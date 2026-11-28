"""안성시 고시·공고 게시판(새올 고시공고)의 공개 목록과 상세를 요청하고 표시 문구를 읽는다."""

from datetime import date
import re
from urllib.parse import quote, urlencode

from .html_tokens import PinnedHTMLParser
from .libraries import _ATTACHMENT_FORMATS, _NoticeParser
from .official_web import OFFICIAL_ORIGIN, _fetch

LABEL = "고시·공고"
PARSER_VERSION = "gosi-notice-parser-v2"
_MENU = "0501040000"
# 고시/공고 구분. 같은 화면의 입법예고·입찰공고는 다른 값을 쓴다.
_SE_CODE = "01"
_DETAIL_ACTION = f"/portal/saeol/gosiView.do?mId={_MENU}"
_NOTICE_ID = re.compile(r"[1-9][0-9]{0,17}")
_IGNORED_TAGS = {"script", "style", "template", "noscript"}
_CELL_TAGS = {"a", "br", "span", "strong", "b", "em", "i", "u", "font"}
_CELLS = ("gosi_num", "gosi_tit", "gosi_dept", "gosi_date")
_TOTAL = re.compile(r"Total ([0-9]{1,18}) Page ([1-9][0-9]{0,17}) / ([1-9][0-9]{0,17})")
_CAPTION = "고시/공고게시판 목록"
_INVALID_LISTING = f"{LABEL} 목록 HTML 구조가 올바르지 않습니다."
# 첨부 링크는 eminwon.anseong.go.kr의 내려받기 주소로 이동하는 스크립트다. 그 호스트의 robots.txt는 2026-11-28 확인 시
# HTTP 302를 반환해 판단할 수 없었으므로 주소는 검토 후보로만 남기고 요청하지 않는다.
_DOWNLOAD = re.compile(r"javascript:goDownload\('([^']*)', '([^']*)', '([^']*)'\)")
_DOWNLOAD_URL = "https://eminwon.anseong.go.kr/emwp/jsp/ofr/FileDown.jsp"
_PREVIEW = re.compile(r"fn_egov_gosi_preview\('([1-9][0-9]{0,17})','([^']*)','([^']*)','([^']*)','([^']*)'\);"
                      r" return false;")
# 페이지 스크립트는 encodeURI로 인자를 붙인다. encodeURI가 그대로 두는 문자 가운데 질의 구분자는 주소를 확정하지 않는다.
_URI_SAFE = ";,/?:@&=+$!*'()#"
_QUERY_DELIMITERS = set("&=#+")
# 번호 체계는 발행 주체(안성시·안성시 농업기술센터·안성시 공도읍 …)마다 따로라, 번호 앞 주체 문구까지 원문 그대로 담는다.
# 주체는 `경기도`·`안성시`로 시작할 때만 읽는다(붙여 쓴 `안성시공도읍`, 괄호 `공고(제…호)` 포함). `다시 공고`처럼
# 낱말 끝만 보고 주체를 지어내지 않도록 다른 주체는 번호만 남긴다. 여는 괄호를 담았으면 닫는 괄호도 있어야 한다.
_NOTICE_NUMBER = re.compile(r"(?:(?:경기도|안성시)(?: ?[가-힣]{1,20}){0,3}? ?(?:고시|공고) ?(\()?)?"
                            r"제\s?[0-9]{4}\s?-\s?[0-9]{1,6}\s?호(?(1)\))")
_MEDIA_LIMIT = 40


def _notice_key(number: str) -> str:
    # 공백·괄호를 지우고, `경기도 안성시 …`·`경기도 및 안성시 …`는 `안성시 …`와 같은 주체로 본다.
    # `경기도 고시`처럼 도 자체 발행은 그대로 둔다.
    return re.sub(r"^경기도[가-힣]*?(?=안성시)", "", re.sub(r"[\s()]", "", number))


def _text(parts: list[str]) -> str:
    return " ".join("".join(parts).split())


