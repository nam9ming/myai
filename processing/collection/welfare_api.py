"""한국사회보장정보원 지자체복지서비스 OpenAPI(공공데이터포털 15108347)의 요청과 XML 응답 검증.

요소 이름은 공공데이터포털 상세 페이지의 Swagger 명세를 따른다. 실제 인증 API 응답으로는
확인하지 않았으므로 문서와 다른 구조는 추정해 고치지 않고 형식 변경으로 거부한다.
"""

import html
import re
from urllib.parse import unquote, urlencode
from xml.etree import ElementTree

from .official_web import _fetch
from .portal_transport import validate_service_key

HOST = "apis.data.go.kr"
_BASE = "/B554287/LocalGovernmentWelfareInformations"
LIST_PATH = _BASE + "/LcgvWelfarelist"
DETAIL_PATH = _BASE + "/LcgvWelfaredetailed"
CATALOG_URL = "https://www.data.go.kr/data/15108347/openapi.do"
# 복지로 공개 상세 화면. 이전 조사에서 안성시 WLF00000915로 확인한 형식이며 인증 키 없이 열린다.
SERVICE_PAGE = "https://www.bokjiro.go.kr/ssis-tbu/twataa/wlfareInfo/moveTWAT52011M.do"
RESPONSE_MAX_BYTES = 2 * 1024 * 1024
REGION = {"ctpvNm": "경기도", "sggNm": "안성시"}
# 코드표의 정렬순서 001(최신순). 조회수로 바뀌는 인기순보다 페이지 사이 순서가 덜 흔들린다.
LIST_ORDER = "001"
SERV_ID = re.compile(r"WLF[0-9]{8}", re.ASCII)
# Swagger는 최상위 요소를 `response`로, 같은 기관의 중앙부처복지서비스 활용가이드 v2.2 예시는
# `wantedList`·`wantedDtl`로 적는다. 이 API의 실제 이름은 미확인이라 두 문서의 이름만 허용한다.
LIST_ROOTS = ("response", "wantedList")
DETAIL_ROOTS = ("response", "wantedDtl")
# 중앙부처 활용가이드 v2.2 오류표의 정상 코드 0과 공공데이터포털 표준 API의 00만 성공으로 본다.
SUCCESS_CODES = ("0", "00")
ENVELOPE = ("resultCode", "resultMessage")
PAGING = ("numOfRows", "pageNo", "totalCount")
LIST_ITEM = "servList"
LIST_FIELDS = ("servId", "servNm", "servDgst", "servDtlLink", "ctpvNm", "sggNm", "bizChrDeptNm", "lifeNmArray",
               "trgterIndvdlNmArray", "intrsThemaNmArray", "sprtCycNm", "srvPvsnNm", "aplyMtdNm", "inqNum",
               "lastModYmd")
DETAIL_FIELDS = ("servId", "servNm", "enfcBgngYmd", "enfcEndYmd", "bizChrDeptNm", "ctpvNm", "sggNm", "servDgst",
                 "lifeNmArray", "trgterIndvdlNmArray", "intrsThemaNmArray", "sprtCycNm", "srvPvsnNm", "aplyMtdNm",
                 "sprtTrgtCn", "slctCritCn", "alwServCn", "aplyMtdCn", "inqNum", "lastModYmd")
# 하위 목록과 코드표의 서비스구분코드(wlfareInfoDtlCd)
RELATED_LISTS = {"inqplCtadrList": "010", "inqplHmpgReldList": "020", "baslawList": "030", "basfrmList": "040"}
RELATED_FIELDS = ("wlfareInfoDtlCd", "wlfareInfoReldNm", "wlfareInfoReldCn")
_DECLARED_ENCODING = re.compile(r"\s*<\?xml\b[^>]*?\bencoding\s*=\s*[\"']([^\"']*)[\"']")
_ASCII_ESCAPE = re.compile(r"\\u00([0-7][0-9a-fA-F])")
_KEY_ECHO = "복지 API 응답에 인증 키가 포함되어 수집을 중단했습니다."


