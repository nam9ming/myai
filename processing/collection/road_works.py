"""안성시 도로 공사현황 목록과 상세의 공개 항목을 읽는다."""

from datetime import date
from html.parser import HTMLParser
import re

from .official_web import road_detail_url, road_state


_IGNORED_TAGS = {"script", "style", "template", "noscript"}
_VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
_PAGE_LABEL = re.compile(r"현재 페이지\s+([1-9][0-9]{0,17})\s*/\s*전체 페이지\s+([1-9][0-9]{0,17})")
_DETAIL_ACTION = re.compile(r"/depart/roadConstruction/view\.do\?idx=([1-9][0-9]{0,17})")
_ROW_HANDLER = "req.post(this); return false;"
_EMPTY_MESSAGE = "검색된 결과가 없습니다."
_PERIOD = re.compile(r"([0-9]{4}-[0-9]{2}-[0-9]{2}) ~ ([0-9]{4}-[0-9]{2}-[0-9]{2})")
_MAX_ROWS = 100
_BREAK_TAGS = {"br", "p", "li", "ul", "ol"}
_TEXT_TAGS = _BREAK_TAGS | {"span", "a", "b", "strong", "em", "i", "u", "font", "sub", "sup", "small", "wbr"}
PARSER_VERSION = "road-works-parser-v1"
_FIELDS = {
    "지역": "region",
    "사업위치": "location",
    "사업량": "quantity",
    "공사기간": "construction_period",
    "현재현황": "current_status",
    "담당부서": "department",
    "전화번호": "phone",
}
_INVALID_LISTING = "도로 공사현황 목록 HTML 구조가 올바르지 않습니다."
_INVALID_DETAIL = "도로 공사현황 상세 HTML 구조가 올바르지 않습니다."


def _text(parts: list[str]) -> str:
    return " ".join("".join(parts).split())


def _list_action(state: str) -> str:
    code, menu, _ = road_state(state)
    return f"/depart/roadConstruction/list.do?mId={menu}&state={code}"


class _FormParser(HTMLParser):
    """공식 페이지의 유일한 `form#list` 안쪽만 구별해 하위 클래스에 넘긴다."""

    def __init__(self, state: str, error: str):
        super().__init__(convert_charrefs=True)
        self.action = _list_action(state)
        self.error = error
        self.ignored_depth = 0
        self.in_form = False
        self.form_seen = False

    def fail(self):
        raise ValueError(self.error)

    def handle_starttag(self, tag, attrs):
        if tag in _IGNORED_TAGS:
            self.ignored_depth += 1
        values = dict(attrs)
        if tag == "form" and values.get("id") == "list":
            names = [name for name, _ in attrs]
            if (self.ignored_depth or self.in_form or self.form_seen
                    or names.count("id") != 1 or names.count("action") != 1
                    or values.get("action") != self.action):
                self.fail()
            self.in_form = self.form_seen = True
            return
        if tag == "form" and self.in_form:
            self.fail()
        if self.in_form and not self.ignored_depth:
            self.form_start(tag, attrs, values)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in _VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if self.ignored_depth:
            if tag in _IGNORED_TAGS:
                self.ignored_depth -= 1
            return
        if not self.in_form:
            return
        if tag == "form":
            self.form_end()
            self.in_form = False
            return
        self.form_endtag(tag)

    def handle_data(self, data):
        if self.in_form and not self.ignored_depth:
            self.form_data(data)

    def finish(self, text: str):
        if not isinstance(text, str) or "\x00" in text:
            self.fail()
        try:
            self.feed(text)
            self.close()
        except AssertionError:
            self.fail()
        if self.in_form or not self.form_seen or self.ignored_depth:
            self.fail()

    def form_start(self, tag, attrs, values):
        raise NotImplementedError

    def form_endtag(self, tag):
        raise NotImplementedError

    def form_data(self, data):
        raise NotImplementedError

    def form_end(self):
        raise NotImplementedError


