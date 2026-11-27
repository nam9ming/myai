"""안성행사알림이의 월별 목록 응답에서 게시물 번호를 읽는다."""

import re

from processing.extraction.validation import decode


MAX_PAGE_ITEMS = 100


def parse_event_listing(raw: bytes, *, page: int) -> tuple[int, list[str]]:
    if type(page) is not int or page < 1:
        raise ValueError("행사 목록 요청의 페이지 번호가 유효하지 않습니다.")

    listing = decode(raw, "input")
    if not isinstance(listing, dict):
        raise ValueError("행사 목록 응답은 JSON 객체여야 합니다.")
    current = listing.get("curPage")
    if type(current) is not int or current != page:
        raise ValueError("행사 목록 응답의 페이지 번호가 요청과 다릅니다.")
    total = listing.get("totalCnt")
    rows = listing.get("list")
    if type(total) is not int or total < 0 or not isinstance(rows, list):
        raise ValueError("행사 목록의 전체 건수 또는 목록 형식이 유효하지 않습니다.")
    if len(rows) > MAX_PAGE_ITEMS:
        raise ValueError("행사 목록의 페이지당 최대 건수를 초과했습니다.")
    if (rows and page - 1 + len(rows) > total) or (page == 1 and total > 0 and not rows):
        raise ValueError("행사 목록의 전체 건수와 행 개수가 맞지 않습니다.")

    ids = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("행사 목록 행은 JSON 객체여야 합니다.")
        value = row.get("idx")
        if type(value) not in (int, str) or re.fullmatch(r"[1-9][0-9]{0,17}", str(value)) is None:
            raise ValueError("행사 목록의 게시물 번호가 유효하지 않습니다.")
        web_id = str(value)
        if web_id in ids:
            raise ValueError("행사 목록에 중복 게시물 번호가 있습니다.")
        ids[web_id] = None
    return total, list(ids)