class WelfareResultError(ValueError):
    """HTTP 200이지만 서비스가 오류를 보낸 경우. 결과 코드 실패, 문서와 다른 봉투, 키 노출이 해당한다."""


def serv_id(value: object) -> str:
    if not isinstance(value, str) or SERV_ID.fullmatch(value) is None:
        raise ValueError("복지서비스 ID는 WLF와 숫자 8자리여야 합니다.")
    return value


def _page_arguments(page: int, page_size: int) -> dict:
    if type(page) is not int or not 1 <= page <= 10000:
        raise ValueError("복지 API 페이지는 1~10000의 정수여야 합니다.")
    if type(page_size) is not int or not 1 <= page_size <= 500:
        raise ValueError("복지 API 페이지당 건수는 1~500의 정수여야 합니다.")
    return {"pageNo": page, "numOfRows": page_size, **REGION, "arrgOrd": LIST_ORDER}


def list_source_url(page: int, page_size: int) -> str:
    """인증 키를 뺀 요청 주소. 기록에는 이 주소만 남긴다."""
    return f"https://{HOST}{LIST_PATH}?{urlencode(_page_arguments(page, page_size))}"


def detail_source_url(service_id: str) -> str:
    return f"https://{HOST}{DETAIL_PATH}?{urlencode({'servId': serv_id(service_id)})}"


def service_page_url(service_id: str) -> str:
    """사람이 검토할 공개 원문 주소. 상세 요청 주소는 키 없이 열리지 않으므로 사람이 검토할 복지로 화면을 쓴다."""
    return f"{SERVICE_PAGE}?{urlencode({'wlfareInfoId': serv_id(service_id)})}"


def reject_key_echo(raw: bytes, service_key: str) -> None:
    """원문·URL 인코딩·JSON 이스케이프(`\\/`·`\\u00XX`)·XML 문자 참조로 바뀐 형태까지 키가 있으면 거부한다.

    NUL 바이트가 있는 본문은 확인하기 전에 거부한다. 키는 ASCII라 UTF-16·UTF-32로 쓰면 원문이든 %-인코딩이든
    반드시 NUL이 끼므로 아래 UTF-8 비교를 빠져나갈 수 있다. ASCII와 NUL만 있으면 UTF-8로도 읽히므로 아래
    디코딩만으로는 막지 못한다. 본문은 `_document`처럼 UTF-8 BOM을 떼고 엄격한 UTF-8로 읽으며, 읽을 수 없으면
    (EBCDIC 등) 키를 찾을 수 없으므로 확인하기 전에 거부한다. 파서도 NUL이 있거나 UTF-8이 아닌 본문은 읽지 않아
    잃는 응답이 없다.
    """
    if b"\x00" in raw:
        raise WelfareResultError("복지 API 응답에 NUL 바이트가 있어 인증 키 포함 여부를 확인할 수 없으므로 수집을 중단했습니다.")
    try:
        text = raw.removeprefix(b"\xef\xbb\xbf").decode("utf-8")
    except UnicodeDecodeError:
        raise WelfareResultError("복지 API 응답이 UTF-8이 아니어서 인증 키 포함 여부를 확인할 수 없으므로 수집을 중단했습니다.") from None
    # 폼 인코딩으로 `+`가 공백으로 풀린 형태도 키를 되살릴 수 있다.
    forms = (service_key, service_key.replace("+", " "))
    # 겹친 인코딩은 바뀌지 않을 때까지 푼다. 5번 안에 끝나지 않으면 확인할 수 없으므로 거부한다.
    for _ in range(5):
        if any(form in text for form in forms):
            raise WelfareResultError(_KEY_ECHO)
        escaped = _ASCII_ESCAPE.sub(lambda match: chr(int(match[1], 16)), text.replace("\\/", "/"))
        decoded = html.unescape(unquote(escaped))
        if decoded == text:
            return
        text = decoded
    raise WelfareResultError("복지 API 응답의 인코딩이 여러 겹이라 인증 키 포함 여부를 확인할 수 없습니다.")


