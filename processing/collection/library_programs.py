"""안성시 도서관 행사신청 목록과 상세의 공개 항목을 표시 문구 그대로 읽는다."""

import re
from urllib.parse import urlencode

from .html_tokens import PinnedHTMLParser
from .official_web import OFFICIAL_ORIGIN, _fetch


PARSER_VERSION = "library-program-parser-v2"
SOURCE_LABEL = "도서관 행사신청"
PROGRAM_ID = re.compile(r"[1-9][0-9]{0,17}")
_MENU = "0202020000"
LIST_ACTION = f"/library/activity/program/list.do?mId={_MENU}"
_IGNORED_TAGS = {"script", "style", "template", "noscript"}
_VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
# br·p·li·div 경계를 표시한다. NUL이 있는 입력은 거부하므로 원문 글자와 섞이지 않는다.
_BREAK = "\x00"
_BREAK_TAGS = {"br", "p", "li", "div"}
_TEXT_TAGS = {"a", "b", "br", "em", "font", "i", "img", "p", "small", "span", "strong", "sub", "sup", "u"}
# 목록 칸은 실제 표본(2026-11-28, 155행)에 나온 태그만 받는다. 그림 상태 표시 등은 형식 변경으로 본다.
_LISTING_TAGS = {"a", "br", "span", "strong"}
_ATTACHMENT_TAGS = {"a", "div", "li", "script", "span", "ul"}
# 화면 표시를 확정할 수 없는 속성. 실제 표본에는 없었으므로 나오면 형식 변경으로 본다.
_HIDING_ATTRS = {"style", "hidden"}
_HEADERS = ["도서관", "행사구분", "행사명", "행사기간", "행사대상", "접수자/정원(대기정원)", "접수현황"]
_LISTING_KEYS = ("library", "program_type", "title", "activity_period", "target", "enrollment", "application_status")
_DETAIL_LINK = re.compile(r"/library/activity/program/view\.do\?mId=0202020000&idx=([1-9][0-9]{0,17})")
_GO_PAGE = re.compile(r"module\.goPage\(([1-9][0-9]{0,17})\); return false;")
_DOWNLOAD = re.compile(r"fn_egov_downFile\('[0-9a-f]{1,128}','[0-9a-f]{1,128}'\); return false;")
_SCRIPT_SRC = re.compile(r"/(?:dwr/(?:interface/EgovFileMngDwr|engine|util)|common/js/common/EgovFileUtils)\.js")
_DETAIL_CAPTION = "문화강좌 신청확인"
_NO_ATTACHMENT = "자료없음"
# 신청 기간(접수기간)과 진행 일정(행사기간·요일·시간)은 키를 나누어 섞지 않는다.
_DETAIL_FIELDS = {
    "구분": "library",
    "행사구분": "program_type",
    "행사명": "title",
    "접수기간": "application_period",
    "행사기간": "activity_period",
    "행사요일": "activity_weekday",
    "행사시간": "activity_time",
    "진행자": "instructor",
    "행사대상": "target",
    "장소": "place",
    "온라인접수": "online_enrollment",
    "재료비": "material_cost",
    "준비물": "supplies",
    "접수방법": "application_method",
    "행사내용": "description",
    "유의사항": "notes",
    "문의전화": "contact_phone",
}
_OPTIONAL = {"진행자", "재료비", "준비물", "유의사항"}
_INVALID_LISTING = "도서관 행사신청 목록 HTML 구조가 올바르지 않습니다."
_INVALID_DETAIL = "도서관 행사신청 상세 HTML 구조가 올바르지 않습니다."
_MARKUP_ERROR = "도서관 행사신청 HTML에 브라우저와 해석이 갈리는 태그·주석·스크립트 표기가 있습니다."


def program_listing_path(page: int) -> str:
    if type(page) is not int or page < 1:
        raise ValueError("목록 페이지는 양의 정수여야 합니다.")
    return LIST_ACTION + "&" + urlencode({"currentPageNo": page})


def _detail_path(program_id: str) -> str:
    if not isinstance(program_id, str) or PROGRAM_ID.fullmatch(program_id) is None:
        raise ValueError("도서관 행사 번호는 18자리 이하의 양의 ASCII 정수여야 합니다.")
    return "/library/activity/program/view.do?" + urlencode({"idx": program_id, "mId": _MENU})


def program_listing_url(page: int) -> str:
    return OFFICIAL_ORIGIN + program_listing_path(page)


def program_detail_url(program_id: str) -> str:
    return OFFICIAL_ORIGIN + _detail_path(program_id)


def fetch_program_listing(page: int, *, limit: int) -> bytes:
    return _fetch("GET", program_listing_path(page), None, limit, source=SOURCE_LABEL)


