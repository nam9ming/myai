"""안성청년포털 청년정책 목록 카드와 상세의 공개 항목을 표시 문구 그대로 읽는다."""

import re
from urllib.parse import urlencode

from .html_tokens import PinnedHTMLParser
from .libraries import _HIDDEN_ERROR, _MARKUP_ERROR, _VOID_TAGS, _NoticeParser, _notice_record
from .official_web import OFFICIAL_ORIGIN, _fetch
from .road_works import _period

PARSER_VERSION = "youth-policy-parser-v3"
SOURCE = "안성청년포털"
# 메뉴 이름은 `청년문화사업`이지만 categoryId가 빈 값이라 네 분야 정책 전체가 나온다(2026-11-28 확인).
YOUTH_MENU = "0201040000"
YOUTH_LISTING_PATH = f"/youth/policy/list.do?mId={YOUTH_MENU}"
_POLICY_ID = re.compile(r"[1-9][0-9]{0,17}")
_CARD_LINK = re.compile(rf"/youth/policy/view\.do\?mId={YOUTH_MENU}&idx=([1-9][0-9]{{0,17}})&categoryId=([0-9]{{1,9}})")
_PAGE_LABEL = re.compile(r"현재 페이지\s+([1-9][0-9]{0,17})\s*/\s*전체 페이지\s+([1-9][0-9]{0,17})")
_IGNORED_TAGS = {"script", "style", "template", "noscript"}
_CARD_LABELS = ("신청기간", "신청방법")
_INFO_FIELDS = {"작성자": "author", "신청방법": "application_method", "조회": None}  # 조회수는 요청마다 바뀌어 보관하지 않는다.
_INVALID_LISTING = "청년정책 목록 HTML 구조가 올바르지 않습니다."
_INVALID_VIEWER = "청년정책 상세의 대표 이미지 영역 형식이 바뀌었습니다."
# 읽는 영역(목록 `form#list`, 상세 `div.bod_view`, 둘 다 자신 포함)은 2026-11-28 저장한 실제 목록 5쪽·상세 24쪽에
# 나온 태그별 속성과 부모>자식 짝만 받는다. 인라인 스타일은 표본에 없어 받지 않는다. 짝을 고정하면 브라우저가 시작
# 태그로 요소를 대신 닫는 경우(p 안 div, li 안 li 등)가 생기지 않는다(목록의 a 안 a만 따로 막는다).
# 숨김 여부를 따지지 않고 목록 밖은 거부한다.
_LISTING_ATTRS = {
    "a": "class href onclick tabindex title", "div": "class", "fieldset": "class", "figure": "",
    "form": "action id method name", "img": "alt data-attach-id data-file-sn onerror src",
    "input": "id name onclick placeholder title type value", "label": "class for", "legend": "class", "li": "",
    "option": "value", "p": "class", "select": "id name title", "span": "class", "strong": "", "ul": "class"}
_LISTING_NEST = frozenset("a>div div>a div>fieldset div>figure div>p div>span div>ul fieldset>input fieldset>label "
                          "fieldset>legend fieldset>select figure>img form>div form>input li>a p>span select>option "
                          "span>span span>strong ul>li".split())
_DETAIL_ATTRS = {
    "a": "href onclick", "br": "", "button": "class data-origin onclick type", "dd": "",
    "div": "class data-saved-file-container id", "dl": "class", "dt": "", "figure": "", "h4": "", "img": "alt src",
    "li": "class", "script": "src", "span": "class", "ul": "class"}
_DETAIL_NEST = frozenset("a>span button>img dd>div dd>script div>br div>button div>div div>dl div>figure div>h4 "
                         "div>script div>ul dl>dd dl>dt dt>span figure>img li>a li>button li>span ul>li".split())
# 신청방법 칸 값 전체가 상태어·자리표시인 경우(실제 `모집마감`, `.`). 걸러 내지 않고 표시만 단다.
# 상태어가 든 한 낱말(`조기마감`·`(마감)`)과 그 앞 낱말 하나(`접수 종료`·`신청 (마감)`)까지만 맞춘다.
# `선착순 마감 시까지 방문 접수`처럼 방법 문구 안의 상태어는 맞추지 않는다.
_NOT_METHOD = re.compile(r"[^0-9A-Za-z가-힣]*|(?:\S+\s)?\S*(?:마감|종료)\S*")
# 상세 본문 맨 앞의 대표 이미지 영역(div.photo_viewer)은 본문 텍스트로 읽지 않는다. 상세 24쪽 모두 같은 틀이었고,
# 그 표본의 부모>자식 짝(None은 영역 자신)별 속성·스크립트 주소·글자만 받는다. 개수·순서·글자 위치는 보지 않는다.
_VIEWER_ATTRS = {None: "class", "div>div": "class id", "div>figure": "", "figure>img": "alt src",
                 "div>button": "class type", "div>ul": "class", "ul>li": "class",
                 "li>button": "data-origin onclick type", "button>img": "alt src", "div>script": "src"}
