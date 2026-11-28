"""안성배움e 전체 강좌 목록과 상세(`eduLctreNo`)의 공개 항목을 요청하고 표시 문구 그대로 읽는다.

안성배움e 공지 게시판(`BOARDS["edu"]`)과 다른 강좌 신청 화면이다.
"""

import re

from .libraries import _DOWNLOAD, _VOID_TAGS, _NoticeParser, _declared_context_paths
from .official_web import OFFICIAL_ORIGIN, _fetch


CONTEXT_PATH = "/edu"
MENU = "1400000000"
_LIST_PATH = f"{CONTEXT_PATH}/portal/edu/eduLctre/selectEduLctreWebList.do"
_VIEW_PATH = f"{CONTEXT_PATH}/portal/edu/eduLctre/eduLctreView.do"
_LABEL = "안성배움e 강좌"
_COURSE_ID = re.compile(r"[1-9][0-9]{0,17}")
_INVALID_LISTING = f"{_LABEL} 목록 HTML 구조가 올바르지 않습니다."
_INVALID_DETAIL = f"{_LABEL} 상세 HTML 구조가 올바르지 않습니다."
_PAGE_LABEL = re.compile(r"전체 [0-9]{1,18} ?건 ?\[ ?([1-9][0-9]{0,17}) ?/ ?([1-9][0-9]{0,17}) ?페이지 ?\]")
# 페이지 머리의 QR 주소는 요청 주소를 되돌려 준다. 상세 HTML에 강좌 번호를 담은 다른 값은 없다.
_ECHO = re.compile(r'qrcode\("' + re.escape(OFFICIAL_ORIGIN + _VIEW_PATH)
                   + r'\?eduLctreNo=([1-9][0-9]{0,17})&mId=' + MENU + r'"\)')
_IMAGE = re.compile(re.escape(CONTEXT_PATH) + r"/common/imgView\.do\?attachId=[0-9a-f]{64}&fileSn=[0-9a-f]{32}"
                    r"&mode=ratioView")
_MAX_ROWS = 100
# 공유 태그 경계 규칙(_NoticeParser)이나 아래 출력·허용 규칙이 바뀌면 올린다.
PARSER_VERSION = "edu-course-parser-v3"
_TEXT_FIELDS = {
    "접수기간": "application_period",
    "접수현황": "enrollment_status",
    "선발방법": "selection_method",
    "교육기간": "course_period",
    "교육시간": "course_schedule",
    "교육장": "venue",
    "강사명": "instructor",
    "수강료": "fee",
    "문의전화": "contact_phone",
    "강좌소개": "description",
    "유의사항": "notes",
}
_MEDIA_FIELDS = {"교육장 사진": "venue_photos", "강의계획서 및 이미지": "course_materials"}
_TEXT_TAGS = {"br", "span", "em", "a"}
# 제목 줄의 span class. bod_btn은 로그인 안내·신청 단추라 읽지 않는다.
_TITLE_PARTS = {"bod_state_type": "state", "bod_subject": "subject", "bod_btn": None}
# 2026-11-28 실제 상세 28쪽의 제목 줄·항목 칸에 있던 속성·class만 받는다. hidden 같은 숨김 속성·다른 인라인 스타일과
# 이 사이트의 화면 숨김 class(blind 등)는 거부한다. skip은 첨부 링크의 `파일 다운로드` 안내에서만 받고 읽지 않는다.
_ATTRS = frozenset("alt class href id onclick src target title type".split())
_STYLES = {"vertical-align:middle"}
_CLASSES = frozenset("bod_title bod_write bod_state_type bod_subject bod_btn em_b_black mL5 mR5 mL20 mR10 updateFileList"
                     " file_slide file_slide_list file_slide_item file_slide_anchor file_slide_control file_slide_prev"
                     " file_slide_next".split())


def _course_id(value: object) -> str:
    if not isinstance(value, str) or _COURSE_ID.fullmatch(value) is None:
        raise ValueError("강좌 번호는 18자리 이하의 양의 ASCII 정수여야 합니다.")
    return value


def listing_path(page: int) -> str:
    if type(page) is not int or page < 1:
        raise ValueError("목록 페이지는 양의 정수여야 합니다.")
    return f"{_LIST_PATH}?mId={MENU}&page={page}"


def _detail_path(course: str) -> str:
    return f"{_VIEW_PATH}?eduLctreNo={_course_id(course)}&mId={MENU}"