def _request(path: str, arguments: dict, service_key: str) -> bytes:
    service_key = validate_service_key(service_key)
    query = urlencode({**arguments, "serviceKey": service_key})
    raw = _fetch("GET", f"{path}?{query}", None, RESPONSE_MAX_BYTES, host=HOST, source="복지 API")
    reject_key_echo(raw, service_key)
    return raw


def fetch_list(page: int, page_size: int, service_key: str) -> bytes:
    return _request(LIST_PATH, _page_arguments(page, page_size), service_key)


def fetch_detail(service_id: str, service_key: str) -> bytes:
    return _request(DETAIL_PATH, {"servId": serv_id(service_id)}, service_key)


def _document(raw: bytes, roots: tuple[str, ...]) -> ElementTree.Element:
    """DTD 선언을 파싱 전에 거부해 외부·내부 엔터티 확장이 일어나지 않게 한다.

    봉투를 읽을 수 없거나 결과 코드가 성공이 아니면 오류 화면·게이트웨이 응답으로 보고 WelfareResultError를 낸다.
    """
    if not isinstance(raw, bytes) or len(raw) > RESPONSE_MAX_BYTES:
        raise WelfareResultError("복지 API 응답이 허용 크기를 초과했습니다.")
    try:
        text = raw.removeprefix(b"\xef\xbb\xbf").decode("utf-8")
    except UnicodeDecodeError:
        raise WelfareResultError("복지 API 응답은 UTF-8 XML이어야 합니다.") from None
    if "\x00" in text:
        raise WelfareResultError("복지 API 응답에 NUL 문자가 있습니다.")
    if re.search(r"<!(?!--|\[CDATA\[)", text):
        raise WelfareResultError("복지 API 응답에 DOCTYPE·ENTITY 같은 선언이 있어 읽지 않습니다.")
    declared = _DECLARED_ENCODING.match(text)
    if declared and declared[1].lower() not in ("utf-8", "utf8"):
        raise WelfareResultError("복지 API 응답의 XML 선언 인코딩이 UTF-8이 아닙니다.")
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError:
        raise WelfareResultError("복지 API 응답의 XML 형식이 올바르지 않습니다.") from None
    if root.tag not in roots:
        raise WelfareResultError(f"복지 API 응답의 최상위 요소가 문서와 다릅니다({_label(root.tag)}).")
    code = root.findtext("resultCode")
    if code not in SUCCESS_CODES:
        message = _label(root.findtext("resultMessage") or "")
        raise WelfareResultError(f"복지 API 결과 코드가 성공이 아닙니다({_label(code or '없음')}: {message}).")
    return root


def _label(value: str) -> str:
    """오류 문구에 넣을 응답 값. 제어 문자를 지우고 길이를 줄인다."""
    return re.sub(r"[\x00-\x1f\x7f]", " ", value)[:120]


def _leaves(element: ElementTree.Element, documented: tuple[str, ...], groups: tuple[str, ...] = ()) -> tuple:
    """문서의 단일 값 요소와 반복 하위 목록을 나눈다. 문서에 없는 단일 값은 원문 그대로 따로 둔다."""
    if (element.text or "").strip() or any((child.tail or "").strip() for child in element):
        raise ValueError(f"복지 API 응답의 {_label(element.tag)} 요소에 하위 요소 밖의 글자가 있습니다.")
    values, undocumented = {}, {}
    nested = {name: [] for name in groups}
    for child in element:
        name = child.tag
        if name in nested:
            nested[name].append(child)
            continue
        if len(child):
            raise ValueError(f"복지 API 응답에 문서에 없는 하위 구조가 있습니다({_label(name)}).")
        target = values if name in documented else undocumented
        if name in target:
            raise ValueError(f"복지 API 응답에 같은 요소가 반복됩니다({_label(name)}).")
        target[name] = child.text or ""
    return values, undocumented, nested