_VIEWER_SCRIPTS = {"/common/js/swiper/swiper.js", "/portal/js/unit/cardNews/view.js"}
_VIEWER_TEXT = {"", "이전보기", "다음보기", "init_thumbnail_view('.photo_viewer');"}
_VIEWER_IMAGE = re.compile(
    r"/common/imgView\.do\?attachId=[0-9a-f]{64}&fileSn=[0-9a-f]{32}&mode=ratioView(?:&width=500&heigth=500)?")
# 시청 고시·공고 제목 검색. 같은 사업의 원공고·정정 공고 후보를 찾는 주소일 뿐 일치를 확인하지 않는다.
CITY_NOTICE_LIST = OFFICIAL_ORIGIN + "/portal/saeol/gosiList.do"


def youth_detail_url(policy_id: str) -> str:
    if not isinstance(policy_id, str) or _POLICY_ID.fullmatch(policy_id) is None:
        raise ValueError("청년정책 번호는 18자리 이하의 양의 ASCII 정수여야 합니다.")
    return f"{OFFICIAL_ORIGIN}/youth/policy/view.do?mId={YOUTH_MENU}&idx={policy_id}"


def city_notice_search_url(title: str) -> str:
    return CITY_NOTICE_LIST + "?" + urlencode(
        {"mId": "0501040000", "seCode": "01", "searchType": "NOT_ANCMT_SJ", "searchTxt": title})


def fetch_youth_listing(page: int, *, limit: int) -> bytes:
    if type(page) is not int or page < 1:
        raise ValueError("목록 페이지는 양의 정수여야 합니다.")
    return _fetch("POST", YOUTH_LISTING_PATH, urlencode({"page": page}).encode("ascii"), limit, source=SOURCE)


def fetch_youth_detail(policy_id: str, *, limit: int) -> bytes:
    path = youth_detail_url(policy_id).removeprefix(OFFICIAL_ORIGIN)
    return _fetch("GET", path, None, limit, source=SOURCE)


def _text(parts: list[str]) -> str:
    return " ".join("".join(parts).split())


def _allowed(tag, names, parent, attrs, nest) -> bool:
    """속성이 중복 없이 태그별 허용 목록 안에 있고, 영역 뿌리(`parent=None`)가 아니면 부모>자식 짝도 표본에 있다."""
    return (tag in attrs and len(set(names)) == len(names) and set(names) <= set(attrs[tag].split())
            and (parent is None or f"{parent}>{tag}" in nest))