def detail_url(course: str) -> str:
    return OFFICIAL_ORIGIN + _detail_path(course)


def fetch_listing(page: int, *, limit: int) -> bytes:
    return _fetch("GET", listing_path(page), None, limit, source=_LABEL)


def fetch_detail(course: str, *, limit: int) -> bytes:
    return _fetch("GET", _detail_path(course), None, limit, source=_LABEL)


class _Page(_NoticeParser):
    """공유 태그 경계 규칙으로 문서를 읽고 `select`가 고른 요소의 하위 트리를 (태그, 속성, 자식)으로 모은다.

    강좌 화면에는 게시판 본문(div.bod_view)이 없으므로 _NoticeParser는 태그 경계 검사와 최상위 script 수집만 한다.
    script·style·template 안쪽은 화면에 나오지 않아 모으지 않는다. 브라우저는 중복 속성의 첫 값을 쓰므로 받지 않는다.
    """

    def __init__(self, select, error: str):
        super().__init__(label=_LABEL)
        self.select = select
        self.error = error
        self.trees: list[tuple] = []
        self.open: list[tuple] = []

    def handle_starttag(self, tag, attrs):
        hidden = self.hidden_depth
        super().handle_starttag(tag, attrs)
        values = dict(attrs)
        if not hidden and len(values) != len(attrs):
            raise ValueError(self.error)
        if hidden or not (self.open or self.select(tag, (values.get("class") or "").split(), values)):
            return
        node = (tag, values, [])
        (self.open[-1][2] if self.open else self.trees).append(node)
        if tag not in _VOID_TAGS:
            self.open.append(node)

    def handle_endtag(self, tag):
        super().handle_endtag(tag)
        if tag == "br" and self.open and not self.hidden_depth:
            self.open[-1][2].append(("br", {}, []))  # 브라우저는 `</br>`를 `<br>`로 읽는다.
        if self.hidden_depth or not self.open or tag in _VOID_TAGS:
            return
        if self.open[-1][0] != tag:
            raise ValueError(self.error)
        self.open.pop()

    def handle_data(self, data):
        super().handle_data(data)
        if self.open and not self.hidden_depth:
            self.open[-1][2].append(data)


def _read(text: str, select, error: str) -> _Page:
    if not isinstance(text, str) or "\x00" in text:
        raise ValueError(error)
    parser = _Page(select, error)
    parser.feed(text)
    parser.close()
    if parser.open or parser.hidden_depth:
        raise ValueError(error)
    return parser


def _elements(node: tuple) -> list[tuple]:
    return [child for child in node[2] if isinstance(child, tuple)]


def _children(node: tuple) -> list[tuple]:
    """요소 밖에 놓인 글자는 화면에 보이지만 읽을 칸이 없으므로 형식 변경으로 본다."""
    if any(isinstance(child, str) and child.strip() for child in node[2]):
        raise ValueError(_INVALID_DETAIL)
    return _elements(node)


def _descendants(node: tuple):
    for child in _elements(node):
        yield child
        yield from _descendants(child)


def _classes(node: tuple) -> list[str]:
    return (node[1].get("class") or "").split()


def _lines(node: tuple, lines: list[list[str]]) -> list[list[str]]:
    for child in node[2]:
        if isinstance(child, str):
            lines[-1].append(child)
        elif child[0] == "br":
            lines.append([])
        else:
            _lines(child, lines)
    return lines


def _value(node: tuple) -> str | None:
    """`br`만 줄바꿈으로 남기고 줄마다 공백을 하나로 줄인다. 빈 줄은 버린다."""
    lines = (" ".join("".join(parts).split()) for parts in _lines(node, [[]]))
    return "\n".join(line for line in lines if line) or None


def _text(node: tuple, error: str = _INVALID_DETAIL) -> str | None:
    """하위 태그가 _TEXT_TAGS뿐인 칸만 읽는다. noscript·details 같은 태그 안 글자는 화면에 나오지 않을 수 있다."""
    if any(child[0] not in _TEXT_TAGS for child in _descendants(node)):
        raise ValueError(error)
    return _value(node)


