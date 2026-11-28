"""한국도로공사 공사 및 도로 차단 계획 OpenAPI 응답과 안성 구간 선택 결과를 비공개로 보관한다.

공공데이터포털 15076650은 제공처 링크형 API다. 요청·출력 항목은 2026-11-28에 받은 제공처 상세 화면
(data.ex.co.kr apiId 0613)의 항목표를 따른다. 키가 없어 실제 응답은 받지 않았다. 항목표에 없는 목록 키 이름과
성공 코드 값은 추정해 넓히지 않고, 다르면 원본과 사유를 남기고 멈춘다.
"""

from datetime import UTC, datetime
import hashlib
import html
import json
import os
from pathlib import Path
import re
import sys
from time import sleep
import unicodedata
from urllib.parse import unquote, urlencode

from processing.extraction.validation import decode

from .capture import (
    CAPTURE_ROOT, bundle_directory, capture_timestamp, open_archive, read_capture_file, read_receipt,
    validate_name, write_new, write_receipt,
)
from .cli import CollectionArguments
from .odcloud_format import PLACEHOLDERS, row_fingerprints
from .official_web import _fetch

HOST = "data.ex.co.kr"
PATH = "/openapi/safeDriving/construction"
CATALOG_URL = "https://www.data.go.kr/data/15076650/openapi.do"
SPEC_URL = "https://data.ex.co.kr/openapi/basicinfo/openApiInfoM?apiId=0613"
# 키는 공공데이터포털이 아니라 고속도로 공공데이터 포털(data.ex.co.kr)이 발급한다.
SERVICE_KEY_ENV = "EX_OPENAPI_KEY"
CLOSURE_SECTION = "collection-road-closures"
CLOSURE_ROOT = CAPTURE_ROOT.with_name(CLOSURE_SECTION)
SCHEMA = "citizen-road-closure-snapshot-v1"
SELECTION_SCHEMA = "road-closure-anseong-v1"
PARSER_VERSION = "ex-construction-parser-v1"
RESPONSE_MAX_BYTES = 2 * 1024 * 1024
PAGE_SIZE = 100
MAX_PAGES = 20
ENVELOPE = ("code", "message", "count", "numOfRows", "pageNo", "pageSize")
FIELDS = ("limtPlanDates", "limtPlanSeq", "hqdrNm", "mtnofKorNm", "cnstnStrtDates", "cnstnStrtTimes",
          "cnstnEndDates", "cnstnEndTimes", "routeCd", "useRotnm", "icNm", "endBlcPntVal", "strtBlcPntVal",
          "blcCtnt", "totCrgwCnt", "blcForm", "cnstnCtnt", "hveqUseYn")
# 안성 판단은 차단노선구간·차단구간명만 쓴다. 본부·지사는 관할이라 위치 근거가 아니다.
SECTION_FIELDS = ("useRotnm", "icNm")
OTHER_FIELDS = ("hqdrNm", "mtnofKorNm", "blcCtnt", "cnstnCtnt")
RULE = "useRotnm 또는 icNm에 '안성' 포함('안성면' 제외)"
# 항목표에 값이 없다. 같은 포털 다른 API의 'SUCCESS'만 성공으로 보고 다르면 거부한다(미확인).
SUCCESS_CODES = ("SUCCESS",)
_ANSEONG = re.compile("안성(?!면)")
_KEY = re.compile(r"[A-Za-z0-9_+/=-]{8,256}", re.ASCII)
_ROUTE = re.compile(r"[0-9]{4}", re.ASCII)
_ASCII_ESCAPE = re.compile(r"\\u00([0-7][0-9a-fA-F])")
_LABEL = "고속도로 차단 계획 API"


def validate_key(key: str) -> str:
    if not isinstance(key, str) or _KEY.fullmatch(key) is None:
        raise ValueError(f"{SERVICE_KEY_ENV}에 고속도로 공공데이터 포털 인증 키를 설정해 주세요.")
    return key


