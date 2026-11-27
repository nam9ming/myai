"""안성시 도서관·시청 공지 목록의 페이지 정보와 게시물 번호를 읽는다."""

from html.parser import HTMLParser
import re

from .official_web import board as board_info


_PAGE_LABEL = re.compile(
    r"현재 페이지\s+([1-9][0-9]{0,17})\s*/\s*전체 페이지\s+([1-9][0-9]{0,17})"
)
_LIBRARY_MENU = "0401010000"
_ROW_NUMBER = re.compile(r"[1-9][0-9]{0,17}")
_IGNORED_TAGS = {"script", "style", "template", "noscript"}


def _notice_link(menu: str) -> re.Pattern:
    return re.compile(r"goTo\.view\('list',\s*'([1-9][0-9]{0,17})',\s*'16',\s*'" + menu + r"'\);\s*return false;")


class _ListingParser(HTMLParser):
    """`detect_pins`가 거짓이면 기존 도서관 목록과 같은 기준으로만 행을 읽는다."""

    def __init__(self, menu: str, invalid: str, *, detect_pins: bool):
        super().__init__()
        self.link = _notice_link(menu)
        self.invalid = invalid
        self.detect_pins = detect_pins
        self.rows: list[tuple[str, bool]] = []
        self.seen: set[str] = set()
        self.number: list[str] | None = None
        self.number_open = False
        self.number_images: list[str] = []
        self.in_form = False
        self.form_closed = False
        self.table_sections: list[str] = []
        self.table_seen = False
        self.body_seen = False
        self.ignored_depth = 0
        self.page_text: list[str] | None = None
        self.page_info: tuple[int, int] | None = None
        self.row_id: str | None = None

    def handle_starttag(self, tag, attrs):
        if tag in _IGNORED_TAGS:
            self.ignored_depth += 1
        if self.ignored_depth:
            return
        attributes = dict(attrs)
        if tag == "form":
            if self.in_form:
                raise ValueError(self.invalid)
            if attributes.get("id") == "list":
                if self.form_closed or sum(key == "id" for key, _ in attrs) != 1:
                    raise ValueError(self.invalid)
                self.in_form = True
            return
        if not self.in_form:
            return
        classes = (attributes.get("class") or "").split()
        if tag == "p" and "page_num" in classes:
            if self.page_text is not None or self.page_info is not None or self.table_sections:
                raise ValueError(self.invalid)
            self.page_text = []
        if tag == "table":
            if self.table_sections or ("bod_list" in classes and self.table_seen):
                raise ValueError(self.invalid)
            if "bod_list" in classes:
                self.table_seen = True
                self.table_sections.append(tag)
        elif self.table_sections:
            self._start_table_tag(tag, attrs)

    def _start_table_tag(self, tag, attrs):
        current = self.table_sections[-1]
        if tag == "tbody":
            if current != "table" or self.body_seen:
                raise ValueError(self.invalid)
            self.body_seen = True
            self.table_sections.append(tag)
        elif tag == "tr" and "tbody" in self.table_sections:
            if current != "tbody":
                raise ValueError(self.invalid)
            self.row_id = None
            self.number, self.number_open, self.number_images = None, False, []
            self.table_sections.append(tag)
        elif tag == "a" and current == "tr":
            handlers = [(value or "").strip() for key, value in attrs if key == "onclick"]
            if not any(handler.startswith("goTo.view") for handler in handlers):
                return
            match = self.link.fullmatch(handlers[0]) if len(handlers) == 1 else None
            if match is None or self.row_id is not None:
                raise ValueError(self.invalid)
            self.row_id = match[1]
        if self.detect_pins and current == "tr":
            self._start_number_tag(tag, attrs)

    def _start_number_tag(self, tag, attrs):
        """번호 칸은 숫자 또는 `공지` 아이콘 하나만 허용해 고정 글을 추정하지 않는다."""
        if tag in ("td", "th"):
            self.number_open = False
            classes = [value for key, value in attrs if key == "class"]
            if len(classes) > 1:
                raise ValueError(self.invalid)
            if tag == "td" and "list_num" in ((classes[0] or "") if classes else "").split():
                if self.number is not None:
                    raise ValueError(self.invalid)
                self.number, self.number_open = [], True
        elif self.number_open:
            alts = [value for key, value in attrs if key == "alt"]
            if tag != "img" or len(alts) != 1:
                raise ValueError(self.invalid)
            self.number_images.append(alts[0])

    def handle_data(self, data):
        if self.page_text is not None and not self.ignored_depth:
            self.page_text.append(data)
        if self.number_open and self.number is not None and not self.ignored_depth:
            self.number.append(data)

    def handle_endtag(self, tag):
        if self.ignored_depth:
            if tag in _IGNORED_TAGS:
                self.ignored_depth -= 1
            return
        if not self.in_form:
            return
        if tag in ("td", "th"):
            self.number_open = False
        if tag == "form":
            if not self.body_seen or self.table_sections or self.page_info is None:
                raise ValueError(self.invalid)
            self.in_form = False
            self.form_closed = True
        elif tag == "p" and self.page_text is not None:
            label = " ".join("".join(self.page_text).split())
            match = _PAGE_LABEL.fullmatch(label)
            if match is None:
                raise ValueError(self.invalid)
            self.page_info = (int(match[1]), int(match[2]))
            self.page_text = None
        elif self.table_sections and tag in {"table", "tbody", "tr"}:
            current = self.table_sections[-1]
            if tag == "tr" and current == "table":
                return
            if tag != current:
                raise ValueError(self.invalid)
            if tag == "tr":
                self._end_row()
            self.table_sections.pop()

    def _end_row(self):
        self.number_open = False
        if self.row_id is None or len(self.rows) == 100:
            raise ValueError(self.invalid)
        pinned = False
        if self.detect_pins:
            number = "".join(self.number or []).strip()
            if self.number is None or not (
                (self.number_images == ["공지"] and not number)
                or (not self.number_images and _ROW_NUMBER.fullmatch(number))
            ):
                raise ValueError(self.invalid)
            pinned = bool(self.number_images)
        elif self.row_id in self.seen:
            raise ValueError(self.invalid)
        self.seen.add(self.row_id)
        self.rows.append((self.row_id, pinned))