def _kept(values: dict, undocumented: dict, documented: tuple[str, ...]) -> dict:
    """값은 바꾸지 않고, 없거나 공백뿐인 값은 null과 사유로 남긴다."""
    fields, unknown = {}, {}
    for name in documented:
        value = values.get(name)
        if value is None or not value.strip():
            fields[name] = None
            unknown[name] = "missing" if value is None else "empty"
        else:
            fields[name] = value
    return {"fields": fields, "unknown": unknown, "undocumented": undocumented}


def _unsigned(value: object, label: str) -> int:
    if not isinstance(value, str) or re.fullmatch(r"[0-9]{1,9}", value.strip()) is None:
        raise ValueError(f"복지 API 응답의 {label} 형식이 올바르지 않습니다.")
    return int(value)


def _region(fields: dict, *, required: bool) -> None:
    for name, expected in REGION.items():
        value = fields[name]
        if (value is None and required) or (value is not None and value != expected):
            raise ValueError("복지 API 응답의 시도·시군구가 요청한 지역과 다릅니다.")


def parse_list(raw: bytes, *, page: int, page_size: int) -> tuple[int, list[dict]]:
    """전체 건수와 페이지의 서비스 목록을 돌려준다. 페이지 번호·건수가 요청과 다르면 거부한다."""
    _page_arguments(page, page_size)
    root = _document(raw, LIST_ROOTS)
    values, _, nested = _leaves(root, ENVELOPE + PAGING, (LIST_ITEM,))
    if (_unsigned(values.get("pageNo"), "페이지 번호") != page
            or _unsigned(values.get("numOfRows"), "페이지당 건수") != page_size):
        raise ValueError("복지 API 응답의 페이지 또는 페이지당 건수가 요청과 다릅니다.")
    total = _unsigned(values.get("totalCount"), "전체 건수")
    items = []
    for element in nested[LIST_ITEM]:
        item = _kept(*_leaves(element, LIST_FIELDS)[:2], LIST_FIELDS)
        serv_id(item["fields"]["servId"])
        if item["fields"]["servNm"] is None:
            raise ValueError("복지 API 목록 항목에 서비스명이 없습니다.")
        _region(item["fields"], required=True)
        items.append(item)
    if len(items) != max(0, min(page_size, total - (page - 1) * page_size)):
        raise ValueError("복지 API 목록의 항목 수가 전체 건수·페이지와 맞지 않습니다.")
    ids = [item["fields"]["servId"] for item in items]
    if len(set(ids)) != len(ids):
        raise ValueError("복지 API 목록 페이지에 같은 서비스 ID가 반복됩니다.")
    return total, items


def parse_detail(raw: bytes, *, service_id: str) -> dict:
    """상세 응답의 문서 필드를 원문 그대로 보관한다. 기간·자격·비용은 해석하지 않는다."""
    serv_id(service_id)
    root = _document(raw, DETAIL_ROOTS)
    values, undocumented, nested = _leaves(root, ENVELOPE + DETAIL_FIELDS, tuple(RELATED_LISTS))
    for name in ENVELOPE:
        values.pop(name, None)
    record = _kept(values, undocumented, DETAIL_FIELDS)
    if record["fields"]["servId"] != service_id:
        raise ValueError("복지 API 상세의 서비스 ID가 요청과 다릅니다.")
    if record["fields"]["servNm"] is None:
        raise ValueError("복지 API 상세에 서비스명이 없습니다.")
    _region(record["fields"], required=False)
    related = {}
    for name, code in RELATED_LISTS.items():
        entries = []
        for element in nested[name]:
            entry = _kept(*_leaves(element, RELATED_FIELDS)[:2], RELATED_FIELDS)
            if entry["fields"]["wlfareInfoDtlCd"] not in (None, code):
                raise ValueError(f"복지 API 상세 {name}의 서비스구분코드가 코드표와 다릅니다.")
            entries.append(entry)
        related[name] = entries
    record["related"] = related
    return record