def route_code(value: str) -> str:
    if not isinstance(value, str) or _ROUTE.fullmatch(value) is None:
        raise ValueError("노선번호는 ASCII 숫자 4자리여야 합니다(예: 0010).")
    return value


def _arguments(route: str, page: int) -> dict:
    if type(page) is not int or not 1 <= page <= MAX_PAGES:
        raise ValueError(f"페이지는 1~{MAX_PAGES}의 정수여야 합니다.")
    return {"type": "json", "routeCd": route_code(route), "numOfRows": PAGE_SIZE, "pageNo": page}


def source_url(route: str, page: int) -> str:
    """키를 뺀 요청 주소. 수집 기록에 쓴다."""
    return f"https://{HOST}{PATH}?{urlencode(_arguments(route, page))}"


def reject_key_echo(raw: bytes, key: str) -> None:
    """키가 원문·URL 인코딩·JSON 이스케이프·HTML 문자 참조로 들어 있으면 저장 전에 거부한다.

    NUL이 있거나 UTF-8이 아닌 본문은 키 비교를 빠져나갈 수 있어 확인하기 전에 거부한다. 파서도 읽지 않는다.
    """
    if b"\x00" in raw:
        raise ValueError(f"{_LABEL} 응답에 NUL 바이트가 있어 인증 키 포함 여부를 확인할 수 없습니다.")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError(f"{_LABEL} 응답이 UTF-8이 아니어서 인증 키 포함 여부를 확인할 수 없습니다.") from None
    forms = (key, key.replace("+", " "))
    for _ in range(5):
        if any(form in text for form in forms):
            raise ValueError(f"{_LABEL} 응답에 인증 키가 포함되어 수집을 중단했습니다.")
        decoded = html.unescape(unquote(_ASCII_ESCAPE.sub(lambda m: chr(int(m[1], 16)), text.replace("\\/", "/"))))
        if decoded == text:
            return
        text = decoded
    raise ValueError(f"{_LABEL} 응답의 인코딩이 여러 겹이라 인증 키 포함 여부를 확인할 수 없습니다.")


def fetch_page(route: str, page: int, key: str) -> bytes:
    query = urlencode({"key": validate_key(key), **_arguments(route, page)})
    raw = _fetch("GET", f"{PATH}?{query}", None, RESPONSE_MAX_BYTES, host=HOST, source=_LABEL)
    reject_key_echo(raw, key)
    return raw


def _label(value: object) -> str:
    return re.sub(r"[\x00-\x1f\x7f]", " ", str(value))[:120]


def _count(value: object, name: str) -> int:
    # 항목표는 모든 값을 string으로 적는다. 숫자 문자열과 정수만 받는다.
    if type(value) is int and value >= 0:
        return value
    if isinstance(value, str) and re.fullmatch(r"[0-9]{1,9}", value, re.ASCII):
        return int(value)
    raise ValueError(f"{_LABEL} 응답의 {name} 형식이 올바르지 않습니다.")


