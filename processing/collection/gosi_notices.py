"""안성시 고시·공고 게시판(새올 고시공고)의 공개 목록과 상세를 요청하고 표시 문구를 읽는다."""

from datetime import date
import re
from urllib.parse import quote, urlencode

from .html_tokens import PinnedHTMLParser
from .libraries import _ATTACHMENT_FORMATS, _HIDDEN_ERROR, _HIDDEN_TAGS, _VOID_TAGS, _NoticeParser
from .official_web import OFFICIAL_ORIGIN, _fetch

LABEL = "고시·공고"
PARSER_VERSION = "gosi-notice-parser-v3"
_MENU = "0501040000"
# 고시/공고 구분. 같은 화면의 입법예고·입찰공고는 다른 값을 쓴다.
_SE_CODE = "01"
_DETAIL_ACTION = f"/portal/saeol/gosiView.do?mId={_MENU}"
_NOTICE_ID = re.compile(r"[1-9][0-9]{0,17}")
_IGNORED_TAGS = {"script", "style", "template", "noscript"}
# 읽는 영역의 구조는 2026-11-28 실제 원본(목록 6쪽: 1·2·658쪽, 검색 2쪽, 수집 1쪽. 상세 27쪽: 서로 다른 18쪽,
# 곧 게시물 17건·없는 번호 1건)에 나온 그대로만 받는다. 한 칸 들여쓰기가 중첩이고, 요소는 `태그.class[그 밖 속성 이름]`,
# 뒤의 글자는 `*`(읽는 칸)·표본의 고정 문구·빈칸(공백만) 가운데 하나다. 자리·class 값·속성 이름이 다르거나 인라인 스타일이
# 있으면(표본에 없었다) 거부한다. 표본 구조에는 브라우저가 시작 태그에서 요소를 암묵적으로 닫는 자리도 없다.
_LISTING_SHAPE = """
div.board_page *
 span.red
  strong *
table.tableSt_list.row_over
 caption *
 thead
  tr
   th.wp20.gosi_num[scope] 고시공고번호
   th.gosi_tit[scope] 제목
   th.wp10.gosi_dept[scope] 담당부서
   th.wp15.gosi_date[scope] 등록일
 tbody
  tr
   td.gosi_num *
    br
   td.taL.gosi_tit
    a[href,onclick] *
   td.gosi_dept *
   td.gosi_date *
"""
_BODY_SHAPE = """
div.bod_view
 h4 *
 div.view_info.gosi_b
  ul
   li.view_write *
    span *
   li.view_date *
    span *
   li.view_hit *
    span *
 div.view_cont *
  br
 dl.view_file
  dt
   span 첨부 파일
  dd
   p
    a[href] *
    a.bt_white_s[href,onclick,target,title]
     span.blank 바로 보기
 div.open_license.clFix.mB20
  a[href,rel,target,title]
   img[alt,src]
  p 본 공공저작물은 공공누리 제4유형: "출처표시" + 상업적 이용 및 변경 금지 조건에 따라 이용할 수 있습니다.
"""
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
# 페이지 스크립트는 encodeURI로 인자를 붙인다. 브라우저는 그 전에 javascript: 주소의 탭·줄바꿈을 지우고 퍼센트 디코딩을
# 하며 JS 이스케이프도 푼다. 그래서 인자는 실제 원본 36벌(108개)에 쓰인 한글 음절·ASCII 영숫자·공백·`()./[]_~「」`만 받는다.
_URI_SAFE = ";,/?:@&=+$!*'()#"
_ARGUMENT = re.compile(r"[가-힣A-Za-z0-9 ()./\[\]_~「」]+")
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


def _shape(spec: str) -> dict:
    shape, path = {}, ()
    for line in spec.strip("\n").splitlines():
        token, _, text = line.lstrip(" ").partition(" ")
        element, _, names = token.rstrip("]").partition("[")
        tag, *classes = element.split(".")
        node = (tag, " ".join(classes) or None, tuple(names.split(",")) if names else ())
        path = path[:len(line) - len(line.lstrip(" "))] + (node,)
        shape[path] = text or None
    return shape


_LISTING_SHAPE, _BODY_SHAPE = _shape(_LISTING_SHAPE), _shape(_BODY_SHAPE)


def _step(shape: dict, parent: tuple, tag: str, attrs: list) -> tuple | None:
    """표본 구조에 있는 자리·class 값·속성 이름이면 새 경로를, 아니면(중복 속성 포함) None을 반환한다."""
    names = [name for name, _ in attrs]
    path = parent + ((tag, dict(attrs).get("class"), tuple(sorted(set(names) - {"class"}))),)
    return path if path in shape and len(set(names)) == len(names) else None