def gosi_listing_path(page: int) -> str:
    if type(page) is not int or page < 1:
        raise ValueError("목록 페이지는 양의 정수여야 합니다.")
    return "/portal/saeol/gosiList.do?" + urlencode({"seCode": _SE_CODE, "mId": _MENU, "page": page})


def _detail_path(notice_id: str) -> str:
    if not isinstance(notice_id, str) or _NOTICE_ID.fullmatch(notice_id) is None:
        raise ValueError("고시·공고 번호는 18자리 이하의 양의 ASCII 정수여야 합니다.")
    return "/portal/saeol/gosiView.do?" + urlencode({"notAncmtMgtNo": notice_id, "mId": _MENU})


def gosi_detail_url(notice_id: str) -> str:
    return OFFICIAL_ORIGIN + _detail_path(notice_id)


def fetch_gosi_listing(page: int, *, limit: int) -> bytes:
    return _fetch("GET", gosi_listing_path(page), None, limit)


def fetch_gosi_detail(notice_id: str, *, limit: int) -> bytes:
    return _fetch("GET", _detail_path(notice_id), None, limit)


class _ListingParser(PinnedHTMLParser):
    """요청 주소를 되돌려 주는 유일한 `form#listForm` 안의 목록 표만 읽는다."""

    def __init__(self, page: int):
        super().__init__()
        self.action = gosi_listing_path(page)
        self.link = re.compile(rf"javascript:boardView\('{page}', '([1-9][0-9]{{0,17}})'\);return false;")
        self.ignored = 0
        self.in_form = self.form_seen = False
        self.total: list[str] | None = None
        self.totals: list[str] = []
        self.caption: list[str] | None = None
        self.captions: list[str] = []
        self.table: list[str] = []
        self.table_seen = False
        self.row: dict | None = None
        self.cell: list[str] | None = None
        self.rows: list[dict] = []

    def fail(self):
        raise ValueError(_INVALID_LISTING)

    def markup_error(self):
        return ValueError(f"{LABEL} 목록 HTML에 브라우저와 해석이 갈리는 태그·주석·스크립트 표기가 있습니다.")

    def handle_starttag(self, tag, attrs):
        super().handle_starttag(tag, attrs)
        if tag in _IGNORED_TAGS:
            self.ignored += 1
        if self.ignored:
            return
        values = dict(attrs)
        names = [name for name, _ in attrs]
        if tag == "form":
            if self.in_form:
                self.fail()
            if values.get("id") == "listForm":
                if (self.form_seen or names.count("id") != 1 or names.count("action") != 1
                        or values["action"] != self.action):
                    raise ValueError(f"{LABEL} 목록이 요청한 게시판·페이지와 일치하지 않습니다.")
                self.in_form = self.form_seen = True
            return
        if not self.in_form:
            return
        classes = (values.get("class") or "").split()
        if tag == "div" and "board_page" in classes:
            if self.total is not None or self.table:
                self.fail()
            self.total = []
        elif tag == "table" and "tableSt_list" in classes:
            if self.table or self.table_seen:
                self.fail()
            self.table_seen = True
            self.table.append(tag)
        elif self.table:
            self._table_start(tag, values, names, classes)

    def _table_start(self, tag, values, names, classes):
        current = self.table[-1]
        if self.cell is not None:
            if tag not in _CELL_TAGS:
                self.fail()
            if tag == "br":
                self.cell.append(" ")
            elif tag == "a":
                if "onclick" not in values:
                    self.fail()
                match = self.link.fullmatch(values["onclick"] or "")
                if match is None or names.count("onclick") != 1 or self.row["cells"][-1] != "gosi_tit":
                    self.fail()
                self.row["ids"].append(match[1])
            if tag != "br":
                self.table.append(tag)
        elif tag == "caption" and current == "table":
            self.caption = []
            self.table.append(tag)
        elif tag in ("thead", "tbody") and current == "table":
            self.table.append(tag)
        elif tag == "tr" and current in ("thead", "tbody"):
            if current == "tbody":
                self.row = {"cells": [], "texts": [], "ids": []}
            self.table.append(tag)
        elif tag in ("th", "td") and current == "tr":
            if self.row is not None:
                if tag != "td" or names.count("class") != 1:
                    self.fail()
                kinds = [name for name in classes if name in _CELLS]
                if len(kinds) != 1:
                    self.fail()
                self.row["cells"].append(kinds[0])
                self.cell = []
            self.table.append(tag)
        elif current not in ("thead", "th"):
            self.fail()

    def handle_data(self, data):
        super().handle_data(data)
        if self.ignored or not self.in_form:
            return
        for parts in (self.total, self.caption, self.cell):
            if parts is not None:
                parts.append(data)

    def handle_endtag(self, tag):
        if self.ignored:
            if tag in _IGNORED_TAGS:
                self.ignored -= 1
            return
        if not self.in_form:
            return
        if tag == "form":
            if self.table or self.total is not None:
                self.fail()
            self.in_form = False
        elif tag == "div" and self.total is not None:
            self.totals.append(_text(self.total))
            self.total = None
        elif self.table and tag == "br":
            # 브라우저는 `</br>`을 `<br>`로 읽어 줄을 바꾼다.
            if self.cell is not None:
                self.cell.append(" ")
            return
        elif self.table:
            if self.table[-1] != tag:
                self.fail()
            self.table.pop()
            if tag == "caption":
                self.captions.append(_text(self.caption))
                self.caption = None
            elif tag == "td" and self.cell is not None:
                self.row["texts"].append(_text(self.cell) or None)
                self.cell = None
            elif tag == "tr" and self.row is not None:
                if len(self.rows) == 100:
                    self.fail()
                self.rows.append(self.row)
                self.row = None

    def finish(self, raw: bytes):
        if not isinstance(raw, bytes) or b"\x00" in raw:
            self.fail()
        try:
            self.feed(raw.decode("utf-8-sig"))
            self.close()
        except (UnicodeDecodeError, AssertionError):
            self.fail()
        if self.in_form or not self.form_seen or self.ignored or self.table or not self.table_seen:
            self.fail()


