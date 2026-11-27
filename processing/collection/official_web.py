"""안성시 공식 행사·도서관의 공개 목록과 상세를 요청한다."""

from contextlib import closing
from datetime import date
from http.client import HTTPException, HTTPSConnection
import re
from urllib.parse import urlencode


DETAIL_MAX_BYTES = 8 * 1024 * 1024
_HOST = "www.anseong.go.kr"
OFFICIAL_ORIGIN = f"https://{_HOST}"
_TIMEOUT = 15
_DETAIL_PATHS = {
    "culture": "/event/program/popup/detail.do?idx={}",
    "living": "/library/bbs/view.do?bIdx={}&mId=0401010000&ptIdx=16",
}


class SourceHTTPError(ValueError):
    def __init__(self, status: int):
        self.status = status
        super().__init__(f"공식 웹 HTTP 응답 오류({status}).")


def _detail_path(category: str, web_id: str) -> str:
    if not isinstance(category, str) or category not in _DETAIL_PATHS:
        raise ValueError("지원하지 않는 공식 웹 수집 분야입니다.")
    if not isinstance(web_id, str) or re.fullmatch(r"[1-9][0-9]*", web_id) is None:
        raise ValueError("공식 웹 게시물 번호는 양의 ASCII 정수여야 합니다.")
    return _DETAIL_PATHS[category].format(web_id)


def detail_url(category: str, web_id: str) -> str:
    return OFFICIAL_ORIGIN + _detail_path(category, web_id)


def fetch_detail(category: str, web_id: str, *, limit: int) -> bytes:
    path = _detail_path(category, web_id)
    if len(web_id) > 18:
        raise ValueError("공식 웹 게시물 번호는 최대 18자리여야 합니다.")
    return _fetch("GET", path, None, limit)


def listing_request(category: str, page: int, begin: date | None, end: date | None) -> tuple[str, str, bytes | None]:
    if type(page) is not int or page < 1:
        raise ValueError("목록 페이지는 양의 정수여야 합니다.")
    if category == "culture":
        if type(begin) is not date or type(end) is not date or not 0 <= (end - begin).days <= 30:
            raise ValueError("행사 목록에는 순서대로 최대 31일의 조회 날짜를 지정해야 합니다.")
        query = urlencode({"page": page, "searchSdate": begin.isoformat(), "searchEdate": end.isoformat()})
        return "GET", "/event/program/list/json.do?" + query, None
    if category == "living":
        if begin is not None or end is not None:
            raise ValueError("도서관 목록에는 조회 날짜를 지정하지 않습니다.")
        path = "/library/bbs/list.do?ptIdx=16&mId=0401010000"
        return "POST", path, urlencode({"page": page}).encode("ascii")
    raise ValueError("지원하지 않는 공식 웹 수집 분야입니다.")


def fetch_listing(category: str, page: int, begin: date | None, end: date | None, *, limit: int) -> bytes:
    method, path, body = listing_request(category, page, begin, end)
    return _fetch(method, path, body, limit)


def _fetch(method: str, path: str, body: bytes | None, limit: int, *, host: str = _HOST) -> bytes:
    if type(limit) is not int or not 1 <= limit <= DETAIL_MAX_BYTES:
        raise ValueError("공식 웹 수집의 원문 크기 한도가 유효하지 않습니다.")

    headers = {
        "User-Agent": "yeogi-it/official-source-capture",
        "Accept-Encoding": "identity",
        "Connection": "close",
    }
    try:
        with closing(HTTPSConnection(host, timeout=_TIMEOUT)) as connection:
            if body is None:
                connection.request(method, path, headers=headers)
            else:
                headers["Content-Type"] = "application/x-www-form-urlencoded"
                connection.request(method, path, body=body, headers=headers)
            with connection.getresponse() as response:
                if response.status != 200:
                    raise SourceHTTPError(response.status)
                if (response.getheader("Content-Encoding") or "identity").lower() != "identity":
                    raise ValueError("공식 웹 상세 응답의 인코딩을 지원하지 않습니다.")

                declared = response.getheader("Content-Length")
                transfer = response.getheader("Transfer-Encoding")
                if transfer is not None and (transfer.lower() != "chunked" or declared is not None):
                    raise ValueError("공식 웹 상세 응답의 전송 형식을 확인할 수 없습니다.")
                if declared is not None:
                    declared = declared.strip(" \t")
                    if re.fullmatch(r"[0-9]{1,19}", declared) is None:
                        raise ValueError("공식 웹 상세 응답의 길이가 유효하지 않습니다.")
                    declared = int(declared)
                    if declared > limit:
                        raise ValueError("공식 웹 상세 응답이 허용 크기를 초과했습니다.")

                raw = response.read(limit + 1)
                if len(raw) > limit:
                    raise ValueError("공식 웹 상세 응답이 허용 크기를 초과했습니다.")
                if declared is not None and len(raw) != declared:
                    raise ValueError("공식 웹 상세 응답이 전송 중 중단되었습니다.")
                return raw
    except TimeoutError:
        message = "공식 웹 상세 응답의 대기 시간을 초과했습니다."
    except (OSError, HTTPException):
        message = "공식 웹 상세 응답을 받지 못했습니다."
    raise ValueError(message) from None