def _said(rule: str | None, data: str) -> bool:
    # 읽지 않는 자리의 글자는 화면에 보여도 버려지므로 표본의 고정 문구만 받는다.
    return not data.strip("\t\n\f\r ") or rule == "*" or rule == " ".join(data.split())


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
    """요청 주소를 되돌려 주는 유일한 `form#listForm` 안의 쪽 표시와 목록 표만 읽는다."""

    def __init__(self, page: int):
        super().__init__()
        self.action = gosi_listing_path(page)
        self.link = re.compile(rf"javascript:boardView\('{page}', '([1-9][0-9]{{0,17}})'\);return false;")
        self.ignored: list[str] = []
        self.in_form = self.form_seen = self.table_seen = False
        self.paths: list[tuple] = []
        self.parts: list[str] | None = None
        self.totals: list[str] = []
        self.captions: list[str] = []
        self.row: dict | None = None
        self.rows: list[dict] = []

    def fail(self):
        raise ValueError(_INVALID_LISTING)

    def markup_error(self):
        return ValueError(f"{LABEL} 목록 HTML에 브라우저와 해석이 갈리는 태그·주석·스크립트 표기가 있습니다.")

    def handle_starttag(self, tag, attrs):
        super().handle_starttag(tag, attrs)
        values = dict(attrs)
        classes = (values.get("class") or "").split()
        if not self.paths:
            if tag in _IGNORED_TAGS:
                self.ignored.append(tag)
            if self.ignored:
                return
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
            if not self.in_form or {"div": "board_page", "table": "tableSt_list"}.get(tag) not in classes:
                return
        # 읽는 영역은 표본 구조만 받고, 종료 태그는 가장 안쪽에 열린 요소를 닫아야 한다.
        path = _step(_LISTING_SHAPE, self.paths[-1] if self.paths else (), tag, attrs)
        if path is None or (tag == "table" and self.table_seen):
            self.fail()
        if tag not in _VOID_TAGS:
            self.paths.append(path)
        if tag in ("div", "caption", "td"):
            self.parts = []
        if tag == "table":
            self.table_seen = True
        elif tag == "tr" and path[-2][0] == "tbody":
            self.row = {"cells": [], "texts": [], "ids": []}
        elif tag == "td":
            self.row["cells"].append(classes[-1])
        elif tag == "a":
            match = self.link.fullmatch(values["onclick"] or "")
            if match is None:
                self.fail()
            self.row["ids"].append(match[1])
        elif tag == "br":
            self.parts.append(" ")

    def handle_data(self, data):
        super().handle_data(data)
        if self.paths:
            if not _said(_LISTING_SHAPE[self.paths[-1]], data):
                self.fail()
            if self.parts is not None:
                self.parts.append(data)

    def handle_endtag(self, tag):
        if self.paths:
            if self.paths.pop()[-1][0] != tag:
                self.fail()
            if tag == "div":
                self.totals.append(_text(self.parts))
            elif tag == "caption":
                self.captions.append(_text(self.parts))
            elif tag == "td":
                self.row["texts"].append(_text(self.parts) or None)
            elif tag == "tr" and self.row is not None:
                if len(self.rows) == 100:
                    self.fail()
                self.rows.append(self.row)
                self.row = None
            if tag in ("div", "caption", "td"):
                self.parts = None
        elif self.ignored:
            # 무시하는 요소 안의 짝 없는 종료 태그(template 안 `</style>` 등)는 브라우저가 무시하므로 깊이를 셀 수 없어 거부한다.
            if tag in _IGNORED_TAGS and tag != self.ignored.pop():
                self.fail()
        elif tag == "form":
            self.in_form = False

    def finish(self, raw: bytes):
        if not isinstance(raw, bytes) or b"\x00" in raw:
            self.fail()
        try:
            self.feed(raw.decode("utf-8-sig"))
            self.close()
        except (UnicodeDecodeError, AssertionError):
            self.fail()
        if self.in_form or not self.form_seen or self.ignored or self.paths or not self.table_seen:
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
    if not all(_ARGUMENT.fullmatch(value) for value in arguments):
        return None
    user, system, path = (quote(value, safe=_URI_SAFE) for value in arguments)
    return f"{_DOWNLOAD_URL}?user_file_nm={user}&sys_file_nm={system}&file_path={path}"


