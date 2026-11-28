"""안성맞춤아트홀 공연·전시 전체일정의 월별 목록과 상세 공개 항목을 읽는다."""

from datetime import datetime
from html.parser import HTMLParser
import re
from urllib.parse import urlencode

from .official_web import OFFICIAL_ORIGIN, _fetch
from .road_works import _BREAK_TAGS, _TEXT_TAGS, _VOID_TAGS, _period, _text

PARSER_VERSION = "arthall-concert-parser-v1"
_MENU = "0202010100"
_LIST_ACTION = f"/arthall/concert/list.do?scCategory=&mId={_MENU}"
_SOURCE = "안성맞춤아트홀"
CONCERT_ID = re.compile(r"[1-9][0-9]{0,17}")
_VIEW = re.compile(r"go_view\('([1-9][0-9]{0,17})'\); return false;")
_PAGE = re.compile(r"goPage\(([1-9][0-9]{0,3})\); return false;")
# 상세 스크립트의 예매 모듈 초기화. 넷째 인자 이후는 로그인 세션 값이라 읽지 않는다.
_INIT = re.compile(r"module\.init\('([^'\\]*)', '([^'\\]*)', '([0-9]*)', '[^'\\]*', '[^'\\]*', '[^'\\]*'\);")
_TICKET_OPEN = re.compile(r"([0-9]{4}-[0-9]{2}-[0-9]{2}) ([0-9]{2}:[0-9]{2}) ~")
_EMPTY = "검색된 전체일정이 없습니다."
_NOT_FOUND = "존재하지 않는 공연/전시입니다."
_SECTION_TAGS = _TEXT_TAGS | {"div", "img"}
_INVALID_LISTING = "안성맞춤아트홀 일정 목록 HTML 구조가 올바르지 않습니다."
_INVALID_DETAIL = "안성맞춤아트홀 공연·전시 상세 HTML 구조가 올바르지 않습니다."
# 브라우저가 안을 마크업으로 읽지 않는 원문 요소. 3.13은 script·style만, 3.14는 나머지도 원문으로 읽는다.
_RAW_TEXT = ("script", "style", "xmp", "iframe", "noembed", "noframes", "textarea", "title")
# 따옴표·`=` 든 끝 태그와 `</title >`처럼 이름 바로 뒤가 `>`가 아닌 원문 요소 끝 태그는 버전마다 끝 위치가 다르다.
# `</ div>`·`</\ndiv>`처럼 `</` 바로 뒤가 공백이면 3.13은 끝 태그로, 3.14와 브라우저는 주석으로 읽는다.
_ODD_END = re.compile(r"</\s|</[A-Za-z][^>]*[\"'=]|</(?!(?:{0})>)(?:{0})\b".format("|".join(_RAW_TEXT)), re.I)
_FIELDS = {
    "장르": "genre", "기간": "period", "시간": "time", "관람시간": "running_time", "장소": "venue",
    "관람연령": "age_rating", "입장권": "admission", "티켓 오픈 일시": "ticket_open", "문의처": "contact",
    "주최/주관": "host", "제작": "production", "연출": "director", "작": "writer", "출연": "cast",
    "내용": "description",
}
# 2026-11-28 실제 상세 13건에 모두 있던 항목. 비어 있거나 없으면 missing 표시를 남긴다.
_CORE = ("genre", "period", "time", "venue", "age_rating", "admission", "ticket_open", "contact", "host")


def listing_path(year: int, month: int, page: int) -> str:
    if type(year) is not int or not 2000 <= year <= 2100 or type(month) is not int or not 1 <= month <= 12:
        raise ValueError("아트홀 일정은 2000~2100년의 1~12월로 지정해야 합니다.")
    if type(page) is not int or page < 1:
        raise ValueError("목록 페이지는 양의 정수여야 합니다.")
    return "/arthall/concert/list.do?" + urlencode({"mId": _MENU, "year": year, "month": month, "page": page})


def _detail_path(concert_id: str) -> str:
    if not isinstance(concert_id, str) or CONCERT_ID.fullmatch(concert_id) is None:
        raise ValueError("아트홀 공연 번호는 18자리 이하의 양의 ASCII 정수여야 합니다.")
    return "/arthall/concert/view.do?" + urlencode({"idx": concert_id, "mId": _MENU})