def parse_page(raw: bytes, route: str, page: int) -> tuple[int, str, list[dict]]:
    """전체 건수, 목록 키 이름, 항목을 돌려준다. 값은 원문 그대로 두고 없거나 공백뿐이면 null과 사유를 남긴다."""
    _arguments(route, page)
    try:
        document = decode(raw, "input", max_bytes=RESPONSE_MAX_BYTES)
    except ValueError:
        raise ValueError(f"{_LABEL} 응답을 UTF-8 JSON으로 읽을 수 없습니다.") from None
    if not isinstance(document, dict):
        raise ValueError(f"{_LABEL} 응답이 JSON 객체가 아닙니다.")
    if document.get("code") not in SUCCESS_CODES:
        raise ValueError(f"{_LABEL} 결과 코드가 성공이 아닙니다"
                                 f"({_label(document.get('code'))}: {_label(document.get('message'))}).")
    # 항목표에 목록 키 이름이 없다. 봉투 밖의 키가 정확히 하나일 때만 그 값을 목록으로 본다.
    extra = set(document) - set(ENVELOPE)
    if set(ENVELOPE) - set(document) or len(extra) != 1 or not isinstance(document[next(iter(extra))], list):
        raise ValueError(f"{_LABEL} 응답 구조가 항목표와 다릅니다.")
    list_key = extra.pop()
    if _count(document["pageNo"], "페이지 번호") != page or _count(document["numOfRows"], "페이지당 건수") != PAGE_SIZE:
        raise ValueError(f"{_LABEL} 응답의 페이지 또는 페이지당 건수가 요청과 다릅니다.")
    total = _count(document["count"], "전체 건수")
    _count(document["pageSize"], "전체 페이지 수")
    rows = document[list_key]
    if len(rows) != max(0, min(PAGE_SIZE, total - (page - 1) * PAGE_SIZE)):
        raise ValueError(f"{_LABEL} 응답의 항목 수가 전체 건수·페이지와 맞지 않습니다.")
    items = []
    for row in rows:
        if not isinstance(row, dict) or any(not (value is None or type(value) in (str, int)) for value in row.values()):
            raise ValueError(f"{_LABEL} 응답 항목에 지원하지 않는 값 형식이 있습니다.")
        fields, unknown = {}, {}
        for name in FIELDS:
            value = row.get(name)
            blank = value is None or (isinstance(value, str) and not value.strip())
            fields[name] = None if blank else value
            if blank:
                unknown[name] = "missing" if name not in row else "empty"
        # 노선번호로 거른 목록인지 확인한다. 형식이 달라도(예: 10과 0010) 맞춰 고치지 않는다.
        if fields["routeCd"] != route:
            raise ValueError(f"{_LABEL} 응답 항목의 노선코드가 요청과 다릅니다.")
        undocumented = {name: value for name, value in row.items() if name not in FIELDS}
        items.append({"fields": fields, "unknown": unknown, "undocumented": undocumented})
    return total, list_key, items


def _mentions(fields: dict, names: tuple[str, ...], pattern: str | re.Pattern) -> list[str]:
    return [name for name in names if isinstance(fields[name], str)
            and re.search(pattern, unicodedata.normalize("NFC", fields[name]))]


def _no_location(value: object) -> bool:
    """위치 판정용 빈 값. 공용 `_blank`와 같지만 글자 여부를 고정된 유니코드 3.2 DB로 본다."""
    # isalnum·casefold는 파이썬마다 유니코드 판이 달라 같은 원본의 판정이 바뀐다. 3.2 뒤에 생긴 문자는 Cn이라 자리표시로 보고 검토로 보낸다.
    # 줄표 대신 흔히 치는 'ㅡ' 같은 한글 호환 자모(U+3131–U+318E)도 자리표시로 본다. 자모만으로 된 지명은 없다.
    if not isinstance(value, str):
        return value is None
    return ("".join(unicodedata.normalize("NFC", value).split()).casefold() in PLACEHOLDERS
            or not any(unicodedata.ucd_3_2_0.category(c)[0] in "LN" and not "\u3131" <= c <= "\u318e" for c in value))