def parse_gosi_listing(raw: bytes, *, page: int) -> tuple[int, list[dict]]:
    """요청 페이지와 대조한 전체 페이지 수와 원래 순서의 목록 항목(표시 문구 그대로)을 반환한다."""
    parser = _ListingParser(page)
    parser.finish(raw)
    if len(parser.captions) != 1 or not parser.captions[0].startswith(_CAPTION):
        raise ValueError(f"{LABEL} 목록의 게시판 구분이 요청과 일치하지 않습니다.")
    match = _TOTAL.fullmatch(parser.totals[0]) if len(parser.totals) == 1 else None
    if match is None:
        raise ValueError(_INVALID_LISTING)
    current, total = int(match[2]), int(match[3])
    if current != page or current > total:
        raise ValueError(f"{LABEL} 목록의 페이지 번호가 요청과 일치하지 않습니다.")
    if not parser.rows:
        raise ValueError(_INVALID_LISTING)
    items, seen = [], set()
    for row in parser.rows:
        if tuple(row["cells"]) != _CELLS or len(row["ids"]) != 1:
            raise ValueError(_INVALID_LISTING)
        notice_id = row["ids"][0]
        if notice_id in seen:
            raise ValueError(f"{LABEL} 목록에 같은 게시물 번호가 있습니다.")
        seen.add(notice_id)
        number, title, department, registered = row["texts"]
        items.append({"notice_id": notice_id, "notice_number": number, "title": title,
                      "department": department, "registered_date": registered})
    return total, items


def _download_url(arguments: tuple[str, str, str]) -> str | None:
    if any(_QUERY_DELIMITERS.intersection(value) for value in arguments):
        return None
    try:
        user, system, path = (quote(value, safe=_URI_SAFE) for value in arguments)
    except UnicodeEncodeError:
        return None
    return f"{_DOWNLOAD_URL}?user_file_nm={user}&sys_file_nm={system}&file_path={path}"