def detail_url(concert_id: str) -> str:
    return OFFICIAL_ORIGIN + _detail_path(concert_id)


def fetch_listing(year: int, month: int, page: int, *, limit: int) -> bytes:
    return _fetch("GET", listing_path(year, month, page), None, limit, source=f"{_SOURCE} 목록")


def fetch_detail(concert_id: str, *, limit: int) -> bytes:
    return _fetch("GET", _detail_path(concert_id), None, limit, source=f"{_SOURCE} 상세")


class _Parser(HTMLParser):
    """정해진 영역(같은 이름 태그의 깊이로 끝을 찾는다) 안만 읽고, 영역 안 글자 모음(capture)을 공통으로 처리한다."""

    REGIONS: dict = {}
    CDATA_CONTENT_ELEMENTS = _RAW_TEXT

    def __init__(self, error: str):
        super().__init__(convert_charrefs=True)
        self.error = error
        self.region = None
        self.depth = 0
        self.capture = None  # [끝 태그, 깊이, 조각, 허용 태그, 완료 함수]
        self.counts = {}
        self.scripts = []

    def fail(self):
        raise ValueError(self.error)

    def run(self, text: str):
        if not isinstance(text, str) or "\x00" in text or _ODD_END.search(text):
            self.fail()
        try:
            self.feed(text)
            self.close()
        except AssertionError:
            self.fail()
        if self.region is not None or self.capture is not None:
            self.fail()
        return self

    def parse_comment(self, i, report=True):
        # 주석 끝을 브라우저처럼 첫 `-->`로 고정한다(3.13.5는 `--\s*>`, 3.14는 `--!?>`에서 닫아 결과가 갈렸다).
        # 해석이 갈리는 `<!-->`·`<!--->`·`--!>`와 닫히지 않은 주석(문서를 한 번에 넣으므로 문서 끝까지)은 거부한다.
        end = self.rawdata.find("-->", i + 4)
        if end < 0 or self.rawdata.startswith((">", "->"), i + 4) or "--!>" in self.rawdata[i + 4:end]:
            self.fail()
        return end + 3

    def parse_html_declaration(self, i):
        # 실제 문서의 `<!DOCTYPE html>`만 받는다. CDATA·가짜 주석·따옴표 든 선언은 버전마다 읽는 범위가 다르다.
        end = self.rawdata.find(">", i + 2)
        if end < 0 or re.fullmatch(r"<!doctype html", self.rawdata[i:end], re.I) is None:
            self.fail()
        return end + 1

    def parse_pi(self, i):
        # 실제 문서에 없고, 닫히지 않은 `<?`는 Python 버전마다 읽는 범위가 다르다.
        self.fail()

    def start_capture(self, tag, allowed, done):
        self.capture = [tag, 1, [], allowed, done]

    def handle_startendtag(self, tag, attrs):
        # 브라우저는 void가 아닌 `<div/>`·`<title/>`의 `/`를 무시해 열어 둔다(원문 요소면 다음 끝 태그까지 글자).
        # 영역 밖이어도 뒤 영역이 화면에서 사라질 수 있다. 실제 원본에는 void가 아닌 self-closing 태그가 없다.
        if tag not in _VOID_TAGS:
            self.fail()
        self.handle_starttag(tag, attrs)

    def handle_starttag(self, tag, attrs):
        if tag == "plaintext":  # 3.14만 문서 끝까지 원문으로 읽는다.
            self.fail()
        values = dict(attrs)
        classes = (values.get("class") or "").split()
        if self.capture is not None:
            end, _, parts, allowed, _ = self.capture
            if tag not in allowed:
                raise ValueError(f"{self.error} 허용하지 않는 태그: {tag[:20]}")
            self.capture[1] += tag == end
            # div는 본문 섹션에서만 허용되고, 브라우저처럼 블록 경계에서 낱말을 띄운다.
            if tag in _BREAK_TAGS or tag == "div":
                parts.append(" ")
            self.capture_start(tag, values, classes)
            return
        if self.region is not None:
            self.depth += tag == self.region
            self.region_start(tag, values, classes)
            return
        for kind, (root, match) in self.REGIONS.items():
            if tag == root and match(values, classes):
                self.counts[kind] = self.counts.get(kind, 0) + 1
                self.region, self.depth, self.kind = root, 1, kind
                self.region_open(kind, values)
                return
        self.outside_start(tag, values)

    def handle_endtag(self, tag):
        if self.capture is not None:
            end, _, parts, _, done = self.capture
            if tag in _BREAK_TAGS or tag == "div":
                parts.append(" ")
            self.capture_end(tag)
            if tag == end:
                self.capture[1] -= 1
                if not self.capture[1]:
                    self.capture = None
                    done(_text(parts))
            return
        if self.region is not None and tag == self.region:
            self.depth -= 1
            if not self.depth:
                self.region = None

    def handle_data(self, data):
        if self.cdata_elem == "script":
            # 브라우저는 `<!--<script>` 뒤 첫 `</script>`에서 script를 끝내지 않는다. 실제 원본 script에는 `<!--`가 없다.
            if "<!--" in data:
                self.fail()
            self.scripts.append(data)
        elif self.capture is not None:
            self.capture_data(data)
        elif self.region is not None:
            self.region_data(data)

    def capture_data(self, data):
        self.capture[2].append(data)

    def capture_start(self, tag, values, classes):
        pass

    def capture_end(self, tag):
        pass

    def region_open(self, kind, values):
        pass

    def region_data(self, data):
        pass

    def outside_start(self, tag, values):
        pass