def _link_id(href: str | None) -> str:
    path, _, query = (href or "").partition("?")
    pairs = [pair.partition("=") for pair in query.split("&")]
    ids = [value for key, _, value in pairs if key == "eduLctreNo"]
    if (path != _VIEW_PATH or [value for key, _, value in pairs if key == "mId"] != [MENU]
            or len(ids) != 1 or _COURSE_ID.fullmatch(ids[0]) is None):
        raise ValueError(_INVALID_LISTING)
    return ids[0]


def parse_course_listing(raw: bytes, *, page: int) -> tuple[int, list[str]]:
    """요청 페이지와 대조한 전체 페이지 수와 원래 순서의 강좌 번호를 반환한다."""
    if type(page) is not int or page < 1 or not isinstance(raw, bytes):
        raise ValueError(_INVALID_LISTING)
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ValueError(_INVALID_LISTING) from None
    parser = _read(text, lambda tag, classes, _: (tag == "p" and "page_num" in classes)
                   or (tag == "table" and "bod_maintain" in classes), _INVALID_LISTING)
    labels = [tree for tree in parser.trees if tree[0] == "p"]
    tables = [tree for tree in parser.trees if tree[0] == "table"]
    if len(labels) != 1 or len(tables) != 1:
        raise ValueError(_INVALID_LISTING)
    captions = [child for child in _elements(tables[0]) if child[0] == "caption"]
    bodies = [child for child in _elements(tables[0]) if child[0] == "tbody"]
    if len(captions) != 1 or not (_value(captions[0]) or "").startswith("수강신청 목록") or len(bodies) != 1:
        raise ValueError(_INVALID_LISTING)
    match = _PAGE_LABEL.fullmatch(_value(labels[0]) or "")
    if match is None:
        raise ValueError(_INVALID_LISTING)
    current, total = int(match[1]), int(match[2])
    if current != page or current > total:
        raise ValueError(f"{_LABEL} 목록의 페이지 번호가 요청과 일치하지 않습니다.")

    rows = _elements(bodies[0])
    if not rows or len(rows) > _MAX_ROWS or any(row[0] != "tr" for row in rows):
        raise ValueError(_INVALID_LISTING)
    ids: list[str] = []
    for row in rows:
        # 제목과 접수상태 단추가 같은 강좌 상세로 연결된다. 다른 링크가 섞이면 형식 변경으로 본다.
        found = {_link_id(link[1].get("href")) for link in _descendants(row) if link[0] == "a"}
        if len(found) != 1:
            raise ValueError(_INVALID_LISTING)
        if found <= set(ids):
            raise ValueError(f"{_LABEL} 목록에 같은 강좌 번호가 있습니다.")
        ids.extend(found)
    return total, ids


def _media(node: tuple, field: str, items: list[dict], hints: set[int]) -> None:
    """교육장 사진·강의계획서 칸의 그림과 첨부 이름을 원래 순서로 모은다. 그 밖의 글자·태그는 형식 변경으로 본다."""
    for child in node[2]:
        if isinstance(child, str):
            if child.strip():
                raise ValueError(_INVALID_DETAIL)
            continue
        tag, values, _ = child
        if tag == "button":  # 슬라이드 이전·다음 단추만 건너뛴다. 그림을 감싼 단추 등은 거부한다.
            if ((values.get("class"), _value(child)) not in (("file_slide_prev", "이전"), ("file_slide_next", "다음"))
                    or [part[0] for part in _descendants(child)] != ["span"]):
                raise ValueError(_INVALID_DETAIL)
            continue
        if tag == "img":
            source = values.get("src") or ""
            items.append({"field": field, "kind": "image", "label": " ".join((values.get("alt") or "").split()) or None,
                          "url": OFFICIAL_ORIGIN + source if _IMAGE.fullmatch(source) else None})
        elif tag == "a" and "onclick" in values:
            match = _DOWNLOAD.fullmatch(values["onclick"] or "")
            # `파일 다운로드` 안내(span.skip)를 뺀 파일 이름. 뺀 요소만 skip class 검사를 통과한다.
            hidden = [part for part in child[2] if isinstance(part, tuple) and "skip" in _classes(part)]
            hints.update(map(id, hidden))
            visible = (tag, values, [part for part in child[2] if part not in hidden])
            items.append({"field": field, "kind": "attachment", "label": _text(visible),
                          "url": f"{OFFICIAL_ORIGIN}{CONTEXT_PATH}/cmm/fms/FileDown.do?atchFileId={match[1]}"
                                 f"&fileSn={match[2]}" if match else None})
        elif tag in ("div", "a"):
            _media(child, field, items, hints)
        else:
            raise ValueError(_INVALID_DETAIL)


