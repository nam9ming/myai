"""포털 표준 API 응답을 검증하고 기존 비교용 CSV 열로 옮긴다."""

from decimal import Decimal
import re

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
        "LBRRY_NM": "도서관명",
        "CTPRVN_NM": "시도명",
        "SIGNGU_NM": "시군구명",
        "CLOSE_DAY": "휴관일",
        "WEEKDAY_OPER_OPEN_HHMM": "평일운영시작시각",
        "WEEKDAY_OPER_COLSE_HHMM": "평일운영종료시각",
        "SAT_OPER_OPER_OPEN_HHMM": "토요일운영시작시각",
        "SAT_OPER_CLOSE_HHMM": "토요일운영종료시각",
        "HOLIDAY_OPER_OPEN_HHMM": "공휴일운영시작시각",
        "HOLIDAY_CLOSE_OPEN_HHMM": "공휴일운영종료시각",
        "RDNMADR": "소재지도로명주소",
        "OPER_INSTITUTION_NM": "운영기관명",
        "HOMEPAGE_URL": "홈페이지주소",
    },
}
_CULTURE_LOCATION = {"auspcInsttNm", "homepageUrl", "rdnmadr", "lnmadr"}
_LIVING_IDENTITY = {"LBRRY_NM", "CTPRVN_NM", "SIGNGU_NM"}


def _unsigned(value: object) -> int:
    if type(value) is str and re.fullmatch(r"[0-9]+", value):
        try:
            value = int(value)
        except ValueError:
            pass
    if type(value) is not int or value < 0:
        raise ValueError("포털 API 페이지 또는 전체 건수 형식이 올바르지 않습니다.")
    return value


def parse_page(raw: bytes, page: int, page_size: int) -> tuple[int, list[dict]]:
    if type(page) is not int or page < 1 or type(page_size) is not int or page_size < 1:
        raise ValueError("포털 API의 요청 페이지와 페이지당 건수는 양의 정수여야 합니다.")
    document = decode(raw, "input")
    response = document.get("response") if isinstance(document, dict) else None
    if not isinstance(response, dict):
        raise ValueError("포털 API 응답 구조가 올바르지 않습니다.")
    header = response.get("header")
    if not isinstance(header, dict) or header.get("resultCode") != "00":
        raise ValueError("포털 API 응답에 성공 코드가 없습니다.")
    body = response.get("body")
    if not isinstance(body, dict):
        raise ValueError("포털 API 응답 본문 형식이 올바르지 않습니다.")
    if _unsigned(body.get("pageNo")) != page or _unsigned(body.get("numOfRows")) != page_size:
        raise ValueError("포털 API 응답의 페이지 또는 페이지당 건수가 요청과 다릅니다.")
    total = _unsigned(body.get("totalCount"))
    expected = max(0, min(page_size, total - (page - 1) * page_size))
    items = body.get("items")
    if not isinstance(items, list) or len(items) != expected or not all(isinstance(item, dict) for item in items):
        raise ValueError("포털 API 응답의 행 형식 또는 개수가 올바르지 않습니다.")
    return total, items


def _columns(category: str) -> dict[str, str]:
    if not isinstance(category, str) or category not in _COLUMNS:
        raise ValueError("지원하지 않는 포털 자료 분야입니다.")
    return _COLUMNS[category]


def csv_header(category: str) -> list[str]:
    return list(_columns(category).values())


def _cell(value: object) -> str:
    if value is None:
        return ""
    if type(value) is str and "\x00" not in value:
        return value
    if type(value) is int or (type(value) is Decimal and value.is_finite()):
        return str(value)
    raise ValueError("포털 API 응답에 지원하지 않는 CSV 필드 값이 있습니다.")


def csv_row(category: str, record: dict) -> list[str]:
    columns = _columns(category)
    if not isinstance(record, dict):
        raise ValueError("포털 API의 행은 객체여야 합니다.")
    if category == "culture":
        location = _CULTURE_LOCATION.intersection(record)
        identity = {"fstvlNm"} | location
        valid = "fstvlNm" in record and bool(location)
    else:
        identity = _LIVING_IDENTITY
        valid = identity.issubset(record)
    if not valid or any(record[key] is not None and type(record[key]) is not str for key in identity):
        raise ValueError("포털 API 응답의 이름 또는 지역 식별 열이 올바르지 않습니다.")
    return [_cell(record.get(key)) for key in columns]