def _has(name):
    return lambda _values, classes: name in classes


class _ListingParser(_Parser):
    REGIONS = {"list": ("div", _has("con_list")), "pages": ("div", _has("bod_page"))}

    def __init__(self):
        super().__init__(_INVALID_LISTING)
        self.in_form = False
        self.actions = []
        self.hidden = {}
        self.ids = []
        self.infos = 0
        self.text = []
        self.current = []
        self.links = []

    def outside_start(self, tag, values):
        if tag == "form" and values.get("id") == "listForm":
            if self.in_form:
                self.fail()
            self.in_form = True
            self.actions.append(values.get("action"))
        elif tag == "input" and self.in_form and values.get("type") == "hidden" and values.get("name"):
            if values["name"] in self.hidden:
                self.fail()
            self.hidden[values["name"]] = values.get("value")

    def handle_endtag(self, tag):
        super().handle_endtag(tag)
        if tag == "form" and self.region is None:
            self.in_form = False

    def region_open(self, kind, values):
        if not self.in_form:
            self.fail()

    def region_start(self, tag, values, classes):
        if self.kind == "list":
            self.infos += tag == "div" and "con_listInfo" in classes
            if tag == "button" and "onclick" in values:
                match = _VIEW.fullmatch(values["onclick"] or "")
                if match is None:
                    self.fail()
                self.ids.append(match[1])
        elif tag == "span":
            self.start_capture("span", (), self.current.append)
        elif tag == "a":
            match = _PAGE.fullmatch(values.get("onclick") or "")
            if match is None:
                self.fail()
            self.start_capture("a", (), lambda text, number=match[1]: self.links.append((number, text)))
        else:
            self.fail()

    def region_data(self, data):
        if self.kind == "list":
            self.text.append(data)
        elif data.strip():
            self.fail()


def parse_listing(raw: bytes, *, year: int, month: int, page: int) -> tuple[int, list[str]]:
    """요청 연월·페이지와 대조한 전체 페이지 수와 원래 순서의 공연 번호를 반환한다."""
    listing_path(year, month, page)
    if not isinstance(raw, bytes):
        raise ValueError(_INVALID_LISTING)
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ValueError(_INVALID_LISTING) from None
    parser = _ListingParser().run(text)
    if parser.actions != [_LIST_ACTION] or parser.counts.get("list") != 1 or parser.counts.get("pages", 0) > 1:
        raise ValueError(_INVALID_LISTING)
    hidden = parser.hidden
    if (hidden.get("year") != str(year) or hidden.get("month") not in (str(month), f"{month:02d}")
            or hidden.get("rangeType") != "" or hidden.get("page") != str(page)):
        raise ValueError("안성맞춤아트홀 일정 목록의 연월 또는 페이지가 요청과 일치하지 않습니다.")
    if len(set(parser.ids)) != len(parser.ids) or parser.infos != len(parser.ids):
        raise ValueError(_INVALID_LISTING)
    if not parser.ids and (_text(parser.text) != _EMPTY or page != 1 or parser.counts.get("pages")):
        raise ValueError(_INVALID_LISTING)
    if not parser.counts.get("pages"):
        # 실제 원본에서 쪽 번호 영역이 없는 목록은 결과 없는 달뿐이었다. 공연이 있으면 쪽 수를 확정할 수 없다.
        if parser.ids:
            raise ValueError(_INVALID_LISTING)
        return 1, []
    # 쪽 번호 영역은 현재 쪽 하나와 나머지 쪽 링크만 1부터 빠짐없이 있어야 한다(다음·끝 버튼이 생기면 형식 변경).
    numbers = {int(number) for number, label in parser.links if label == number}
    if (parser.current != [str(page)] or len(numbers) != len(parser.links) or page in numbers
            or numbers | {page} != set(range(1, len(numbers) + 2))):
        raise ValueError("안성맞춤아트홀 일정 목록의 쪽 번호가 요청과 일치하지 않습니다.")
    return len(numbers) + 1, parser.ids