class _GosiParser(_NoticeParser):
    """공지 게시판 본문 규칙에 표본 구조·엄격한 중첩, 고시·공고 머리 항목과 첨부 스크립트 해석을 더한다."""

    def __init__(self, notice_id: str):
        super().__init__(label=LABEL)
        self.notice_id = notice_id
        self.detail_actions: list[str | None] = []
        self.attachments: list[dict] = []
        self.downloads: list[tuple[str, str, str] | None] = []
        self.anchor = None
        self.file_section_seen = False
        self.paths: list[tuple] = []
        self.hidden: list[str] = []

    def handle_starttag(self, tag, attrs):
        if not self.tags and tag in _HIDDEN_TAGS:
            self.hidden.append(tag)
        # 상위 파서가 태그를 넣은 뒤의 상태로 판단한다. 최상위 form은 쌓이지 않는다.
        super().handle_starttag(tag, attrs)
        if self.paths or self.tags:
            # 본문 영역은 상위 파서의 허용 목록보다 좁은 표본 구조만 받는다.
            path = _step(_BODY_SHAPE, self.paths[-1] if self.paths else (), tag, attrs)
            if path is None:
                raise ValueError(_HIDDEN_ERROR.format(LABEL))
            if len(self.tags) > len(self.paths):
                self.paths.append(path)
        names = [name for name, _ in attrs]
        values = dict(attrs)
        if not self.tags and not self.hidden_depth and tag == "form" and values.get("id") == "detailForm":
            if names.count("id") != 1 or names.count("action") != 1:
                raise ValueError(f"{LABEL} 상세 폼의 HTML 속성이 중복되었습니다.")
            self.detail_actions.append(values["action"])
        if self.hidden_depth or not self.tags:
            return
        if tag == "dl":
            # 첨부가 없는 글도 템플릿은 빈 `dl.view_file`을 출력한다(없는 번호 화면에서 확인). 영역의 유무로 형식 변경을 가린다.
            if self.file_section_seen:
                raise ValueError(f"{LABEL} 첨부 영역이 중복되었습니다.")
            self.file_section_seen = True
        if tag == "li" and self.section is None:
            for name, section in (("view_write", "notice_number"), ("view_hit", "department")):
                if values["class"] == name:
                    if section in self.parts:
                        raise ValueError(f"{LABEL} 필드가 중복되었습니다.")
                    self.section, self.section_depth, self.parts[section] = section, len(self.tags), []
        if tag == "a" and self.attachment_open:
            self._attachment_link(values)

    def _attachment_link(self, values):
        self.review_flags.add("attachment")
        if "class" not in values:
            self.anchor = (_DOWNLOAD.fullmatch(values["href"] or ""), [])
            return
        # 바로 보기 인자는 게시물 번호와 바로 앞 첨부의 내려받기 인자를 되풀이한다. 다르면 형식 변경으로 본다.
        match = _PREVIEW.fullmatch(values["onclick"] or "")
        if match is None:
            raise ValueError(f"{LABEL} 첨부 바로 보기 형식이 바뀌었습니다.")
        if match[1] != self.notice_id:
            raise ValueError(f"{LABEL} HTML의 번호가 요청과 일치하지 않습니다.")
        if not self.downloads or self.downloads[-1] != match.groups()[2:]:
            raise ValueError(f"{LABEL} 첨부 링크와 바로 보기 정보가 일치하지 않습니다.")

    def handle_data(self, data):
        super().handle_data(data)
        if self.paths and not _said(_BODY_SHAPE[self.paths[-1]], data):
            raise ValueError(f"{LABEL} HTML 구조가 올바르지 않습니다.")
        if self.anchor is not None:
            self.anchor[1].append(data)

    def handle_endtag(self, tag):
        if not self.tags and self.hidden_depth and tag in _HIDDEN_TAGS and tag != self.hidden.pop():
            # 숨김 요소 안의 짝 없는 종료 태그(template 안 `</script>` 등)를 브라우저는 무시하는데 상위 파서는 깊이를 줄인다.
            raise ValueError(f"{LABEL} 본문 영역을 확인할 수 없습니다.")
        if self.tags and self.tags[-1] != tag:
            # 본문 영역의 종료 태그는 가장 안쪽에 열린 요소만 닫아야 한다(빈 요소의 종료 태그 포함).
            raise ValueError(f"{LABEL} HTML 구조가 올바르지 않습니다.")
        super().handle_endtag(tag)
        del self.paths[len(self.tags):]
        if tag != "a" or self.anchor is None:
            return
        match, parts = self.anchor
        self.anchor = None
        if len(self.attachments) == _MEDIA_LIMIT:
            raise ValueError(f"{LABEL}의 첨부 후보가 40개를 초과했습니다.")
        label = _text(parts) or None
        _, dot, extension = (label or "").rpartition(".")
        extension = extension.lower()
        format_name = extension if dot and extension in _ATTACHMENT_FORMATS else None
        self.downloads.append(match.groups() if match else None)
        self.attachments.append({"kind": "attachment", "source_url": _download_url(match.groups()) if match else None,
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