def _title(node: tuple) -> tuple[str | None, str]:
    found: dict[str, str | None] = {}
    for child in _children(node):
        kind = _TITLE_PARTS.get(child[1].get("class") or "", "unknown") if child[0] == "span" else "unknown"
        if kind == "unknown" or kind in found:
            raise ValueError(_INVALID_DETAIL)
        if kind:
            found[kind] = _text(child)
    if not found.get("subject") or "state" not in found:
        raise ValueError(f"{_LABEL} 상세의 강좌명 또는 접수상태 칸이 없습니다.")
    return found["state"], found["subject"]


def parse_course_detail(text: str, *, course_id: str) -> dict:
    """강좌 상세 항목을 표시 문구 그대로 보관한다. 날짜·금액·정원·대상은 해석하지 않는다."""
    url = detail_url(course_id)
    parser = _read(text, lambda tag, _, values: tag == "div" and values.get("id") == "learning_cont", _INVALID_DETAIL)
    # 실제 28쪽의 속성 그대로일 때만 받는다. hidden·style·class="blind" 등은 영역 전체를 숨길 수 있다.
    if len(parser.trees) != 1 or parser.trees[0][1] != {"id": "learning_cont", "class": "learning_content"}:
        raise ValueError(_INVALID_DETAIL)
    # 첨부 주소는 페이지 설정의 contextPath로 만들어지므로 선언이 정확히 한 번, /edu여야 한다.
    if _declared_context_paths(parser.scripts) != [CONTEXT_PATH]:
        raise ValueError(f"{_LABEL} 페이지의 사이트 경로가 {CONTEXT_PATH}와 일치하지 않습니다.")
    if {number for script in parser.scripts for number in _ECHO.findall(script)} != {course_id}:
        raise ValueError(f"{_LABEL} 상세의 강좌 번호가 요청과 일치하지 않습니다.")
    blocks = {name: [child for child in _elements(parser.trees[0]) if name in _classes(child)]
              for name in ("bod_title", "bod_write")}
    if any(len(found) != 1 for found in blocks.values()):
        raise ValueError(_INVALID_DETAIL)
    state, title = _title(blocks["bod_title"][0])

    fields = {"reception_status": state, **dict.fromkeys(_TEXT_FIELDS.values())}
    media: list[dict] = []
    hints: set[int] = set()
    seen = set()
    for row in _children(blocks["bod_write"][0]):
        cells = _children(row)
        if row[0] != "dl" or [cell[0] for cell in cells] != ["dt", "dd"]:
            raise ValueError(_INVALID_DETAIL)
        label, value = _text(cells[0]) or "", cells[1]
        if label not in _TEXT_FIELDS and label not in _MEDIA_FIELDS:
            raise ValueError(f"{_LABEL} 상세에 알 수 없는 항목이 있습니다: {label[:40]}")
        if label in seen:
            raise ValueError(f"{_LABEL} 상세의 항목이 중복되었습니다.")
        seen.add(label)
        if label in _MEDIA_FIELDS:
            _media(value, _MEDIA_FIELDS[label], media, hints)
        else:
            fields[_TEXT_FIELDS[label]] = _text(value, f"{_LABEL} 상세의 {label} 칸 형식이 바뀌었습니다.")
    if len(seen) != len(_TEXT_FIELDS) + len(_MEDIA_FIELDS):
        raise ValueError(f"{_LABEL} 상세에 빠진 항목이 있습니다.")
    for node in (block for found in blocks.values() for block in (found[0], *_descendants(found[0]))):
        if (any(name not in _ATTRS and not (name == "style" and value in _STYLES) for name, value in node[1].items())
                or any(token not in _CLASSES and not (token == "skip" and id(node) in hints)
                       for token in _classes(node))):
            raise ValueError(f"{_LABEL} 상세에 화면 표시를 확정할 수 없는 속성이 있습니다.")

    flags = {f"missing:{key}" for key, value in fields.items() if value is None}
    flags.update(f"{item['kind']}:{item['field']}" for item in media)
    return {
        "source": "edu_course",
        "external_id": course_id,
        "official_url": url,
        "title": title,
        "fields": fields,
        "media": media,
        "review_flags": sorted(flags),
    }
