"""경기도교통정보센터 돌발정보 Open API(getIncidentInfo) 응답을 비공개 묶음으로 보관하고 다시 검증한다.

요소 이름은 공식 명세 페이지의 응답결과 예시 이미지(소문자 태그)를 따른다. 인증 키가 필요한 실제 API는
호출하지 않았고 합성 응답으로만 시험했다. 예시와 다른 구조는 추정해 고치지 않고 형식 변경으로 거부한다.
"""

import hashlib
import json
import os
from pathlib import Path
import re
import sys
from urllib.parse import urlencode
from xml.etree import ElementTree

from .batch import save_web
from .capture import (
    CAPTURE_ROOT, bundle_directory, capture_timestamp, open_archive, read_capture_file, read_receipt,
    validate_name, write_receipt,
)
from .cli import CollectionArguments
from .official_web import _fetch
from .welfare_api import reject_key_echo

HOST = "openapigits.gg.go.kr"
PATH = "/api/rest/getIncidentInfo"
SOURCE_URL = f"https://{HOST}{PATH}"
MANUAL_URL = f"https://{HOST}/api/jsp/manual_getIncidentInfo.jsp?m1=2&m2=6"
TERMS_URL = f"https://{HOST}/api/jsp/apiKey_requestInfo.jsp"
GITS_SECTION = "collection-gits"
GITS_ROOT = CAPTURE_ROOT.with_name(GITS_SECTION)
SCHEMA = "citizen-gits-incident-snapshot-v1"
RECORD_SCHEMA = "citizen-gits-incident-v1"
PARSER_VERSION = "gits-incident-parser-v1"
SERVICE_KEY_ENV = "GITS_SERVICE_KEY"
RESPONSE_MAX_BYTES = 4 * 1024 * 1024
RAW_FILE = "incidents.xml"
PARSED_FILE = "incidents.json"
RECEIPT_FILE = "capture.json"
LABEL = "GITS 돌발 API"
# 응답코드 상세목록의 0(정상적으로 처리되었습니다)과 4(결과가 존재하지 않습니다)만 정상 응답으로 본다.
OK_CODE, EMPTY_CODE = "0", "4"
ENVELOPE = ("commsgheader", "msgheader", "msgbody")
HEADER_FIELDS = ("headercd", "headermsg", "itemcount")
ITEM = "itemlist"
ITEM_FIELDS = ("routeid", "linkid", "spotid", "regseq", "confirmdate", "startdate", "estenddate", "enddate",
               "restricttype", "incidesc", "inciplace1", "inciplace2", "coord_x", "coord_y")
# 명세의 돌발 지점1(도로명)·지점2(방향, 구간). '안성방향'·'안성 방면'과 '(안성·평택방향)'처럼
# 방향으로 끝나는 괄호 안의 '안성'은 진행 방향이라 위치로 보지 않는다.
PLACE_FIELDS = ("inciplace1", "inciplace2")
_ANSEONG = re.compile(r"안성(?!\s*(?:방향|방면)|[^()]*(?:방향|방면)\s*\))")
NO_BOUNDARY = "위치 문구에 '안성'이 없고, 공식 안성시 경계 좌표를 확보하지 못해 좌표로 판정하지 않습니다."
# 키 형식은 명세에 없다. 요청 주소에 그대로 넣을 수 있는 ASCII만 받는다.
_KEY = re.compile(r"[A-Za-z0-9_+/=-]{8,256}", re.ASCII)
_DECLARED_ENCODING = re.compile(r"\s*<\?xml\b[^>]*?\bencoding\s*=\s*[\"']([^\"']*)[\"']")


def validate_service_key(service_key: str) -> str:
    if not isinstance(service_key, str) or _KEY.fullmatch(service_key) is None:
        raise ValueError("GITS 인증 키 형식이 올바르지 않습니다.")
    return service_key


