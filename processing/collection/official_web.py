"""안성시 공식 행사·도서관·도로 공사현황·시청·안성배움e 공지의 공개 목록과 상세를 요청한다."""

from contextlib import closing
from datetime import date
from http.client import HTTPException, HTTPSConnection
import re
from types import MappingProxyType
from typing import NamedTuple
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
    def __init__(self, status: int, source: str = "공식 웹"):
        self.status = status
        super().__init__(f"{source} HTTP 응답 오류({status}).")


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


ROAD_STATES = {
    "planned": ("0", "0901020200", "예정"),
    "ongoing": ("1", "0901020100", "진행중"),
    "completed": ("2", "0901020300", "완료"),
}
_PROJECT_ID = re.compile(r"[1-9][0-9]{0,17}")


def road_state(state: str) -> tuple[str, str, str]:
    if not isinstance(state, str) or state not in ROAD_STATES:
        raise ValueError("지원하지 않는 도로 공사현황 구분입니다.")
    return ROAD_STATES[state]


def road_listing_path(state: str, page: int) -> str:
    code, menu, _ = road_state(state)
    if type(page) is not int or page < 1:
        raise ValueError("목록 페이지는 양의 정수여야 합니다.")
    return "/depart/roadConstruction/list.do?" + urlencode(
        {"searchGubun": 1, "state": code, "mId": menu, "page": page})


def _road_detail_path(state: str, project_id: str) -> str:
    code, menu, _ = road_state(state)
    if not isinstance(project_id, str) or _PROJECT_ID.fullmatch(project_id) is None:
        raise ValueError("도로 공사 번호는 18자리 이하의 양의 ASCII 정수여야 합니다.")
    return "/depart/roadConstruction/view.do?" + urlencode({"idx": project_id, "mId": menu, "state": code})


def road_detail_url(state: str, project_id: str) -> str:
    return OFFICIAL_ORIGIN + _road_detail_path(state, project_id)


def fetch_road_listing(state: str, page: int, *, limit: int) -> bytes:
    return _fetch("GET", road_listing_path(state, page), None, limit)


def fetch_road_detail(state: str, project_id: str, *, limit: int) -> bytes:
    return _fetch("GET", _road_detail_path(state, project_id), None, limit)


class Board(NamedTuple):
    """같은 게시판 CMS를 쓰는 공식 게시판. label은 오류 문구, source는 파싱 결과에 쓴다.

    title_class가 있으면 상세 제목을 `<h4>` 대신 본문 영역 바로 아래의 그 class 블록에서 읽는다.
    context_path는 페이지가 선언하는 `contextPath`이며 첨부 다운로드 주소 앞에 붙는다.
    """

    prefix: str
    menu: str
    label: str
    source: str
    pt_idx: str = "16"
    title_class: str | None = None
    context_path: str = ""


BOARDS = MappingProxyType({
    "city": Board("/portal/bbs", "0501010000", "시청 공지", "city_notice"),
    "edu": Board("/edu/portal/bbs", "0901040000", "안성배움e 공지", "edu_notice",
                 pt_idx="300", title_class="bod_view_title", context_path="/edu"),
})
_NOTICE_ID = _PROJECT_ID


def board(name: str) -> Board:
    if not isinstance(name, str) or name not in BOARDS:
        raise ValueError("지원하지 않는 공식 게시판입니다.")
    return BOARDS[name]


def _board_detail_path(name: str, notice_id: str) -> str:
    info = board(name)
    if not isinstance(notice_id, str) or _NOTICE_ID.fullmatch(notice_id) is None:
        raise ValueError("공지 번호는 18자리 이하의 양의 ASCII 정수여야 합니다.")
    return f"{info.prefix}/view.do?bIdx={notice_id}&mId={info.menu}&ptIdx={info.pt_idx}"


def board_detail_url(name: str, notice_id: str) -> str:
    return OFFICIAL_ORIGIN + _board_detail_path(name, notice_id)


def board_listing_path(name: str) -> str:
    info = board(name)
    return f"{info.prefix}/list.do?ptIdx={info.pt_idx}&mId={info.menu}"


def fetch_board_listing(name: str, page: int, *, limit: int) -> bytes:
    path = board_listing_path(name)
    if type(page) is not int or page < 1:
        raise ValueError("목록 페이지는 양의 정수여야 합니다.")
    return _fetch("POST", path, urlencode({"page": page}).encode("ascii"), limit)


def fetch_board_detail(name: str, notice_id: str, *, limit: int) -> bytes:
    return _fetch("GET", _board_detail_path(name, notice_id), None, limit)


def fetch_listing(category: str, page: int, begin: date | None, end: date | None, *, limit: int) -> bytes:
    method, path, body = listing_request(category, page, begin, end)
    return _fetch(method, path, body, limit)


def _fetch(method: str, path: str, body: bytes | None, limit: int, *, host: str = _HOST,
           source: str = "공식 웹") -> bytes:
    """`source`는 오류 문구에 쓰는 출처 이름이다."""
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
                    raise SourceHTTPError(response.status, source)
                if (response.getheader("Content-Encoding") or "identity").lower() != "identity":
                    raise ValueError(f"{source} 응답의 인코딩을 지원하지 않습니다.")

                declared = response.getheader("Content-Length")
                transfer = response.getheader("Transfer-Encoding")
                if transfer is not None and (transfer.lower() != "chunked" or declared is not None):
                    raise ValueError(f"{source} 응답의 전송 형식을 확인할 수 없습니다.")
                if declared is not None:
                    declared = declared.strip(" \t")
                    if re.fullmatch(r"[0-9]{1,19}", declared) is None:
                        raise ValueError(f"{source} 응답의 길이가 유효하지 않습니다.")
                    declared = int(declared)
                    if declared > limit:
                        raise ValueError(f"{source} 응답이 허용 크기를 초과했습니다.")

                raw = response.read(limit + 1)
                if len(raw) > limit:
                    raise ValueError(f"{source} 응답이 허용 크기를 초과했습니다.")
                if declared is not None and len(raw) != declared:
                    raise ValueError(f"{source} 응답이 전송 중 중단되었습니다.")
                return raw
    except TimeoutError:
        message = f"{source} 응답의 대기 시간을 초과했습니다."
    except (OSError, HTTPException):
        message = f"{source} 응답을 받지 못했습니다."
    raise ValueError(message) from None