class _ListingParser(PinnedHTMLParser):
    """`form#list` 안의 숨은 입력·페이지 표시·정책 카드만 읽는다. 카드 안 다른 위치의 글자는 형식 변경으로 본다."""

    def __init__(self):
        super().__init__()
        self.ignored: list[str] = []  # 열린 숨김 요소 이름. 짝이 맞지 않는 종료 태그는 브라우저가 무시해 숨김 범위가 갈린다.
        self.form_seen = self.in_form = False
        self.stack: list[tuple[str, list[str], list[str] | None]] = []
        self.inputs: dict[str, list[str | None]] = {}
        self.page_info: tuple[int, int] | None = None
        self.card: dict | None = None
        self.cards: list[dict] = []

    def fail(self):
        raise ValueError(_INVALID_LISTING)

    def markup_error(self):
        return ValueError(_MARKUP_ERROR.format("청년정책 목록"))

    def handle_starttag(self, tag, attrs):
        super().handle_starttag(tag, attrs)
        names = [name for name, _ in attrs]
        values = dict(attrs)
        # 폼 안에서는 숨김 요소(script 등)도 목록 밖이라 열리지 않으므로, 폼 안에서 self.ignored는 늘 비어 있다.
        root = tag == "form" and values.get("id") == "list" and not self.ignored
        if self.in_form or root:
            parent = self.stack[-1][0] if self.stack else "form" if self.in_form else None
            if (not _allowed(tag, names, parent, _LISTING_ATTRS, _LISTING_NEST)
                    or (tag == "a" and any(entry[0] == "a" for entry in self.stack))):  # 브라우저는 a 안 a를 닫는다.
                self.fail()
        if tag in _IGNORED_TAGS:
            self.ignored.append(tag)
        if self.ignored:
            return
        if root:
            if self.form_seen or values.get("action") != YOUTH_LISTING_PATH:
                self.fail()
            self.form_seen = self.in_form = True
            return
        if not self.in_form:
            return
        classes = (values.get("class") or "").split()
        parent = self.stack[-1] if self.stack else ("form", [], None)
        slot = None
        if tag == "input" and values.get("type") == "hidden":
            self.inputs.setdefault(values.get("name"), []).append(values.get("value"))
        elif "page_num" in classes:
            if tag != "p":  # 페이지 표시가 p가 아니면 형식 변경이다. 끝 태그에서 글자 슬롯을 읽으므로 여기서 막는다.
                self.fail()
            slot = []
        elif tag == "li" and parent[0] == "ul" and len(self.stack) > 1 and "bod_photo" in self.stack[-2][1]:
            if self.card is not None:
                self.fail()
            self.card = {"links": [], "category": None, "title": None, "info": [], "depth": len(self.stack)}
        elif self.card is not None:
            slot = self._card_slot(tag, classes, parent, values)
        if tag not in _VOID_TAGS:
            self.stack.append((tag, classes, slot))

    def _card_slot(self, tag, classes, parent, values):
        card = self.card
        if tag == "a" and parent[0] == "li":
            card["links"].append(values.get("href") or "")
        # thumb·tit 분기보다 먼저 둔다. `.cont > span.info`는 class가 더 붙어도 모두 항목을 만든다.
        elif tag == "span" and "info" in classes and "cont" in parent[1]:
            card["info"].append([None, None])
        elif tag == "span" and "thumb" in parent[1] and card["category"] is None:
            card["category"] = []
            return card["category"]
        elif tag == "span" and "tit" in classes and "cont" in parent[1] and card["title"] is None:
            card["title"] = []
            return card["title"]
        # 위 분기에서 항목을 만든 `.cont > span.info` 바로 아래만 읽는다. 다른 .info 요소는 글자가 있으면 형식 변경이다.
        elif (tag in ("strong", "span") and parent[0] == "span" and "info" in parent[1]
              and "cont" in self.stack[-2][1]):
            index = 0 if tag == "strong" else 1
            if card["info"][-1][index] is not None:
                self.fail()
            card["info"][-1][index] = []
            return card["info"][-1][index]
        return None

    def handle_endtag(self, tag):
        if self.ignored:
            if tag in _IGNORED_TAGS:
                if tag != self.ignored[-1]:
                    self.fail()
                self.ignored.pop()
            return
        if not self.in_form or tag in _VOID_TAGS:
            return
        if tag == "form":
            if self.stack or self.card is not None:
                self.fail()
            self.in_form = False
            return
        if not self.stack or self.stack[-1][0] != tag:
            self.fail()
        _, classes, slot = self.stack.pop()
        if "page_num" in classes:
            match = _PAGE_LABEL.fullmatch(_text(slot))
            if match is None or self.page_info is not None:
                self.fail()
            self.page_info = (int(match[1]), int(match[2]))
        elif self.card is not None and len(self.stack) == self.card["depth"]:
            self._end_card()

    def _end_card(self):
        card, self.card = self.card, None
        match = _CARD_LINK.fullmatch(card["links"][0]) if len(card["links"]) == 1 else None
        info = [(_text(label or []), _text(value) if value is not None else None) for label, value in card["info"]]
        if (match is None or card["title"] is None or not _text(card["title"]) or card["category"] is None
                or tuple(label for label, _ in info) != _CARD_LABELS or len(self.cards) == 100):
            self.fail()
        self.cards.append({
            "policy_id": match[1],
            "category_id": match[2],
            "category": _text(card["category"]) or None,
            "title": _text(card["title"]),
            "application_period": info[0][1] or None,
            "application_method": info[1][1] or None,
        })

    def handle_data(self, data):
        super().handle_data(data)
        if self.ignored or not self.in_form:
            return
        slot = next((entry[2] for entry in reversed(self.stack) if entry[2] is not None), None)
        if slot is not None:
            slot.append(data)
        elif self.card is not None and data.strip():
            self.fail()