def select_items(page: int, items: list[dict], matched: list, review: list) -> None:
    """차단 구간 글자에 안성이 보이는 항목만 고른다. 판단할 수 없거나 다른 열에만 보이면 사람 검토로 넘긴다."""
    for position, item in enumerate(items, 1):
        fields, place = item["fields"], {"page": page, "position": position}
        if found := _mentions(fields, SECTION_FIELDS, _ANSEONG):
            matched.append({**place, "match": {name: fields[name] for name in found}, "record": item})
        elif _no_location(fields["icNm"]):
            # 항목표만으로는 useRotnm(차단노선구간)이 노선명인지 구간인지 알 수 없다. icNm이 비면 구간 근거가 없을 수 있다.
            # '-'·'없음' 같은 자리표시도 위치를 알려 주지 않으므로 빈 값과 같이 검토로 보낸다. 저장 값은 원문 그대로 둔다.
            review.append({**place, "reason": "blank_section", "mentions": _mentions(fields, FIELDS, "안성"),
                           "record": item})
        elif found := _mentions(fields, SECTION_FIELDS, "안성"):
            review.append({**place, "reason": "mention", "mentions": found, "record": item})
        elif found := _mentions(fields, OTHER_FIELDS, "안성"):
            review.append({**place, "reason": "other_mention", "mentions": found, "record": item})