def _check_hidden(values: dict) -> None:
    # 탭 본문 영역 자신의 display:none은 화면 스크립트가 탭을 열 때 풀리므로 영역 안쪽만 본다.
    if "hidden" in values or re.search(r"display|visibility", values.get("style") or "", re.I):
        raise ValueError("안성맞춤아트홀 상세에 화면 표시를 확정할 수 없는 숨김 표기가 있습니다.")


class _DetailParser(_Parser):
    REGIONS = {
        "image": ("div", _has("conInfo_img")),
        "info": ("div", _has("conInfo_list")),
        "tabs": ("ul", _has("tab_view")),
        "section": ("div", _has("tap_wrapper")),
    }

    def __init__(self):
        super().__init__(_INVALID_DETAIL)
        self.actions = []
        self.posters = []
        self.buttons = []
        self.in_buttons = 0
        self.categories = []
        self.titles = []
        self.pairs = []
        self.label = None
        self.tabs = []
        self.sections = {}
        self.section = None
        self.notice = False

    def outside_start(self, tag, values):
        if tag == "form" and values.get("id") == "cancel":
            self.actions.append(values.get("action"))

    def region_open(self, kind, values):
        if kind == "section":
            match = re.fullmatch(r"tap_wrapper([1-9][0-9]?)", values.get("id") or "")
            if match is None or match[1] in self.sections:
                self.fail()
            self.section = self.sections[match[1]] = {"text": None, "images": [], "links": []}
            self.start_capture("div", _SECTION_TAGS, self._close_section)
            self.region = None

    def _close_section(self, text):
        self.section["text"] = text or None
        self.section = None

    def region_start(self, tag, values, classes):
        _check_hidden(values)
        if self.kind == "image":
            if tag == "img" and not self.in_buttons:
                self.posters.append(values.get("src"))
            elif tag == "div" and "ticket_btns" in classes:
                self.in_buttons = self.depth
            elif tag == "a" and self.in_buttons:
                self.start_capture("a", (), self.buttons.append)
            elif tag not in ("div", "p", "span", "a"):
                self.fail()
        elif self.kind == "tabs":
            if tag == "a":
                index = values.get("onclick") or ""
                match = re.fullmatch(r"goTab\(([1-9][0-9]?)\); return false;", index)
                if match is None:
                    self.fail()
                self.start_capture("a", (), lambda text, key=match[1]: self.tabs.append((key, text)))
            elif tag != "li":
                self.fail()
        elif tag == "span" and "title" in classes and self.label is None:
            self.start_capture("span", (), self._set_label)
        elif tag == "span" and "sub" in classes and self.label is not None:
            self.start_capture("span", _TEXT_TAGS, self._set_value)
        elif tag == "span" and any(name.startswith("category_") for name in classes):
            self.start_capture("span", (), self.categories.append)
        elif tag == "h4":
            self.start_capture("h4", (), self.titles.append)
        elif tag not in ("ul", "li"):
            self.fail()

    def handle_endtag(self, tag):
        if self.in_buttons and self.capture is None and tag == "div" and self.depth == self.in_buttons:
            self.in_buttons = 0
        if tag == "li" and self.capture is None and self.region and self.kind == "info" and self.label is not None:
            self.fail()
        super().handle_endtag(tag)

    def _set_label(self, text):
        self.label = text

    def _set_value(self, text):
        self.pairs.append((self.label, text))
        self.label = None

    def region_data(self, data):
        if data.strip() and self.kind in ("info", "tabs"):
            self.fail()

    def capture_start(self, tag, values, classes):
        _check_hidden(values)
        if self.section is None:
            return
        # 안내 문단 안 태그는 브라우저가 p를 암묵적으로 닫아 뒤 본문이 보일 수 있다. 실제 안내는 글자뿐이었다.
        if "tap_wrapper" in classes or self.notice:
            self.fail()
        if tag == "p" and "p_notice" in classes:
            self.notice = True
        elif tag == "img":
            self.section["images"].append(values.get("src"))
        elif tag == "a":
            self.section["links"].append(values.get("href"))

    def capture_end(self, tag):
        if self.notice and tag != "p":
            self.fail()
        if tag == "p":
            self.notice = False

    def capture_data(self, data):
        if not self.notice:
            super().capture_data(data)