class _GosiParser(_NoticeParser):
    """도서관·게시판 공지와 같은 본문 허용 목록·태그 경계 규칙에 고시·공고 머리 항목과 첨부 스크립트 해석을 더한다."""

    def __init__(self, notice_id: str):
        super().__init__(label=LABEL)
        self.notice_id = notice_id
        self.detail_actions: list[str | None] = []
        self.attachments: list[dict] = []
        self.downloads: list[tuple[str, str, str] | None] = []
        self.anchor = None
        self.file_section_seen = False

    def handle_starttag(self, tag, attrs):
        # 상위 파서가 태그를 넣은 뒤의 상태로 판단한다. 최상위 form은 쌓이지 않고, 첨부 영역은 `bod_view` 바로 아래 dl이다.
        super().handle_starttag(tag, attrs)
        names = [name for name, _ in attrs]
        values = dict(attrs)
        if not self.tags and not self.hidden_depth and tag == "form" and values.get("id") == "detailForm":
            if names.count("id") != 1 or names.count("action") != 1:
                raise ValueError(f"{LABEL} 상세 폼의 HTML 속성이 중복되었습니다.")
            self.detail_actions.append(values["action"])
        if self.hidden_depth or not self.tags:
            return
        if tag == "dl" and self.attachment_open and len(self.tags) == 2:
            # 첨부가 없는 글도 템플릿은 빈 `dl.view_file`을 출력한다(없는 번호 화면에서 확인). 영역의 유무로 형식 변경을 가린다.
            if self.file_section_seen:
                raise ValueError(f"{LABEL} 첨부 영역이 중복되었습니다.")
            self.file_section_seen = True
        if tag == "li" and self.tags == ["div", "div", "ul", "li"] and self.section is None:
            classes = (values.get("class") or "").split()
            for name, section in (("view_write", "notice_number"), ("view_hit", "department")):
                if name in classes:
                    if section in self.parts:
                        raise ValueError(f"{LABEL} 필드가 중복되었습니다.")
                    self.section, self.section_depth, self.parts[section] = section, len(self.tags), []
                    break
        if tag == "a" and self.attachment_open:
            self._attachment_link(values, names)

    def _attachment_link(self, values, names):
        if self.anchor is not None:
            raise ValueError(f"{LABEL}의 첨부 링크가 중첩되었습니다.")
        href, script = values.get("href") or "", values.get("onclick") or ""
        if script.startswith("fn_egov_gosi_preview("):
            # 바로 보기 인자는 게시물 번호와 바로 앞 첨부의 내려받기 인자를 되풀이한다. 다르면 형식 변경으로 본다.
            match = _PREVIEW.fullmatch(script)
            if match is None:
                raise ValueError(f"{LABEL} 첨부 바로 보기 형식이 바뀌었습니다.")
            if match[1] != self.notice_id:
                raise ValueError(f"{LABEL} HTML의 번호가 요청과 일치하지 않습니다.")
            if not self.downloads or self.downloads[-1] != match.groups()[2:]:
                raise ValueError(f"{LABEL} 첨부 링크와 바로 보기 정보가 일치하지 않습니다.")
            return
        if not (href or script):
            return
        match = _DOWNLOAD.fullmatch(href) if names.count("href") == 1 and not script else None
        self.anchor = (len(self.tags), match.groups() if match else None, [])

    def handle_data(self, data):
        super().handle_data(data)
        if self.anchor is not None and not self.hidden_depth:
            self.anchor[2].append(data)

    def handle_endtag(self, tag):
        depth = len(self.tags)
        super().handle_endtag(tag)
        if tag != "a" or self.anchor is None or self.anchor[0] != depth:
            return
        _, arguments, parts = self.anchor
        self.anchor = None
        if len(self.attachments) == _MEDIA_LIMIT:
            raise ValueError(f"{LABEL}의 첨부 후보가 40개를 초과했습니다.")
        label = _text(parts) or None
        _, dot, extension = (label or "").rpartition(".")
        extension = extension.lower()
        format_name = extension if dot and extension in _ATTACHMENT_FORMATS else None
        self.downloads.append(arguments)
        self.attachments.append({"kind": "attachment", "source_url": _download_url(arguments) if arguments else None,
                                 "label": label, "format": "jpeg" if format_name == "jpg" else format_name})