def parse_youth_listing(raw: bytes, *, page: int) -> tuple[int, list[dict]]:
    """요청 페이지와 대조한 전체 페이지 수와 원래 순서의 정책 카드(신청기간·신청방법 표시 문구 포함)를 반환한다."""
    if type(page) is not int or page < 1 or not isinstance(raw, bytes) or b"\x00" in raw:
        raise ValueError(_INVALID_LISTING)
    parser = _ListingParser()
    try:
        parser.feed(raw.decode("utf-8-sig"))
        parser.close()
    except (UnicodeDecodeError, AssertionError):
        raise ValueError(_INVALID_LISTING) from None
    if not parser.form_seen or parser.in_form or parser.ignored or parser.page_info is None or not parser.cards:
        raise ValueError(_INVALID_LISTING)
    if parser.inputs.get("categoryId") != [""]:
        raise ValueError("청년정책 목록이 전체 분야가 아닌 특정 분야로 걸러져 있습니다.")
    current, total = parser.page_info
    if parser.inputs.get("page") != [str(page)] or current != page or current > total:
        raise ValueError("청년정책 목록의 페이지 번호가 요청과 일치하지 않습니다.")
    ids = [card["policy_id"] for card in parser.cards]
    if len(set(ids)) != len(ids):
        raise ValueError("청년정책 목록에 같은 정책 번호가 있습니다.")
    for card in parser.cards:
        card["page"] = page
    return total, parser.cards


class _PolicyParser(_NoticeParser):
    """게시판 공지 파서의 태그 경계·본문 허용 목록을 그대로 쓰고, 청년포털의 다른 점만 덧붙인다.

    번호는 `input[name=idx]`, 게시판 대조는 `form#list` action, 작성자·신청방법은 `div.view_info`의 항목에서 읽는다.
    """

    def __init__(self):
        super().__init__(label="청년정책", view_action=YOUTH_LISTING_PATH, require_view=True)
        self.categories: list[str | None] = []
        self.info: list[str] = []
        self.viewer: list[str] | None = None
        self.viewer_seen = False
        self.images: list[str] = []

    def handle_starttag(self, tag, attrs):
        names = [name for name, _ in attrs]
        values = dict(attrs)
        classes = (values.get("class") or "").split()
        viewer = self.viewer is not None or (
            self.section == "description" and len(self.tags) == self.section_depth and not self.hidden_depth
            and tag == "div" and "photo_viewer" in classes)
        # 중복 class면 브라우저는 첫 값을 써 대표 이미지 틀이 아닌 본문으로 보이므로, 틀 여부와 함께 여기서 거부한다.
        if (self.tags or (tag == "div" and "bod_view" in classes)) and not _allowed(
                tag, names, (self.viewer or self.tags or [None])[-1], _DETAIL_ATTRS, _DETAIL_NEST):
            raise ValueError(_INVALID_VIEWER if viewer else _HIDDEN_ERROR.format(self.label))
        if viewer:
            # 대표 이미지 틀은 공지 본문 허용 목록 대신 위 표본 허용 목록과 아래 틀 검사를 받는다.
            PinnedHTMLParser.handle_starttag(self, tag, attrs)
            if self.viewer is None:
                if self.viewer_seen or "".join(self.parts["description"]).strip():
                    raise ValueError(_INVALID_VIEWER)
                self.viewer, self.viewer_seen = [], True
            self._viewer_start(tag, names, values)
            return
        super().handle_starttag(tag, attrs)
        # 최상위 form·input은 공지 파서가 태그 깊이·숨김 깊이를 바꾸지 않으므로 호출 뒤에 봐도 같다.
        if not self.tags and not self.hidden_depth:
            if tag == "form" and values.get("id") == "list":
                if names.count("id") != 1 or names.count("action") != 1:
                    raise ValueError(self.label + " 상세 폼의 HTML 속성이 중복되었습니다.")
                self.view_actions.append(values.get("action"))
            if tag == "input" and values.get("name") in ("idx", "categoryId"):
                if names.count("name") != 1 or names.count("value") != 1:
                    raise ValueError(self.label + " 번호·분야 입력의 HTML 속성이 없거나 중복되었습니다.")
                if values["name"] == "idx":
                    self.notice_ids.add(values["value"])
                else:
                    self.categories.append(values["value"])
        if self.section is None and not self.hidden_depth and self.tags == ["div", "div", "ul", "li"]:
            self.section, self.section_depth = f"info{len(self.info)}", 4
            self.parts[self.section] = []
            self.info.append(self.section)

    def _viewer_start(self, tag, names, values):
        pair = f"{self.viewer[-1]}>{tag}" if self.viewer else None
        source = values.get("src") or ""
        # 원본 주소(data-origin)는 슬라이드 li 바로 아래, 원본 보기 onclick이 있는 버튼에서만 읽는다.
        if (pair not in _VIEWER_ATTRS or not set(names) <= set(_VIEWER_ATTRS[pair].split())
                or (tag == "script" and names and source not in _VIEWER_SCRIPTS)
                or (tag == "img" and not _VIEWER_IMAGE.fullmatch(source))
                or (pair == "li>button" and values.get("onclick") != "fn_view_original(this);")):
            raise ValueError(_INVALID_VIEWER)
        if "data-origin" in values:
            origin = values["data-origin"] or ""
            if not _VIEWER_IMAGE.fullmatch(origin):
                raise ValueError(_INVALID_VIEWER)
            self.images.append(OFFICIAL_ORIGIN + origin)
        if tag not in _VOID_TAGS:
            self.viewer.append(tag)

    def handle_endtag(self, tag):
        if self.viewer is None:
            # 본문 영역의 종료 태그는 가장 안쪽 요소만 닫는다. 공지 파서가 대신 닫는 생략 가능 태그(li 등)도 받지 않는다.
            if self.tags and tag not in _VOID_TAGS and self.tags[-1] != tag:
                raise ValueError(self.label + " HTML 구조가 올바르지 않습니다.")
            super().handle_endtag(tag)
        elif tag not in _VOID_TAGS:
            if self.viewer[-1] != tag:
                raise ValueError(_INVALID_VIEWER)
            self.viewer.pop()
            self.viewer = self.viewer or None

    def handle_data(self, data):
        if self.viewer is None:
            super().handle_data(data)
            return
        PinnedHTMLParser.handle_data(self, data)
        if data.strip() not in _VIEWER_TEXT:
            raise ValueError(_INVALID_VIEWER)