def parse_detail(text: str, *, concert_id: str) -> dict:
    """상세 표시 문구를 그대로 보관하고, 공연 기간과 티켓 오픈 시각은 정확한 형식만 따로 읽는다."""
    url = detail_url(concert_id)
    parser = _DetailParser().run(text)
    script = "".join(parser.scripts)
    if not parser.counts.get("info") and _NOT_FOUND in script:
        raise ValueError("공식 사이트가 존재하지 않는 공연·전시라고 응답했습니다.")
    if (parser.actions != [_LIST_ACTION] or parser.counts.get("image") != 1 or parser.counts.get("info") != 1
            or parser.counts.get("tabs", 0) > 1 or len(parser.titles) != 1 or len(parser.categories) > 1
            or len(parser.posters) > 1 or parser.label is not None):
        raise ValueError(_INVALID_DETAIL)
    inits = _INIT.findall(script)
    if len(inits) != 1 or inits[0][0] != concert_id:
        raise ValueError("안성맞춤아트홀 상세의 공연 번호가 요청과 일치하지 않습니다.")
    if not parser.titles[0]:
        raise ValueError("안성맞춤아트홀 상세의 공연명이 없습니다.")

    fields = dict.fromkeys(_FIELDS.values())
    others = []
    labels = [label for label, _ in parser.pairs]
    if len(set(labels)) != len(labels):
        raise ValueError("안성맞춤아트홀 상세의 항목이 중복되었습니다.")
    for label, value in parser.pairs:
        if label in _FIELDS:
            fields[_FIELDS[label]] = value or None
        else:
            others.append({"label": label, "value": value or None})
    flags = [f"missing:{key}" for key in _CORE if fields[key] is None]
    if others:
        flags.append("unmapped_field")
    period, problem = _period(fields["period"])
    if problem:
        flags.append(problem)
    opens_at = None
    if fields["ticket_open"] == "~":
        flags.append("ticket_open_blank")
    elif fields["ticket_open"] is not None:
        match = _TICKET_OPEN.fullmatch(fields["ticket_open"])
        try:
            opens_at = datetime.fromisoformat(f"{match[1]}T{match[2]}").isoformat(timespec="minutes")
        except (TypeError, ValueError):
            flags.append("ticket_open_unparsed")

    tabs = dict(parser.tabs)
    if len(tabs) != len(parser.tabs) or not tabs.keys() <= parser.sections.keys():
        raise ValueError(_INVALID_DETAIL)
    sections = []
    for key in sorted(parser.sections, key=int):
        section = parser.sections[key]
        if key in tabs or section["text"] or section["images"] or section["links"]:
            sections.append({"index": int(key), "title": tabs.get(key), **section})
            if key not in tabs:
                flags.append(f"untitled_section:{key}")
    if not any(section["text"] for section in sections):
        flags.append("sections_without_text")
    return {
        "external_id": concert_id,
        "official_url": url,
        "category": parser.categories[0] if parser.categories else None,
        "title": parser.titles[0],
        "fields": fields,
        "other_fields": others,
        # 기간은 공연·전시 진행 일정이고, 예매(신청) 시작은 티켓 오픈 일시에서만 읽어 따로 둔다.
        "performance_period": period,
        "ticket_open_at": opens_at,
        "booking_buttons": parser.buttons,
        "ticketing_goods_code": inits[0][2] or None,
        "poster_url": parser.posters[0] if parser.posters else None,
        "sections": sections,
        "review_flags": sorted(flags),
    }