def fetch_program_detail(program_id: str, *, limit: int) -> bytes:
    return _fetch("GET", _detail_path(program_id), None, limit, source=SOURCE_LABEL)


def _clean(parts: list[str]) -> str:
    """줄 안의 공백만 하나로 줄이고 br·문단 경계는 줄바꿈으로 남긴다."""
    lines = "".join(parts).split(_BREAK)
    return "\n".join(" ".join(line.split()) for line in lines).strip("\n")


class _PageParser(PinnedHTMLParser):
    """class가 `table_class`인 표 하나의 칸과 목록 폼·페이지 이동·신청 버튼만 모은다.

    주석·원문 텍스트·종료 태그 경계와 빈 요소가 아닌 태그의 `/>` 처리는 공용 기반의 브라우저 규칙을 따른다.
    """

    def __init__(self, table_class: str, error: str):
        super().__init__()
        self.table_class, self.error = table_class, error
        self.ignored = 0
        self.in_form = False
        self.form_actions: list[str | None] = []
        self.page_inputs: list[str | None] = []
        self.buttons: list[dict] = []
        self.tables = 0
        self.stack: list[str] | None = None
        self.caption: list[str] | None = None
        self.captions: list[str] = []
        self.row: list[dict] | None = None
        self.section = ""
        self.rows: list[tuple[str, list[dict]]] = []
        self.cell: dict | None = None
        self.box = 0
        self.on_text: list[str] | None = None
        self.current_pages: list[str] = []
        self.end_pages: list[str | None] = []

    def fail(self):
        raise ValueError(self.error)

    def markup_error(self):
        return ValueError(_MARKUP_ERROR)

    def handle_starttag(self, tag, attrs):
        super().handle_starttag(tag, attrs)
        values = dict(attrs)
        # 같은 속성이 반복되면 브라우저(첫 값)와 dict(마지막 값)의 해석이 갈린다. 칸 안 script src도 같다.
        repeated = len(values) != len(attrs)
        if tag in _IGNORED_TAGS:
            if self.cell is not None:
                if repeated:
                    self.fail()
                self.cell["tags"].append((tag, values))
            elif self.stack is not None and not self.ignored:
                self.fail()
            self.ignored += 1
            return
        if self.ignored:
            return
        if repeated:
            self.fail()
        classes = (values.get("class") or "").split()
        if tag == "form" and values.get("id") == "listForm":
            self.form_actions.append(values.get("action"))
            self.in_form = True
        elif tag == "input" and self.in_form and values.get("id") == "currentPageNo":
            self.page_inputs.append(values.get("value"))
        elif tag == "a" and values.get("data-button") == "write":
            self.buttons.append(values)
        if self.box:
            self.box += tag == "div"
            if tag == "a" and "on" in classes:
                self.on_text = []
            elif tag == "a" and "btn_end" in classes:
                self.end_pages.append(values.get("onclick"))
        elif tag == "div" and "box_page" in classes and self.stack is None:
            # 표 안의 box_page는 칸 태그로 검사해야 하므로 페이지 이동 영역으로 보지 않는다.
            self.box = 1
        elif self.stack is not None:
            self._table_start(tag, values)
        elif tag == "table" and self.table_class in classes:
            if _HIDING_ATTRS & values.keys():
                self.fail()
            self.tables += 1
            self.stack = ["table"]

    def _table_start(self, tag, values):
        if self.cell is not None:
            if tag in ("table", "caption", "thead", "tbody", "tr", "th", "td"):
                self.fail()
            self.cell["tags"].append((tag, values))
            if tag in _BREAK_TAGS:
                self.cell["text"].append(_BREAK)
        elif _HIDING_ATTRS & values.keys():
            # 칸 안쪽 태그뿐 아니라 표 구조 태그 자신의 숨김 속성도 형식 변경으로 본다.
            self.fail()
        elif tag == "caption" and self.stack == ["table"]:
            self.caption = []
        elif tag in ("colgroup", "thead", "tbody") and self.stack == ["table"]:
            self.section = tag
        elif tag == "tr" and self.stack[-1] in ("thead", "tbody") and self.row is None:
            self.row = []
        elif tag in ("th", "td") and self.stack[-1] == "tr":
            self.cell = {"tag": tag, "text": [], "tags": []}
        elif not (tag == "col" and self.stack[-1] == "colgroup"):
            self.fail()
        if tag not in _VOID_TAGS:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if self.ignored:
            self.ignored -= tag in _IGNORED_TAGS
            return
        if tag == "form":
            self.in_form = False
        if self.box:
            if tag == "a" and self.on_text is not None:
                self.current_pages.append(" ".join("".join(self.on_text).split()))
                self.on_text = None
            self.box -= tag == "div"
            return
        if self.stack is None:
            return
        if tag in _VOID_TAGS:
            if tag == "br" and self.cell is not None:
                self.cell["text"].append(_BREAK)
            return
        if self.stack[-1] != tag:
            self.fail()
        self.stack.pop()
        if self.cell is not None and tag in _BREAK_TAGS:
            self.cell["text"].append(_BREAK)
        if tag in ("th", "td"):
            self.row.append({**self.cell, "text": _clean(self.cell["text"])})
            self.cell = None
        elif tag == "tr":
            if len(self.rows) == 101:
                self.fail()
            self.rows.append((self.section, self.row))
            self.row = None
        elif tag == "caption":
            self.captions.append(_clean(self.caption))
            self.caption = None
        elif tag == "table":
            self.stack = None

    def handle_data(self, data):
        super().handle_data(data)
        if self.ignored:
            return
        if self.cell is not None:
            self.cell["text"].append(data)
        elif self.caption is not None:
            self.caption.append(data)
        elif self.on_text is not None:
            self.on_text.append(data)
        elif self.stack is not None and data.strip():
            self.fail()

    def finish(self, text: str):
        if not isinstance(text, str) or "\x00" in text:
            self.fail()
        try:
            self.feed(text)
            self.close()
        except AssertionError:
            self.fail()
        if self.ignored or self.stack is not None or self.box or self.tables != 1 or self.form_actions != [LIST_ACTION]:
            self.fail()


