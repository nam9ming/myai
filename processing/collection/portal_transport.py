"""공공데이터포털의 행사와 도서관 표준 API를 조회한다."""

import re
from urllib.parse import unquote_to_bytes, urlencode

from .official_web import DETAIL_MAX_BYTES, _fetch


_HOST = "api.data.go.kr"
_PATHS = {
    "culture": "/openapi/tn_pubr_public_cltur_fstvl_api",
    "living": "/openapi/tn_pubr_public_lbrry_api",
}
_KEY = re.compile(r"[A-Za-z0-9_+/=-]{8,256}", re.ASCII)
_ASCII_ESCAPE = re.compile(rb"\\u00([0-7][0-9a-fA-F])")


def _portal_path(category: str) -> str:
    if not isinstance(category, str) or category not in _PATHS:
        raise ValueError("지원하지 않는 공공데이터포털 수집 분야입니다.")
    return _PATHS[category]


def portal_endpoint(category: str) -> str:
    return f"https://{_HOST}{_portal_path(category)}"


def validate_service_key(service_key: str) -> str:
    if not isinstance(service_key, str) or _KEY.fullmatch(service_key) is None:
        raise ValueError("공공데이터포털의 디코딩된 서비스 키 형식이 올바르지 않습니다.")
    return service_key


def fetch_portal_page(category: str, page: int, page_size: int, service_key: str) -> bytes:
    path = _portal_path(category)
    if type(page) is not int or not 1 <= page <= 2_147_483_647:
        raise ValueError("포털 API 페이지는 양의 32비트 정수여야 합니다.")
    if type(page_size) is not int or not 1 <= page_size <= 1000:
        raise ValueError("포털 API 페이지당 건수는 1~1000의 정수여야 합니다.")
    service_key = validate_service_key(service_key)
    query = urlencode({"pageNo": page, "numOfRows": page_size, "type": "json", "serviceKey": service_key})
    raw = _fetch("GET", f"{path}?{query}", None, DETAIL_MAX_BYTES, host=_HOST)

    key = service_key.encode("ascii")
    decoded = _ASCII_ESCAPE.sub(lambda match: bytes([int(match[1], 16)]), raw)
    if key in raw or key in unquote_to_bytes(decoded.replace(rb"\/", b"/")):
        raise ValueError("공공데이터포털 응답에 인증 키가 포함되어 수집을 중단했습니다.")
    return raw