def fetch_incidents(service_key: str) -> bytes:
    """도로·링크 ID 없이 경기도 전체 돌발정보를 한 번 요청한다. 키가 되돌아온 응답은 저장 전에 거부한다."""
    service_key = validate_service_key(service_key)
    raw = _fetch("GET", f"{PATH}?{urlencode({'serviceKey': service_key})}", None, RESPONSE_MAX_BYTES,
                 host=HOST, source=LABEL)
    reject_key_echo(raw, service_key, source=LABEL, error=ValueError)
    return raw


def _label(value: str) -> str:
    """오류 문구에 넣을 응답 값. 제어 문자를 지우고 길이를 줄인다."""
    return re.sub(r"[\x00-\x1f\x7f]", " ", value)[:120]


def _document(raw: bytes) -> ElementTree.Element:
    """복지 API 파서와 같이 UTF-8만 받고 DTD 선언을 파싱 전에 거부해 엔터티 확장을 막는다."""
    if not isinstance(raw, bytes) or len(raw) > RESPONSE_MAX_BYTES:
        raise ValueError(f"{LABEL} 응답이 허용 크기를 초과했습니다.")
    try:
        text = raw.removeprefix(b"\xef\xbb\xbf").decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError(f"{LABEL} 응답은 UTF-8 XML이어야 합니다.") from None
    if "\x00" in text:
        raise ValueError(f"{LABEL} 응답에 NUL 문자가 있습니다.")
    if re.search(r"<!(?!--|\[CDATA\[)", text):
        raise ValueError(f"{LABEL} 응답에 DOCTYPE·ENTITY 같은 선언이 있어 읽지 않습니다.")
    declared = _DECLARED_ENCODING.match(text)
    if declared and declared[1].lower() not in ("utf-8", "utf8"):
        raise ValueError(f"{LABEL} 응답의 XML 선언 인코딩이 UTF-8이 아닙니다.")
    try:
        return ElementTree.fromstring(text)
    except ElementTree.ParseError:
        raise ValueError(f"{LABEL} 응답의 XML 형식이 올바르지 않습니다.") from None


def _children(element: ElementTree.Element, allowed: tuple[str, ...], *, repeat: str | None = None) -> dict:
    """예시에 있는 하위 요소만 받는다. `repeat` 외의 요소가 반복되거나 하위 요소 밖에 글자가 있으면 거부한다."""
    if (element.text or "").strip() or any((child.tail or "").strip() for child in element):
        raise ValueError(f"{LABEL} 응답의 {_label(element.tag)} 요소에 하위 요소 밖의 글자가 있습니다.")
    found = {name: [] for name in allowed}
    for child in element:
        if child.tag not in found or (child.tag != repeat and found[child.tag]):
            raise ValueError(f"{LABEL} 응답의 {_label(element.tag)}에 예시와 다른 요소가 있습니다({_label(child.tag)}).")
        found[child.tag].append(child)
    return found


def _item(element: ElementTree.Element) -> dict:
    """값은 바꾸지 않고, 없거나 공백뿐인 값은 null과 사유로 남긴다. 예시에 없는 단일 값은 원문 그대로 따로 둔다."""
    if (element.text or "").strip() or any((child.tail or "").strip() for child in element):
        raise ValueError(f"{LABEL} 응답의 {ITEM} 요소에 하위 요소 밖의 글자가 있습니다.")
    values, undocumented = {}, {}
    for child in element:
        if len(child):
            raise ValueError(f"{LABEL} 응답에 예시에 없는 하위 구조가 있습니다({_label(child.tag)}).")
        # 명세 표의 대소문자 이름(endDate 등)은 예시와 다른 형식이다. 값이 undocumented로 빠지지 않게 거부한다.
        if child.tag not in ITEM_FIELDS and child.tag.lower() in ITEM_FIELDS:
            raise ValueError(f"{LABEL} 응답의 {ITEM}에 예시와 대소문자가 다른 요소가 있습니다({_label(child.tag)}).")
        target = values if child.tag in ITEM_FIELDS else undocumented
        if child.tag in target:
            raise ValueError(f"{LABEL} 응답에 같은 요소가 반복됩니다({_label(child.tag)}).")
        target[child.tag] = child.text or ""
    fields, unknown = {}, {}
    for name in ITEM_FIELDS:
        value = values.get(name)
        if value is None or not value.strip():
            fields[name] = None
            unknown[name] = "missing" if value is None else "empty"
        else:
            fields[name] = value
    if fields["regseq"] is None:
        raise ValueError(f"{LABEL} 돌발 항목에 돌발상황 고유번호(regseq)가 없습니다.")
    return {"fields": fields, "unknown": unknown, "undocumented": undocumented,
            "anseong_relevance": anseong_relevance(fields)}