def _check_tags(cell: dict, allowed: set[str], error: str) -> None:
    for tag, values in cell["tags"]:
        if tag not in allowed or _HIDING_ATTRS & values.keys():
            raise ValueError(error)


def parse_program_listing(raw: bytes, *, page: int) -> tuple[int, list[tuple[str, dict]]]:
    """요청 페이지와 대조한 전체 페이지 수와 원래 순서의 (행사 번호, 목록 칸 원문)을 반환한다."""
    if type(page) is not int or page < 1 or not isinstance(raw, bytes):
        raise ValueError(_INVALID_LISTING)
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ValueError(_INVALID_LISTING) from None
    parser = _PageParser("bod_list", _INVALID_LISTING)
    parser.finish(text)
    if len(parser.page_inputs) != 1 or len(parser.current_pages) != 1 or len(parser.end_pages) != 1:
        raise ValueError(_INVALID_LISTING)
    end = _GO_PAGE.fullmatch(parser.end_pages[0] or "")
    if end is None:
        raise ValueError(_INVALID_LISTING)
    total = int(end[1])
    if parser.page_inputs != [str(page)] or parser.current_pages != [str(page)] or page > total:
        raise ValueError("도서관 행사신청 목록의 페이지 번호가 요청과 일치하지 않습니다.")

    head = [cells for section, cells in parser.rows if section == "thead"]
    body = [cells for section, cells in parser.rows if section == "tbody"]
    if (len(head) != 1 or [cell["text"] for cell in head[0]] != _HEADERS
            or any(cell["tag"] != "th" for cell in head[0]) or not body):
        raise ValueError(_INVALID_LISTING)
    rows = []
    for cells in body:
        if len(cells) != len(_HEADERS) or any(cell["tag"] != "td" for cell in cells):
            raise ValueError(_INVALID_LISTING)
        for cell in cells:
            _check_tags(cell, _LISTING_TAGS, _INVALID_LISTING)
        links = [[values.get("href") for tag, values in cell["tags"] if tag == "a"] for cell in cells]
        match = _DETAIL_LINK.fullmatch(links[2][0] or "") if len(links[2]) == 1 else None
        if match is None or sum(map(len, links)) != 1:
            raise ValueError(_INVALID_LISTING)
        # 상태 칸 신청 버튼의 번호가 링크와 다르면 다른 행사의 상태가 붙을 수 있다.
        if any(values.get("data-idx", match[1]) != match[1] for cell in cells for _, values in cell["tags"]):
            raise ValueError("도서관 행사신청 목록 행의 행사 번호가 서로 다릅니다.")
        # 행사명과 접수현황(목록에만 있는 신청 상태)이 비면 형식 변경으로 본다.
        if not cells[2]["text"] or not cells[6]["text"]:
            raise ValueError("도서관 행사신청 목록 행의 행사명 또는 접수현황이 비었습니다.")
        if match[1] in (program_id for program_id, _ in rows):
            raise ValueError("도서관 행사신청 목록에 같은 행사 번호가 있습니다.")
        rows.append((match[1], {key: cell["text"] or None for key, cell in zip(_LISTING_KEYS, cells)}))
    return total, rows


