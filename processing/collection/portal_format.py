"""포털 표준 API 응답을 검증하고 기존 비교용 CSV 열로 옮긴다."""

from processing.extraction.validation import decode


_COLUMNS = {
    "culture": {
        "fstvlNm": "축제명",
        "opar": "개최장소",
        "fstvlStartDate": "축제시작일자",
        "fstvlEndDate": "축제종료일자",
        "fstvlCo": "축제내용",
        "auspcInsttNm": "주최기관명",
        "homepageUrl": "홈페이지주소",
        "rdnmadr": "소재지도로명주소",
        "lnmadr": "소재지지번주소",
        "latitude": "위도",
        "longitude": "경도",
    },
    "living": {
        "lbrryNm": "도서관명",
        "ctprvnNm": "시도명",
        "signguNm": "시군구명",
        "closeDay": "휴관일",
        "weekdayOperOpenHhmm": "평일운영시작시각",
        "weekdayOperColseHhmm": "평일운영종료시각",
        "satOperOperOpenHhmm": "토요일운영시작시각",
        "satOperCloseHhmm": "토요일운영종료시각",
        "holidayOperOpenHhmm": "공휴일운영시작시각",
        "holidayCloseOpenHhmm": "공휴일운영종료시각",
        "rdnmadr": "소재지도로명주소",
        "operInstitutionNm": "운영기관명",
        "homepageUrl": "홈페이지주소",
    },
}
# 2026-11-29 실제 응답(문화축제 500행·도서관 500행)의 행마다 같았던 열 전체다. 하나라도 다르면 거부한다.
_ITEM_KEYS = {
    "culture": frozenset((*_COLUMNS["culture"], "insttCode", "insttNm", "mnnstNm", "phoneNumber",
                          "referenceDate", "relateInfo", "suprtInsttNm")),
    "living": frozenset((*_COLUMNS["living"], "bookCo", "buldAr", "insttCode", "insttNm", "latitude", "lbrrySe",
                         "lonCo", "lonDaycnt", "longitude", "noneBookCo", "pblictnCo", "phoneNumber", "plotAr",
                         "referenceDate", "seatCo")),
}
_HEADER = {"resultCode": "00", "resultMsg": "NORMAL SERVICE."}
_BODY_KEYS = {"items", "numOfRows", "pageNo", "totalCount"}


def _count(value: object) -> int:
    if type(value) is not int or value < 0:
        raise ValueError("포털 API 페이지 또는 전체 건수가 0 이상의 JSON 정수가 아닙니다.")
    return value


def parse_page(category: str, raw: bytes, page: int, page_size: int) -> tuple[int, list[dict]]:
    """2026-11-29 실제 응답과 같은 구조만 받는다. 확인하지 못한 구조는 추정하지 않고 거부한다."""
    keys = _ITEM_KEYS[_category(category)]
    if type(page) is not int or page < 1 or type(page_size) is not int or page_size < 1:
        raise ValueError("포털 API의 요청 페이지와 페이지당 건수는 양의 정수여야 합니다.")
    document = decode(raw, "input")
    if not isinstance(document, dict) or set(document) != {"header", "body"}:
        raise ValueError("포털 API 응답 최상위가 실제 응답의 header·body 구조가 아닙니다.")
    if document["header"] != _HEADER:
        raise ValueError("포털 API 응답 header가 성공 코드 00·NORMAL SERVICE.와 다릅니다.")
    body = document["body"]
    if not isinstance(body, dict) or set(body) != _BODY_KEYS:
        raise ValueError("포털 API 응답 body의 키가 items·numOfRows·pageNo·totalCount와 다릅니다.")
    if _count(body["pageNo"]) != page or _count(body["numOfRows"]) != page_size:
        raise ValueError("포털 API 응답의 페이지 또는 페이지당 건수가 요청과 다릅니다.")
    total = _count(body["totalCount"])
    expected = min(page_size, total - (page - 1) * page_size)
    # 빈 페이지·1행 페이지의 items 표기는 실제로 보지 못했다. 빈 페이지와 단일 객체 items는 거부한다.
    if expected < 1:
        raise ValueError("포털 API 응답이 빈 페이지(전체 0건 또는 마지막 페이지 뒤)라 받지 않습니다.")
    items = body["items"]
    if not isinstance(items, dict) or set(items) != {"item"} or type(items["item"]) is not list:
        raise ValueError('포털 API 응답 items가 실제 응답의 {"item": [행 목록]} 형식이 아닙니다.')
    rows = items["item"]
    if len(rows) != expected:
        raise ValueError("포털 API 응답의 행 개수가 전체 건수로 계산한 페이지 건수와 다릅니다.")
    for row in rows:
        if not isinstance(row, dict) or set(row) != keys:
            raise ValueError("포털 API 응답 행의 열 이름이 2026-11-29 실제 응답과 다릅니다.")
        if not all(type(value) is str and "\x00" not in value for value in row.values()):
            raise ValueError("포털 API 응답 행에 문자열이 아니거나 NUL이 든 값이 있습니다.")
    return total, rows


def _category(category: str) -> str:
    if not isinstance(category, str) or category not in _COLUMNS:
        raise ValueError("지원하지 않는 포털 자료 분야입니다.")
    return category


def csv_header(category: str) -> list[str]:
    return list(_COLUMNS[_category(category)].values())


def csv_row(category: str, record: dict) -> list[str]:
    """parse_page로 열 이름과 문자열 값을 확인한 행만 받는다."""
    return [record[key] for key in _COLUMNS[_category(category)]]