def anseong_relevance(fields: dict) -> dict:
    """돌발 지점 문구만으로 판정한다. 공식 경계가 없어 좌표·돌발 내용 문구로는 안성 여부를 정하지 않는다."""
    matched = [name for name in PLACE_FIELDS if fields[name] is not None and _ANSEONG.search(fields[name])]
    if matched:
        return {"status": "location_text", "matched_fields": matched}
    return {"status": "needs_review", "matched_fields": [], "reason": NO_BOUNDARY}


def parse_incidents(raw: bytes) -> dict:
    """결과 코드·메시지·건수와 돌발 항목을 원문 그대로 돌려준다. 시각·차로·좌표는 해석하지 않는다."""
    root = _document(raw)
    # 예시에는 속성이 없다. 속성 값은 필드에 담기지 않고 조용히 빠지므로 형식 변경으로 거부한다.
    attributed = next((element for element in root.iter() if element.attrib), None)
    if attributed is not None:
        raise ValueError(f"{LABEL} 응답의 {_label(attributed.tag)} 요소에 예시에 없는 속성이 있습니다.")
    if root.tag != "serviceresult":
        raise ValueError(f"{LABEL} 응답의 최상위 요소가 예시와 다릅니다({_label(root.tag)}).")
    parts = _children(root, ENVELOPE)
    if not parts["msgheader"]:
        raise ValueError(f"{LABEL} 응답에 msgheader가 없습니다.")
    # 예시의 commsgheader는 비어 있다. 내용이 있으면 게이트웨이 오류일 수 있어 읽지 않는다.
    common = parts["commsgheader"]
    if common and (len(common[0]) or (common[0].text or "").strip()):
        raise ValueError(f"{LABEL} 응답의 commsgheader에 예시에 없는 내용이 있습니다.")
    header = _children(parts["msgheader"][0], HEADER_FIELDS)
    if any(len(element) for found in header.values() for element in found):
        raise ValueError(f"{LABEL} 응답의 msgheader에 예시에 없는 하위 구조가 있습니다.")
    code, message, count = ((found[0].text or "") if found else None for found in header.values())
    if code not in (OK_CODE, EMPTY_CODE):
        raise ValueError(f"{LABEL} 결과 코드가 정상이 아닙니다({_label(code or '없음')}: {_label(message or '')}).")
    items = _children(parts["msgbody"][0], (ITEM,), repeat=ITEM)[ITEM] if parts["msgbody"] else []
    # 결과 없음은 건수가 없거나 0이고 항목도 없을 때만 받는다. 건수와 항목이 어긋나면 어느 쪽도 믿지 않는다.
    if code == EMPTY_CODE and (items or count not in (None, "0")):
        raise ValueError(f"{LABEL} 응답이 결과 없음(4)인데 돌발 항목이나 0이 아닌 itemcount가 있습니다.")
    if code == OK_CODE and (count is None or re.fullmatch(r"[0-9]{1,9}", count) is None or int(count) != len(items)):
        raise ValueError(f"{LABEL} 응답의 결과 데이터 개수(itemcount)가 돌발 항목 수와 맞지 않습니다.")
    return {"result_code": code, "result_message": message, "item_count": count,
            "items": [_item(element) for element in items]}


def _parsed(digest: str, record: dict) -> dict:
    return {"schema_version": RECORD_SCHEMA, "parser_version": PARSER_VERSION, "sha256": digest, "record": record}


