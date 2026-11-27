"""안성시 도서관 공지 목록의 페이지 정보와 게시물 번호를 읽는다."""

from html.parser import HTMLParser
import re


_PAGE_LABEL = re.compile(
    r"현재 페이지\s+([1-9][0-9]{0,17})\s*/\s*전체 페이지\s+([1-9][0-9]{0,17})"
)
_NOTICE_LINK = re.compile(
    r"goTo\.view\('list',\s*'([1-9][0-9]{0,17})',\s*'16',\s*'0401010000'\);\s*return false;"
)
_IGNORED_TAGS = {"script", "style", "template", "noscript"}
_INVALID = "도서관 공지 목록 HTML 구조가 올바르지 않습니다."


class _ListingParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_form = False
        self.form_closed = False
        self.table_sections: list[str] = []
        self.table_seen = False
        self.body_seen = False
        self.ignored_depth = 0
        self.page_text: list[str] | None = None
        self.page_info: tuple[int, int] | None = None
        self.notice_ids: list[str] = []
        self.row_id: str | None = None

    def handle_starttag(self, tag, attrs):
        if tag in _IGNORED_TAGS:
            self.ignored_depth += 1
        if self.ignored_depth:
            return
        attributes = dict(attrs)
        if tag == "form":
            if self.in_form:
                raise ValueError(_INVALID)
            if attributes.get("id") == "list":
                if self.form_closed or sum(key == "id" for key, _ in attrs) != 1:
                    raise ValueError(_INVALID)
                self.in_form = True
            return
        if not self.in_form:
            return
        classes = (attributes.get("class") or "").split()
        if tag == "p" and "page_num" in classes:
            if self.page_text is not None or self.page_info is not None or self.table_sections:
                raise ValueError(_INVALID)
            self.page_text = []
        if tag == "table":
            if self.table_sections or ("bod_list" in classes and self.table_seen):
                raise ValueError(_INVALID)
            if "bod_list" in classes:
                self.table_seen = True
                self.table_sections.append(tag)
        elif self.table_sections:
            self._start_table_tag(tag, attrs)

    def _start_table_tag(self, tag, attrs):
        current = self.table_sections[-1]
        if tag == "tbody":
            if current != "table" or self.body_seen:
                raise ValueError(_INVALID)
            self.body_seen = True
            self.table_sections.append(tag)
        elif tag == "tr" and "tbody" in self.table_sections:
            if current != "tbody":
                raise ValueError(_INVALID)
            self.row_id = None
            self.table_sections.append(tag)
        elif tag == "a" and current == "tr":
            handlers = [(value or "").strip() for key, value in attrs if key == "onclick"]
            if not any(handler.startswith("goTo.view") for handler in handlers):
                return
            match = _NOTICE_LINK.fullmatch(handlers[0]) if len(handlers) == 1 else None
            if match is None or self.row_id is not None:
                raise ValueError(_INVALID)
            self.row_id = match[1]

    def handle_data(self, data):
        if self.page_text is not None and not self.ignored_depth:
            self.page_text.append(data)

    def handle_endtag(self, tag):
        if self.ignored_depth:
            if tag in _IGNORED_TAGS:
                self.ignored_depth -= 1
            return
        if not self.in_form:
            return
        if tag == "form":
            if not self.body_seen or self.table_sections or self.page_info is None:
                raise ValueError(_INVALID)
            self.in_form = False
            self.form_closed = True
        elif tag == "p" and self.page_text is not None:
            label = " ".join("".join(self.page_text).split())
            match = _PAGE_LABEL.fullmatch(label)
            if match is None:
                raise ValueError(_INVALID)
            self.page_info = (int(match[1]), int(match[2]))
            self.page_text = None
        elif self.table_sections and tag in {"table", "tbody", "tr"}:
            current = self.table_sections[-1]
            if tag == "tr" and current == "table":
                return
            if tag != current:
                raise ValueError(_INVALID)
            if tag == "tr":
                if self.row_id is None or self.row_id in self.notice_ids or len(self.notice_ids) == 100:
                    raise ValueError(_INVALID)
                self.notice_ids.append(self.row_id)
            self.table_sections.pop()


def parse_library_listing(raw: bytes, *, page: int) -> tuple[int, list[str]]:
    """요청 페이지와 대조한 전체 페이지 수 및 원래 순서의 게시물 번호를 반환한다."""
    if type(page) is not int or page < 1 or not isinstance(raw, bytes) or b"\x00" in raw:
        raise ValueError(_INVALID)
    parser = _ListingParser()
    try:
        parser.feed(raw.decode("utf-8-sig"))
        parser.close()
    except (UnicodeDecodeError, AssertionError):
        raise ValueError(_INVALID) from None
    if not parser.form_closed or parser.ignored_depth or not parser.notice_ids or parser.page_info is None:
        raise ValueError(_INVALID)
    current_page, total_pages = parser.page_info
    if current_page != page or current_page > total_pages:
        raise ValueError("도서관 공지 목록의 페이지 번호가 요청과 일치하지 않습니다.")
    return total_pages, parser.notice_ids