def _parse(raw: bytes, page: int, menu: str, label: str, *, detect_pins: bool) -> tuple[int, list[tuple[str, bool]]]:
    invalid = f"{label} 목록 HTML 구조가 올바르지 않습니다."
    if type(page) is not int or page < 1 or not isinstance(raw, bytes) or b"\x00" in raw:
        raise ValueError(invalid)
    parser = _ListingParser(menu, invalid, detect_pins=detect_pins)
    try:
        parser.feed(raw.decode("utf-8-sig"))
        parser.close()
    except (UnicodeDecodeError, AssertionError):
        raise ValueError(invalid) from None
    if not parser.form_closed or parser.ignored_depth or not parser.rows or parser.page_info is None:
        raise ValueError(invalid)
    current_page, total_pages = parser.page_info
    if current_page != page or current_page > total_pages:
        raise ValueError(f"{label} 목록의 페이지 번호가 요청과 일치하지 않습니다.")
    return total_pages, parser.rows


def parse_library_listing(raw: bytes, *, page: int) -> tuple[int, list[str]]:
    """요청 페이지와 대조한 전체 페이지 수 및 원래 순서의 게시물 번호를 반환한다."""
    total_pages, rows = _parse(raw, page, _LIBRARY_MENU, "도서관 공지", detect_pins=False)
    return total_pages, [notice_id for notice_id, _ in rows]


def parse_board_listing(raw: bytes, *, board: str, page: int) -> tuple[int, list[str], list[str]]:
    """전체 페이지 수와 번호가 붙은 글, 매 페이지에 반복되는 상단 고정 글을 원래 순서로 나누어 반환한다."""
    _, menu, label, _ = board_info(board)
    total_pages, rows = _parse(raw, page, menu, label, detect_pins=True)
    numbered = [notice_id for notice_id, pinned in rows if not pinned]
    pinned = [notice_id for notice_id, pinned in rows if pinned]
    if not numbered:
        raise ValueError(f"{label} 목록에 번호가 붙은 글이 없습니다.")
    for ids in (numbered, pinned):
        if len(set(ids)) != len(ids):
            raise ValueError(f"{label} 목록에 같은 게시물 번호가 있습니다.")
    return total_pages, numbered, pinned