def parse_youth_detail(text: str, *, policy_id: str, card: dict) -> dict:
    """상세 본문·작성자·신청방법과 목록 카드(신청기간)를 고치지 않고 묶는다.

    카드 `신청기간` 칸에는 사업·운영 기간이 든 글도 있어(2026-11-28 확인) 날짜 범위는 `listing_period_range`로만
    옮기고 모든 기록에 `application_period_unconfirmed`를 단다.

    지원 대상·금액은 별도 항목 없이 본문 자유 서술에만 있어 뽑지 않는다. 자격·마감은 시청 원공고가 기준이므로
    그 공고는 제목 검색 후보 주소만 남기고 이 기록의 값으로 덮어쓰지 않는다.
    """
    url = youth_detail_url(policy_id)
    if not isinstance(card, dict) or card.get("policy_id") != policy_id:
        raise ValueError("청년정책 목록 카드가 상세 번호와 일치하지 않습니다.")
    parser = _PolicyParser()
    record = _notice_record(parser, text, policy_id, "youth_policy", lambda: url)
    if len(parser.categories) != 1 or not re.fullmatch(r"[0-9]{1,9}", parser.categories[0] or ""):
        raise ValueError("청년정책 상세의 분야 번호를 확인할 수 없습니다.")
    fields = record["fields"]
    flags = set(record.pop("review_flags", []))
    for section in parser.info:
        label, colon, value = _text(parser.parts[section]).partition(":")
        label = label.strip()
        key = _INFO_FIELDS.get(label, "")
        if not colon or key == "" or key in fields:
            raise ValueError(f"청년정책 상세에 알 수 없거나 중복된 항목이 있습니다: {label[:40]}")
        if key:
            fields[key] = value.strip() or None
    for key in ("author", "application_method"):
        if fields.setdefault(key, None) is None:
            flags.add(f"missing:{key}")
    period, problem = _period(card["application_period"])
    flags.update(name for name, differs in (
        (problem, problem is not None),
        ("missing:application_period", card["application_period"] is None),
        ("listing_category_differs", card["category_id"] != parser.categories[0]),
        ("listing_method_differs", card["application_method"] != fields["application_method"]),
        ("application_method_not_method", any(
            value is not None and _NOT_METHOD.fullmatch(value)
            for value in (card["application_method"], fields["application_method"]))),
        ("application_period_unconfirmed", True),
    ) if differs)
    record.update({
        "category_id": parser.categories[0],
        "listing": card,
        "listing_period_range": period,
        # 대상·금액은 본문이나 첨부에만 있고 어느 쪽인지도 확인하지 않아 위치를 단정하지 않는다.
        "unknown": {"support_target": "not_extracted", "support_amount": "not_extracted"},
        "city_notice_candidate": {"search_url": city_notice_search_url(card["title"]), "status": "unverified"},
        "images": parser.images,
        "review_flags": sorted(flags),
    })
    return record