def _selection(route: str, matched: list, review: list) -> tuple[bytes, dict]:
    document = {"schema_version": SELECTION_SCHEMA, "parser_version": PARSER_VERSION, "route_cd": route,
                "rule": RULE, "rows": matched, "needs_review": review}
    raw = (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    return raw, {"file": "anseong.json", "sha256": hashlib.sha256(raw).hexdigest(),
                 "rows": len(matched), "needs_review": len(review)}


def _receipt_base(route: str) -> dict:
    return {"schema_version": SCHEMA, "parser_version": PARSER_VERSION, "route_cd": route,
            "endpoint": f"https://{HOST}{PATH}", "catalog_url": CATALOG_URL, "spec_url": SPEC_URL,
            "page_size": PAGE_SIZE}


def _read(raw: bytes, route: str, page: int, total: int | None, list_key: str | None,
          seen: set[bytes], matched: list, review: list) -> tuple[int, str, int]:
    found, key, items = parse_page(raw, route, page)
    if (total is not None and found != total) or (list_key is not None and key != list_key):
        raise ValueError(f"{_LABEL} 조회 중 전체 건수 또는 목록 키가 달라졌습니다.")
    if found == 0:
        # 노선번호 표를 확인하지 못해 잘못된 노선번호와 '차단 계획 없음'을 구별할 수 없다.
        raise ValueError(f"{_LABEL}의 전체 건수가 0건이라 노선번호 오류와 차단 계획 없음을 구별할 수 없어 완료로 보지 않습니다.")
    if found > MAX_PAGES * PAGE_SIZE:
        raise ValueError(f"{_LABEL}의 전체 건수가 페이지 수집 한도를 초과했습니다.")
    # 서버가 pageNo를 무시하거나 정렬이 흔들리면 앞 페이지 행이 다시 오고 다른 행이 빠진다. 한 응답 안의 중복은 허용한다.
    fingerprints = row_fingerprints(items)
    if fingerprints & seen:
        raise ValueError(f"{_LABEL}가 앞 페이지의 행을 다시 보냈습니다. 빠진 행이 있을 수 있습니다.")
    seen |= fingerprints
    select_items(page, items, matched, review)
    return found, key, len(items)


def collect_road_closures(route: str, name: str, root: Path, key: str) -> dict:
    """응답 원본을 먼저 쓰고 `closures.json`을 마지막에 쓴다. 키는 요청에만 쓰고 기록하지 않는다."""
    validate_name(name)
    route_code(route)
    validate_key(key)
    pages, matched, review, seen = [], [], [], set()
    total = list_key = None
    rows = 0
    result = {"snapshot_id": name, "status": "failed", "pages": 0, "rows": 0}
    with bundle_directory(root, name) as directory:
        receipt = {**_receipt_base(route), "responses": pages}
        try:
            for page in range(1, MAX_PAGES + 1):
                if page > 1:
                    sleep(1.0)
                raw = fetch_page(route, page, key)
                filename = f"page-{page}.json"
                write_new(directory, filename, raw)
                entry = {"page": page, "file": filename, "source_url": source_url(route, page),
                         "fetched_at": datetime.now(UTC).isoformat(), "sha256": hashlib.sha256(raw).hexdigest()}
                pages.append(entry)
                total, list_key, entry["rows"] = _read(raw, route, page, total, list_key, seen, matched, review)
                rows += entry["rows"]
                if rows == total:
                    break
            if rows != total:
                raise ValueError(f"{_LABEL}의 보고 건수를 모두 수집하지 못했습니다.")
            selection, receipt["selection"] = _selection(route, matched, review)
            write_new(directory, "anseong.json", selection)
            receipt["list_key"] = list_key
            result["status"] = "complete"
        except ValueError as error:
            receipt["error"] = str(error)
        result.update(pages=len(pages), rows=rows)
        write_receipt(directory, "closures.json", {**receipt, **result})
    return result


def read_road_closure_snapshot(private_root: Path, name: str) -> tuple[bytes, dict]:
    """보관한 응답 원본을 다시 검증·선택해 `anseong.json`과 기록을 대조한다."""
    validate_name(name)
    with open_archive(private_root, Path(CLOSURE_SECTION) / name) as directory:
        receipt = read_receipt(directory, "closures.json")
        route, responses = receipt.get("route_cd"), receipt.get("responses")
        if (receipt.get("snapshot_id") != name or receipt.get("status") != "complete" or not isinstance(route, str)
                or any(receipt.get(k) != v for k, v in _receipt_base(route_code(route)).items())
                or not isinstance(responses, list) or not 1 <= len(responses) <= MAX_PAGES):
            raise ValueError("완료된 고속도로 차단 계획 수집 기록을 확인할 수 없습니다.")
        matched, review, seen = [], [], set()
        total = list_key = None
        rows = 0
        for page, entry in enumerate(responses, 1):
            filename = f"page-{page}.json"
            if (not isinstance(entry, dict) or entry.get("page") != page or entry.get("file") != filename
                    or entry.get("source_url") != source_url(route, page) or (total is not None and rows == total)):
                raise ValueError("고속도로 차단 계획 수집 기록의 페이지가 맞지 않습니다.")
            capture_timestamp(entry.get("fetched_at"))
            raw = read_capture_file(directory, filename, RESPONSE_MAX_BYTES)
            if entry.get("sha256") != hashlib.sha256(raw).hexdigest():
                raise ValueError("고속도로 차단 계획 응답 원본 해시가 맞지 않습니다.")
            total, list_key, received = _read(raw, route, page, total, list_key, seen, matched, review)
            if type(entry.get("rows")) is not int or entry["rows"] != received:
                raise ValueError("고속도로 차단 계획 수집 기록의 페이지 건수가 맞지 않습니다.")
            rows += received
        if (rows != total or receipt.get("rows") != rows or receipt.get("pages") != len(responses)
                or receipt.get("list_key") != list_key):
            raise ValueError("고속도로 차단 계획 수집 기록의 전체 건수가 맞지 않습니다.")
        selection, computed = _selection(route, matched, review)
        if (read_capture_file(directory, "anseong.json", RESPONSE_MAX_BYTES * MAX_PAGES) != selection
                or receipt.get("selection") != computed):
            raise ValueError("안성 구간 선택 결과가 응답 원본 또는 수집 기록과 다릅니다.")
        return selection, receipt


def main() -> int:
    parser = CollectionArguments(description=__doc__)
    parser.add_argument("--route-cd", required=True)
    parser.add_argument("--name", required=True)
    args = parser.parse_args()
    try:
        summary = collect_road_closures(args.route_cd, args.name, CLOSURE_ROOT, os.environ.get(SERVICE_KEY_ENV, ""))
    except ValueError as error:
        print(f"고속도로 차단 계획 수집 실패: {error}", file=sys.stderr)
        return 1
    except OSError:
        print("고속도로 차단 계획 원본 또는 완료 기록을 저장할 수 없습니다.", file=sys.stderr)
        return 1
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if summary["status"] == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