def _attachments(cell: dict) -> list[str] | None:
    """첨부 칸의 파일 이름·크기 표시를 줄 단위 원문으로 돌려준다. 첨부 본문은 받지 않는다.

    `자료없음` 문구도 파일 목록도 없이 첨부 스크립트만 있는 칸은 첨부 유무를 확정할 수 없어 None이다.
    """
    anchors = 0
    for tag, values in cell["tags"]:
        if tag not in _ATTACHMENT_TAGS or _HIDING_ATTRS & values.keys():
            raise ValueError(_INVALID_DETAIL)
        if tag == "script" and _SCRIPT_SRC.fullmatch(values.get("src") or "") is None:
            raise ValueError(_INVALID_DETAIL)
        if tag == "a":
            if _DOWNLOAD.fullmatch(values.get("onclick") or "") is None:
                raise ValueError(_INVALID_DETAIL)
            anchors += 1
    lines = [line for line in cell["text"].split("\n") if line]
    if anchors == 0 and lines in ([], [_NO_ATTACHMENT]):
        return [] if lines else None
    if anchors == 0 or len(lines) != anchors:
        raise ValueError(_INVALID_DETAIL)
    return lines


def parse_program_detail(text: str, program_id: str) -> dict:
    """상세 표의 항목을 표시 문구 그대로 보관한다. 신청 상태·비용·자격은 해석하지 않는다."""
    url = program_detail_url(program_id)
    parser = _PageParser("tbl", _INVALID_DETAIL)
    parser.finish(text)
    if parser.captions != [_DETAIL_CAPTION] or len(parser.buttons) != 1:
        raise ValueError(_INVALID_DETAIL)
    if parser.buttons[0].get("data-idx") != program_id:
        raise ValueError("도서관 행사신청 상세의 행사 번호가 요청과 일치하지 않습니다.")
    # 실제 표본의 신청 버튼은 모두 상태 코드가 있었다. 없거나 비면 형식 변경으로 본다.
    if not parser.buttons[0].get("data-state"):
        raise ValueError(_INVALID_DETAIL)

    fields = dict.fromkeys(_DETAIL_FIELDS.values())
    seen, flags, attachments = set(), [], None
    required = _DETAIL_FIELDS.keys() - _OPTIONAL | {"첨부파일"}
    for section, cells in parser.rows:
        if section != "tbody" or not cells or len(cells) % 2:
            raise ValueError(_INVALID_DETAIL)
        for label_cell, cell in zip(cells[::2], cells[1::2]):
            label = label_cell["text"]
            if label_cell["tag"] != "th" or label_cell["tags"] or cell["tag"] != "td":
                raise ValueError(_INVALID_DETAIL)
            if label in seen:
                raise ValueError("도서관 행사신청 상세의 항목이 중복되었습니다.")
            seen.add(label)
            if label == "첨부파일":
                attachments = _attachments(cell)
                continue
            key = _DETAIL_FIELDS.get(label)
            if key is None:
                raise ValueError(f"도서관 행사신청 상세에 알 수 없는 항목이 있습니다: {label[:40]}")
            _check_tags(cell, _TEXT_TAGS, _INVALID_DETAIL)
            if any(tag == "img" for tag, _ in cell["tags"]):
                flags.append(f"image:{key}")
            fields[key] = cell["text"] or None
    if not required <= seen:
        raise ValueError("도서관 행사신청 상세에 빠진 항목이 있습니다.")
    if fields["title"] is None:
        raise ValueError("도서관 행사신청 상세의 행사명이 없습니다.")
    # 재료비 등이 없거나 비면 무료로 보지 않고 null과 사유만 남긴다.
    unknown = {key: "missing" if label not in seen else "empty"
               for label, key in _DETAIL_FIELDS.items() if fields[key] is None}
    if attachments is None:
        unknown["attachments"] = "empty"
    if attachments:
        flags.append("attachment")
    return {
        "external_id": program_id,
        "official_url": url,
        "fields": fields,
        "attachments": attachments,
        "apply_button_state": parser.buttons[0].get("data-state"),
        # 통합예약과 같은 행사인지 판단하지 않는다. 신청 버튼이 통합예약 신청 양식에 넘기는 번호만 남긴다.
        "cross_reference_candidate": {"integrated_reservation_program_idx": program_id},
        "unknown": unknown,
        "review_flags": sorted(flags),
    }


def program_record(page: int, listing: dict, detail: dict) -> dict:
    """목록 행(접수현황 원문 포함)과 상세 항목을 합치지 않고 나란히 둔다. 빈 목록 칸은 사유를 남긴다."""
    unknown = {**detail["unknown"], **{f"listing.{key}": "empty" for key, value in listing.items() if value is None}}
    return {**detail, "unknown": unknown, "list_page": page, "listing": listing}