def _info(parser: _GosiParser, section: str, label: str) -> str | None:
    if section not in parser.parts:
        raise ValueError(f"{LABEL} 상세에 {label} 항목이 없습니다.")
    match = re.fullmatch(rf"{label} :(?: (.+))?", _text(parser.parts[section]))
    if match is None:
        raise ValueError(f"{LABEL} 상세의 {label} 항목 형식이 바뀌었습니다.")
    return match[1]


def parse_gosi_detail(text: str, *, notice_id: str, listing: dict) -> dict:
    """상세의 표시 문구를 그대로 보관한다. 상세에는 번호가 첨부 바로 보기에만 있으므로 목록 항목과 머리 항목을 대조한다."""
    url = gosi_detail_url(notice_id)
    if not isinstance(text, str) or "\x00" in text:
        raise ValueError(f"{LABEL} HTML 형식이 올바르지 않습니다.")
    parser = _GosiParser(notice_id)
    parser.feed(text)
    parser.close()
    if parser.tags or not parser.found_board:
        raise ValueError(f"{LABEL} 본문 영역을 확인할 수 없습니다.")
    if parser.detail_actions != [_DETAIL_ACTION]:
        raise ValueError(f"{LABEL} HTML의 게시판이 요청과 일치하지 않습니다.")
    # 없는 번호 화면에도 빈 본문·첨부 영역이 있다. 영역이 아예 없으면 '본문·첨부 없음'이 아니라 형식 변경이다.
    if "description" not in parser.parts:
        raise ValueError(f"{LABEL} 본문 영역(view_cont)이 없습니다. 형식이 바뀌었습니다.")
    if not parser.file_section_seen:
        raise ValueError(f"{LABEL} 첨부 영역(view_file)이 없습니다. 형식이 바뀌었습니다.")
    title = _text(parser.parts.get("title", []))
    if not title:
        # 없는 번호도 HTTP 200과 빈 제목·항목의 같은 화면을 돌려준다.
        raise ValueError(f"{LABEL} 제목이 없습니다. 없는 게시물이거나 형식이 바뀌었습니다.")
    fields = {
        "notice_number": _info(parser, "notice_number", "고시공고번호"),
        "registered_date": _info(parser, "published_date", "등록일"),
        "department": _info(parser, "department", "담당부서"),
    }
    shown = {"notice_id": notice_id, "title": title, **fields}
    if not isinstance(listing, dict) or listing != shown:
        raise ValueError(f"{LABEL} 상세가 목록 항목과 일치하지 않습니다.")
    lines = [" ".join(line.split()) for line in "".join(parser.parts.get("description", [])).splitlines()]
    fields["description"] = "\n".join(line for line in lines if line) or None

    flags = set(parser.review_flags) | {f"missing:{key}" for key, value in fields.items() if value is None}
    registered = None
    match = re.fullmatch(r"([0-9]{4})\.([0-9]{2})\.([0-9]{2})", fields["registered_date"] or "")
    try:
        registered = date(*map(int, match.groups())).isoformat() if match else None
    except ValueError:
        pass
    if registered is None and fields["registered_date"] is not None:
        flags.add("registered_date_unparsed")
    # 정정·변경 관계는 본문·제목에 적힌 고시공고번호 문자열만 남기고, 제목의 `(정정)`만으로 원공고를 추정하지 않는다.
    # 자기 번호 제외와 중복 제거는 같은 비교 키로, 발행 주체까지 같은 전체 번호일 때만 한다. 키만 정규화하고 값은 원문이다.
    references, seen = [], {_notice_key(fields["notice_number"] or "")}
    for found in _NOTICE_NUMBER.finditer(f"{title}\n{fields['description'] or ''}"):
        if (key := _notice_key(found[0])) not in seen:
            seen.add(key)
            references.append(found[0])
    return {
        "source": "city_gosi_notice",
        "external_id": notice_id,
        "official_url": url,
        "title": title,
        "fields": fields,
        "registered_on": registered,
        "attachments": parser.attachments,
        "referenced_notice_numbers": references,
        "review_flags": sorted(flags),
    }