class _ListingParser(_FormParser):
    def __init__(self, state: str):
        super().__init__(state, _INVALID_LISTING)
        self.page_text: list[str] | None = None
        self.page_info: tuple[int, int] | None = None
        self.caption: list[str] | None = None
        self.captions: list[str] = []
        self.table: list[str] = []
        self.table_seen = False
        self.body_seen = False
        self.row: dict | None = None
        self.rows: list[dict] = []
        self.links = 0

    def form_start(self, tag, attrs, values):
        if tag == "a" and "data-action" in values:
            self.links += 1
        classes = (values.get("class") or "").split()
        if tag == "p" and "page_num" in classes:
            if self.page_text is not None or self.page_info is not None or self.table:
                self.fail()
            self.page_text = []
            return
        if tag == "table" and "bod_maintain" in classes:
            if self.table or self.table_seen:
                self.fail()
            self.table_seen = True
            self.table.append(tag)
            return
        if not self.table:
            return
        current = self.table[-1]
        if tag == "caption" and current == "table":
            self.caption = []
        elif tag == "tbody":
            if current != "table" or self.body_seen:
                self.fail()
            self.body_seen = True
            self.table.append(tag)
        elif tag == "tr" and "tbody" in self.table:
            if current != "tbody":
                self.fail()
            self.row = {"ids": [], "cells": [], "text": []}
            self.table.append(tag)
        elif tag == "td" and current == "tr":
            self.row["cells"].append(values.get("colspan"))
            self.table.append(tag)
        elif tag == "a" and self.row is not None and "data-action" in values:
            names = [name for name, _ in attrs]
            match = _DETAIL_ACTION.fullmatch(values["data-action"] or "")
            if (names.count("data-action") != 1 or names.count("onclick") != 1
                    or values.get("onclick") != _ROW_HANDLER or match is None):
                self.fail()
            self.row["ids"].append(match[1])

    def form_data(self, data):
        if self.page_text is not None:
            self.page_text.append(data)
        if self.caption is not None:
            self.caption.append(data)
        if self.row is not None:
            self.row["text"].append(data)

    def form_endtag(self, tag):
        if tag == "p" and self.page_text is not None:
            match = _PAGE_LABEL.fullmatch(_text(self.page_text))
            if match is None:
                self.fail()
            self.page_info = (int(match[1]), int(match[2]))
            self.page_text = None
            return
        if tag == "caption" and self.caption is not None:
            self.captions.append(_text(self.caption))
            self.caption = None
            return
        if not self.table or tag not in ("table", "tbody", "tr", "td"):
            return
        current = self.table[-1]
        if tag == "tr" and current == "table":
            return
        if tag == "td" and current != "td":
            return
        if tag != current:
            self.fail()
        if tag == "tr":
            if len(self.rows) == _MAX_ROWS:
                self.fail()
            self.rows.append(self.row)
            self.row = None
        self.table.pop()

    def form_end(self):
        if self.table or not self.body_seen or self.page_info is None or self.page_text is not None:
            self.fail()


def parse_road_listing(raw: bytes, *, state: str, page: int) -> tuple[int, list[str]]:
    """요청 구분·페이지와 대조한 전체 페이지 수와 원래 순서의 공사 번호를 반환한다."""
    _, _, label = road_state(state)
    if type(page) is not int or page < 1 or not isinstance(raw, bytes):
        raise ValueError(_INVALID_LISTING)
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ValueError(_INVALID_LISTING) from None
    parser = _ListingParser(state)
    parser.finish(text)
    if not parser.rows or parser.links != sum(len(row["ids"]) for row in parser.rows):
        raise ValueError(_INVALID_LISTING)
    if len(parser.captions) != 1 or not parser.captions[0].startswith(f"도로 공사 {label} 현황"):
        raise ValueError("도로 공사현황 목록의 구분이 요청과 일치하지 않습니다.")
    current, total = parser.page_info
    if current != page or current > total:
        raise ValueError("도로 공사현황 목록의 페이지 번호가 요청과 일치하지 않습니다.")

    ids: list[str] = []
    for row in parser.rows:
        if len(row["ids"]) > 1:
            raise ValueError(_INVALID_LISTING)
        if row["ids"]:
            if row["ids"][0] in ids:
                raise ValueError("도로 공사현황 목록에 같은 공사 번호가 있습니다.")
            ids.append(row["ids"][0])
            continue
        empty = (len(parser.rows) == 1 and page == total == 1 and row["cells"] == ["3"]
                 and _text(row["text"]) == _EMPTY_MESSAGE)
        if not empty:
            raise ValueError(_INVALID_LISTING)
    return total, ids