def _counts(record: dict) -> dict:
    return {"items": len(record["items"]),
            "location_text": sum(item["anseong_relevance"]["status"] == "location_text" for item in record["items"])}


def collect_incidents(name: str, root: Path, service_key: str) -> dict:
    """원본 응답을 먼저 쓰고 `capture.json`을 마지막에 쓴다. 인증 키는 요청에만 쓰고 기록하지 않는다."""
    validate_name(name)
    if not service_key:
        raise ValueError(f"{SERVICE_KEY_ENV}에 경기도교통정보센터에서 발급받은 인증 키를 설정해 주세요.")
    validate_service_key(service_key)
    result = {"capture_id": name, "status": "fetch_failed", "items": 0, "location_text": 0}
    with bundle_directory(root, name) as directory:
        receipt = {"schema_version": SCHEMA, "source_url": SOURCE_URL, "manual_url": MANUAL_URL, "terms_url": TERMS_URL}
        try:
            raw = fetch_incidents(service_key)
        except ValueError as error:
            receipt["error"] = str(error)
        else:
            receipt["response"] = save_web(directory, RAW_FILE, raw)
            try:
                record = parse_incidents(raw)
            except ValueError as error:
                result["status"] = "parse_failed"
                receipt["error"] = str(error)
            else:
                write_receipt(directory, PARSED_FILE, _parsed(receipt["response"]["sha256"], record))
                receipt["parsed_file"] = PARSED_FILE
                result.update(status="parsed", **_counts(record))
        write_receipt(directory, RECEIPT_FILE, {**receipt, **result})
    return result


def read_incidents(private_root: Path, name: str) -> tuple[dict, dict]:
    """보관한 응답 원본의 해시를 확인하고 현재 파서로 다시 만든 결과를 보관본·기록과 대조한다."""
    validate_name(name)
    with open_archive(private_root, Path(GITS_SECTION) / name) as directory:
        receipt = read_receipt(directory, RECEIPT_FILE)
        response = receipt.get("response")
        if (receipt.get("schema_version") != SCHEMA or receipt.get("capture_id") != name
                or receipt.get("status") != "parsed" or receipt.get("source_url") != SOURCE_URL
                or receipt.get("parsed_file") != PARSED_FILE
                or not isinstance(response, dict) or response.get("file") != RAW_FILE):
            raise ValueError(f"파싱이 완료된 {LABEL} 수집 기록을 확인할 수 없습니다.")
        capture_timestamp(response.get("fetched_at"))
        raw = read_capture_file(directory, RAW_FILE, RESPONSE_MAX_BYTES)
        digest = hashlib.sha256(raw).hexdigest()
        if response.get("sha256") != digest:
            raise ValueError(f"{LABEL} 응답 원본 해시가 수집 기록과 다릅니다.")
        stored = read_receipt(directory, PARSED_FILE)
        if stored.get("parser_version") != PARSER_VERSION:
            raise ValueError("다른 파서 버전으로 만든 파싱 결과입니다. 현재 버전으로 다시 수집해 주세요.")
        record = parse_incidents(raw)
        if stored != _parsed(digest, record) or any(receipt.get(key) != value for key, value in _counts(record).items()):
            raise ValueError(f"{LABEL} 파싱 결과가 원본 또는 수집 기록과 다릅니다.")
        return stored, receipt


def main() -> int:
    parser = CollectionArguments(description=__doc__)
    parser.add_argument("--name", required=True)
    args = parser.parse_args()
    try:
        summary = collect_incidents(args.name, GITS_ROOT, os.environ.get(SERVICE_KEY_ENV, ""))
    except ValueError as error:
        print(f"{LABEL} 수집 실패: {error}", file=sys.stderr)
        return 1
    except OSError:
        print(f"{LABEL} 원본 또는 완료 기록을 저장할 수 없습니다.", file=sys.stderr)
        return 1
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if summary["status"] == "parsed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