class _DetailParser(_FormParser):
    def __init__(self, state: str):
        super().__init__(state, _INVALID_DETAIL)
        self.ids: list[str] = []
        self.title: list[str] | None = None
        self.title_tags: list[str] = []
        self.titles: list[str] = []
        self.region: list[str] | None = None
        self.region_seen = False
        self.pairs: list[tuple[str, str]] = []
        self.cell: list[str] | None = None
        self.cells: list[str] = []

    def form_start(self, tag, attrs, values):
        if tag == "input" and values.get("name") == "idx":
            if [name for name, _ in attrs].count("value") != 1:
                self.fail()
            self.ids.append(values.get("value") or "")
        if self.region is not None:
            self._region_start(tag)
            return
        if self.title is not None:
            if tag not in _TEXT_TAGS:
                self.fail()
            if tag in _BREAK_TAGS:
                self.title.append(" ")
            if tag not in _VOID_TAGS:
                self.title_tags.append(tag)
            return
        classes = (values.get("class") or "").split()
        if tag == "h4":
            if self.titles:
                self.fail()
            self.title = []
        elif tag == "div" and "tbl_form" in classes:
            if self.region_seen:
                self.fail()
            self.region_seen = True
            self.region = ["div"]

    def _region_start(self, tag):
        current = self.region[-1]
        if tag in ("dt", "dd"):
            if current != "dl" or (tag == "dd") != (len(self.cells) == 1) or self.cell is not None:
                self.fail()
            self.cell = []
        elif tag == "dl":
            if len(self.region) != 1:
                self.fail()
            self.cells = []
        elif self.cell is None or tag not in _TEXT_TAGS:
            self.fail()
        elif tag in _BREAK_TAGS:
            self.cell.append(" ")
        if tag not in _VOID_TAGS:
            self.region.append(tag)

    def form_data(self, data):
        if self.title is not None:
            self.title.append(data)
        if self.cell is not None:
            self.cell.append(data)
        elif self.region is not None and data.strip():
            self.fail()

    def form_endtag(self, tag):
        if tag == "br":
            for parts in (self.cell, self.title):
                if parts is not None:
                    parts.append(" ")
        if tag in _VOID_TAGS:
            return
        if self.region is not None:
            if self.region[-1] != tag:
                self.fail()
            self.region.pop()
            if tag in _BREAK_TAGS and self.cell is not None:
                self.cell.append(" ")
            if tag in ("dt", "dd"):
                self.cells.append(_text(self.cell))
                self.cell = None
            elif tag == "dl":
                if len(self.cells) != 2:
                    self.fail()
                self.pairs.append((self.cells[0], self.cells[1]))
            if not self.region:
                self.region = None
            return
        if self.title is not None:
            if self.title_tags and self.title_tags[-1] == tag:
                self.title_tags.pop()
                if tag in _BREAK_TAGS:
                    self.title.append(" ")
            elif not self.title_tags and tag == "h4":
                self.titles.append(_text(self.title))
                self.title = None
            else:
                self.fail()

    def form_end(self):
        if self.region is not None or self.title is not None or not self.region_seen or len(self.titles) != 1:
            self.fail()


def _period(value: str | None) -> tuple[dict | None, str | None]:
    if value is None:
        return None, None
    match = _PERIOD.fullmatch(value)
    try:
        start, end = (date.fromisoformat(match[1]), date.fromisoformat(match[2])) if match else (None, None)
    except ValueError:
        start = end = None
    if start is None:
        return None, "period_unparsed"
    if start > end:
        return None, "period_inverted"
    return {"start": start.isoformat(), "end": end.isoformat()}, None


def parse_road_detail(text: str, *, state: str, project_id: str) -> dict:
    """공사 상세의 표시 문구를 그대로 보관하고 기간은 정확한 날짜 범위만 읽는다."""
    url = road_detail_url(state, project_id)
    parser = _DetailParser(state)
    parser.finish(text)
    if parser.ids != [project_id]:
        raise ValueError("도로 공사현황 상세의 공사 번호가 요청과 일치하지 않습니다.")
    title = parser.titles[0]
    if not title:
        raise ValueError("도로 공사현황 상세의 사업명이 없습니다.")

    fields = dict.fromkeys(_FIELDS.values())
    seen = set()
    for label, value in parser.pairs:
        key = _FIELDS.get(label)
        if key is None:
            raise ValueError(f"도로 공사현황 상세에 알 수 없는 항목이 있습니다: {label[:40]}")
        if key in seen:
            raise ValueError("도로 공사현황 상세의 항목이 중복되었습니다.")
        seen.add(key)
        fields[key] = value or None
    if len(seen) != len(_FIELDS):
        raise ValueError("도로 공사현황 상세에 빠진 항목이 있습니다.")

    flags = [f"missing:{key}" for key, value in fields.items() if value is None]
    period, problem = _period(fields["construction_period"])
    if problem:
        flags.append(problem)
    return {
        "external_id": project_id,
        "official_url": url,
        "listing_state": state,
        "title": title,
        "fields": fields,
        "construction_period_range": period,
        "review_flags": sorted(flags),
    }
