"""안성시 직영 공공체육시설 예약 누리집 공지의 robots.txt·목록·상세를 요청하고 읽는다. 마크업은 2026-11-29 실제 원본 기준이다(README)."""

import re
import string
from urllib.parse import parse_qsl, quote, urlsplit

from .html_tokens import PinnedHTMLParser
from .official_web import _fetch

HOST = "reservation.anseong.go.kr"
ORIGIN = f"https://{HOST}"
USER_AGENT = "yeogi-it/official-source-capture"  # official_web._fetch가 보내는 값과 같다.
ROBOTS_URL = ORIGIN + "/robots.txt"
ROBOTS_MAX_BYTES = 512 * 1024
_LISTING_PATH = "/index.do?menu_id=0008"
LISTING_URL = ORIGIN + _LISTING_PATH
PARSER_VERSION = "sports-notice-parser-v8"
# 목록의 상세 href 그대로다(`cp`의 `/`·빈 검색 인자 포함). 이 주소로 받은 상세 5건을 원본으로 확인했다.
_DETAIL_PATH = ("/index.do?menu_id=0008&cp=/board/view.do&pageIndex=1&seq={}"
                "&board_id=notice&searchCondition=&searchKeyword=")
_SEQ = re.compile(r"[1-9][0-9]{0,17}")
_ROBOTS_LINE = re.compile(r"([A-Za-z-]+)[ \t]*:((?:[ \t]|\S)*)")
_PRODUCT = USER_AGENT.split("/")[0]  # RFC 9309 그룹은 제품 토큰으로 고른다.
# 다섯 자리를 넘으면 sleep 한도를 넘을 수 있다.
_CRAWL_DELAY = re.compile(r"[0-9]{1,5}(?:\.[0-9]+)?")
_VOID_TAGS = frozenset("area base br col embed hr img input link meta source track wbr".split())
# 읽는 영역과 그 안·조상은 2026-11-29 실제 원본(목록 1쪽·상세 5건)에서 본 표기만 받는다(README).
_BODY = {"br": "", "div": "class data-hjsonver data-jsonlen id style", "font": "color face", "h1": "style",
         "img": "data-editor-image data-file-cnt src style", "p": "class data-end data-loading-node data-start style",
         "span": "lang style"}
_TITLE = {"h3": "class"}
_FIELD = {"input": "id name type value"}
_LINK = {"a": "class data-board-seq data-button href"}
_LINK_TEXT = {"em": "class"}
_ANCESTORS = {"html": "lang", "body": "class", "div": "id", "form": "action class id method", "table": "class",
              "tbody": "", "tr": "", "td": "class colspan", "ul": "class", "li": ""}
_BREAK_TAGS = frozenset("br div h1 p".split())
_COLOR = r"#[0-9a-f]{6}|rgb\([0-9]{1,3}, [0-9]{1,3}, [0-9]{1,3}\)"
# 선언 값은 본 값만 받고 색·글꼴만 본 값의 형태로 넓혔다. font의 face·color 속성도 이 표로 확인한다.
_STYLE = {name: re.compile(value) for name, value in {
    "background-color": _COLOR, "color": _COLOR, "font-family": r"[\w ,'-]+", "font-size": r"0\.8125rem|16px",
    "font-weight": "bolder", "letter-spacing": r"0\.1px|0pt", "max-width": "100%", "opacity": "1"}.items()}
# 영역 밖 메뉴·하단은 어긋난 중첩이 있어 브라우저(HTML5 in body) 복구를 따른다. 원본에 없던 복구가 일어날 표기는 거부한다.
_SCOPE = frozenset("applet caption html marquee object table td template th".split())
_FORMATTING = frozenset("a b big code em font i nobr s small strike strong tt u".split())
_BLOCK_END = frozenset("address article aside blockquote button center details dialog dir div dl fieldset figcaption "
                       "figure footer header hgroup listing main menu nav ol pre search section summary ul".split())
_CLOSES_P = _BLOCK_END - {"button"} | frozenset("dd dt form h1 h2 h3 h4 h5 h6 hr li p plaintext table xmp".split())
_HEADINGS = frozenset("h1 h2 h3 h4 h5 h6".split())
_REJECT = frozenset("dd dt frameset image math nobr optgroup rb rp rt rtc svg template".split())
# 표·select 안에서 브라우저가 요소를 옮기거나 몰래 만들고 닫는 일이 없도록 바로 위 요소별로 받을 자식을 정한다.
_CHILDREN = {name: frozenset(children.split()) for name, children in {
    "table": "caption colgroup tbody tfoot thead", "colgroup": "col", "tbody": "tr", "tfoot": "tr", "thead": "tr",
    "tr": "td th", "select": "option", "option": ""}.items()}
_CELLS = frozenset("caption col colgroup tbody td tfoot th thead tr".split())
# 강제 줄바꿈(UAX #14 BK·NL)과 U+001C~U+001F를 str.split은 공백으로 접고 그 숫자 참조는 Python이 지운다.
_UNREAD = re.compile(r"[\x00\x0b\x0c\x1c-\x1f\x85\u2028\u2029]|&#(?:0*(?:1[12]|2[89]|3[01]|823[23])(?![0-9])|"
                     r"x0*(?:[bc]|1[c-f]|202[89])(?![0-9a-f]))", re.I)
_INVALID_DETAIL = "체육시설 공지 상세 HTML 구조가 예상과 다릅니다."
_INVALID_LISTING = "체육시설 공지 목록 HTML 구조가 올바르지 않습니다."
_INVALID_BODY = "체육시설 공지 본문에 허용하지 않는 태그·속성이 있습니다."
_CONCEALED = "체육시설 공지 목록의 상세 링크나 그 조상에 허용 목록 밖 태그·속성이 있습니다."
# 원문 줄을 고르는 검색어(공백 무시). `예약:`은 실제 seq=96의 `일반(누구나) 예약: 11.30일(09:00부터) ~` 꼴이다.
KEYWORD_GROUPS = {
    "reservation_schedule": ("예약일정", "예약기간", "예약일시", "예약접수", "예약개시", "예약오픈", "예약시작",
                             "접수기간", "신청기간", "예약:"),
    "priority": ("우선",),
    "suspension": ("중단", "중지", "제한", "휴관", "폐쇄"),
}


def _seq(value: str) -> str:
    if not isinstance(value, str) or _SEQ.fullmatch(value) is None:
        raise ValueError("체육시설 공지 번호(seq)는 18자리 이하의 양의 ASCII 정수여야 합니다.")
    return value


def _detail_path(seq: str) -> str:
    return _DETAIL_PATH.format(_seq(seq))


def detail_url(seq: str) -> str:
    return ORIGIN + _detail_path(seq)


def fetch_robots() -> bytes:
    return _fetch("GET", "/robots.txt", None, ROBOTS_MAX_BYTES, host=HOST, source="체육시설 robots.txt")


def fetch_listing(*, limit: int) -> bytes:
    return _fetch("GET", _LISTING_PATH, None, limit, host=HOST, source="체육시설 공지 목록")


def fetch_detail(seq: str, *, limit: int) -> bytes:
    return _fetch("GET", _detail_path(seq), None, limit, host=HOST, source="체육시설 공지 상세")


def robots_rules(raw: bytes) -> dict:
    """RFC 9309대로 적용할 규칙과 Crawl-delay를 읽는다. robotparser는 3.13·3.14마다 결과가 달라 쓰지 않는다."""
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ValueError("체육시설 robots.txt를 UTF-8로 읽을 수 없습니다.") from None
    # RFC 9309의 줄 끝은 CR·LF, 공백은 SP·HTAB뿐이다.
    lines = [line.split("#", 1)[0].strip(" \t") for line in re.split(r"\r\n?|\n", text)]
    groups: list[tuple[set[str], list[tuple[str, str]]]] = []
    for line in filter(None, lines):
        match = _ROBOTS_LINE.fullmatch(line)
        if match is None:
            raise ValueError("체육시설 robots.txt에 규칙이 아닌 줄이 있어 허용 여부를 확정할 수 없습니다.")
        key, value = match[1].lower(), match[2].strip()
        if key == "user-agent":
            # `yeogi-it, x`·`* all`은 허용 쪽으로 잘못 판정된다.
            token = re.match(r"\*|[A-Za-z_-]*", value)[0].lower()
            if token in ("*", _PRODUCT) and value.split("/", 1)[0].strip().lower() != token:
                raise ValueError("체육시설 robots.txt의 User-agent 값을 확정할 수 없습니다.")
            # Allow·Disallow 뒤에 나온 user-agent 줄만 새 그룹을 연다. Crawl-delay는 RFC 9309의 규칙이 아니다.
            if not groups or any(k != "crawl-delay" for k, _ in groups[-1][1]):
                groups.append((set(), []))
            groups[-1][0].add(value.split("/", 1)[0].strip().lower())
        elif key in ("allow", "disallow", "crawl-delay") and groups:
            groups[-1][1].append((key, value))
        elif groups and re.match(r"allow|dis|diasl", key):
            # 오타(`Disalow` 등)를 건너뛰면 막힌 주소를 허용한다.
            raise ValueError("체육시설 robots.txt에 확정할 수 없는 Allow·Disallow 줄이 있습니다.")
    if any(lines) and not groups:
        raise ValueError("체육시설 robots.txt에 User-agent 줄이 없어 허용 여부를 확정할 수 없습니다.")
    # 이름이 맞는 그룹이 없을 때만 `*` 그룹을 따르고, 맞는 그룹이 여럿이면 규칙을 합친다.
    chosen = [rules for agents, rules in groups if _PRODUCT in agents] or [
        rules for agents, rules in groups if "*" in agents]
    rules = [rule for group in chosen for rule in group]
    if any(key != "crawl-delay" and value and value[0] not in "/*" for key, value in rules):
        raise ValueError("체육시설 robots.txt의 Allow·Disallow 값이 경로 형식이 아닙니다.")
    delays = [value for key, value in rules if key == "crawl-delay"]
    if any(_CRAWL_DELAY.fullmatch(value) is None for value in delays):
        raise ValueError("체육시설 robots.txt의 Crawl-delay를 읽을 수 없어 요청 간격을 확정할 수 없습니다.")
    return {"rules": [(key == "allow", value) for key, value in rules if key != "crawl-delay" and value],
            "delay": max(map(float, delays), default=0.0)}


def _matches(pattern: str, path: str) -> bool:
    """`*`는 아무 글자열, 끝의 `$`는 주소 끝이다. 정규식 역추적 없이 조각을 왼쪽부터 찾는다."""
    anchored = pattern.endswith("$")
    first, *rest = (pattern[:-1] if anchored else pattern).split("*")
    if not path.startswith(first):
        return False
    position = len(first)
    for index, part in enumerate(rest):
        if anchored and index == len(rest) - 1:
            return path.endswith(part) and len(path) - len(part) >= position
        position = path.find(part, position)
        if position < 0:
            return False
        position += len(part)
    return not anchored or position == len(path)


def _verdict(rules: list[tuple[bool, str]], path: str) -> bool:
    return max(((len(pattern), allow) for allow, pattern in rules if _matches(pattern, path)), default=(0, True))[1]


def _decode(value: str, plain) -> str:
    """비ASCII는 인코딩하고 `plain` 글자만 풀며 남은 `%XX`는 대문자로 맞춘다."""
    return re.sub("%[0-9A-Fa-f]{2}", lambda m: c if (c := chr(int(m[0][1:], 16))) in plain else m[0].upper(),
                  quote(value, safe=string.punctuation))


def allowed(rules: dict, url: str) -> bool:
    """가장 긴 일치, 같은 길이면 Allow. RFC 9309대로 비예약 글자만 풀고(`%2A`·`%24`는 글자), `*`·`$` 밖을 다 풀어 막혀도 막힌다."""
    parts = urlsplit(url)
    path = parts.path + ("?" + parts.query if parts.query else "")
    return all(_verdict([(allow, _decode(pattern, plain)) for allow, pattern in rules["rules"]], _decode(path, plain))
               for plain in (string.ascii_letters + string.digits + "-._~", set(map(chr, range(128))) - set("*$")))


def _allowed(rules: dict, tag: str, attrs) -> list | None:
    """태그·속성·인라인 스타일이 모두 허용 목록 안이면 선언 (이름, 값) 목록을, 아니면 None을 돌려준다."""
    names = [name for name, _ in attrs]
    # 속성이 중복되면 브라우저는 첫 값을, 이 파서는 마지막 값을 쓴다. CSS 주석·이스케이프는 선언 경계와 이름을 바꾼다.
    # font의 face·color 속성은 같은 뜻의 선언으로 바꿔 함께 확인한다. style 속성은 본문 요소에만 허용한다.
    style = (dict(attrs).get("style") or "") + "".join(
        f";{'font-family' if name == 'face' else name}:{value}" for name, value in attrs if tag == "font")
    if tag not in rules or len(set(names)) < len(names) or not set(names) <= set(rules[tag].split()) or (
            "/*" in style or "\\" in style):
        return None
    pairs = [(name.strip().lower(), " ".join(value.lower().split()))
             for name, _, value in (part.partition(":") for part in style.split(";") if part.strip())]
    return pairs if all(name in _STYLE and _STYLE[name].fullmatch(value) for name, value in pairs) else None


def _feed(parser: PinnedHTMLParser, text: str) -> None:
    if _UNREAD.search(text):
        raise parser.markup_error()
    try:
        parser.feed(text)
        parser.close()
    except AssertionError:
        raise parser.markup_error() from None
    if parser.stack:
        raise parser.markup_error()


class _Parser(PinnedHTMLParser):
    """영역 안의 종료 태그는 가장 안쪽의 열린 요소를 닫아야 하고 문서 끝에 열린 요소가 없어야 한다.

    영역 밖은 브라우저처럼 복구한 이 스택으로 영역 끝과 조상을 정한다. 복구로 브라우저와 스택이 갈릴 수 있는 표기는 거부한다.
    """
    message = _INVALID_DETAIL

    def __init__(self):
        super().__init__()
        # (태그, 읽는 영역, 플래그). 플래그는 영역 밖에서는 조상 허용 여부, 본문에서는 줄을 끊는지다.
        self.stack: list[tuple[str, str | None, bool]] = []
        self.form = None  # 브라우저의 form 요소 포인터

    def markup_error(self):
        return ValueError(self.message)

    @property
    def region(self) -> str | None:
        return self.stack[-1][1] if self.stack else None

    def parse_endtag(self, i):
        # 실제 원본 빠른 메뉴의 `</br>`. 브라우저는 `<br>`로 읽어 영역 밖 스택은 그대로다.
        if self.region is None and self.rawdata.startswith("</br>", i):
            return i + 5
        return super().parse_endtag(i)

    def _in_scope(self, tag, extra=()) -> int | None:
        for index in reversed(range(len(self.stack))):
            if self.stack[index][0] == tag:
                return index
            if self.stack[index][0] in _SCOPE or self.stack[index][0] in extra:
                return None
        return None

    def handle_starttag(self, tag, attrs):
        super().handle_starttag(tag, attrs)
        # 브라우저는 뒤에 나온 html·body 태그의 속성도 그 요소에 더하고, frameset 뒤의 본문은 보이지 않는다.
        if tag in ("html", "body", "frameset") and _allowed(_ANCESTORS, tag, attrs) is None:
            raise self.markup_error()
        if self.region is None:
            names = [entry[0] for entry in self.stack]
            if tag in ("html", "body") and tag in names or tag == "form" and self.form is not None:
                return  # 브라우저가 버리는 시작 태그다(실제 상세의 댓글 form).
            if tag == "li" and names[-1:] == ["li"]:
                del self.stack[-1], names[-1]  # 실제 메뉴처럼 닫지 않은 li는 다음 li가 닫는다.
            top = names[-1] if names else None
            if (tag in _REJECT or (top in _CHILDREN or tag in _CELLS) and tag not in _CHILDREN.get(top, ())
                    or tag in _CLOSES_P and self._in_scope("p", ("button",)) is not None
                    or tag == "li" and top not in ("ol", "ul") or tag in _HEADINGS and top in _HEADINGS
                    or tag in ("a", "button") and tag in names or tag in ("body", "head") and names != ["html"]):
                raise self.markup_error()
        entry = (tag, *self.start(tag, attrs, self.region))
        if tag not in _VOID_TAGS:
            self.stack.append(entry)
            if tag == "form":
                self.form = entry

    def handle_endtag(self, tag):
        names = [entry[0] for entry in self.stack]
        if names[-1:] == [tag]:
            if tag == "form":
                self.form = None
            self.end(*self.stack.pop())
        elif self.region is not None:
            raise self.markup_error()
        elif tag == "form":
            # 브라우저는 form만 스택에서 빼고 안쪽 요소는 열어 둔다(실제 상세의 댓글 영역). 숨김 form이면 조상이 사라져 거부한다.
            node, self.form, index = self.form, None, self._in_scope("form")
            if node is not None and index is not None and self.stack[index] is node:
                if not node[2] or names[-1] in ("li", "option", "p"):
                    raise self.markup_error()
                del self.stack[index]
        elif tag == "li" or tag in _BLOCK_END:
            # 실제 메뉴의 남는 `</li>`(범위 밖)는 버리고 `</nav>`는 안쪽 li·ul까지 닫는다.
            index = self._in_scope(tag, ("ol", "ul") if tag == "li" else ())
            if index is not None:
                # 브라우저는 함께 닫힌 서식 요소를 뒤에서 다시 열어 거부한다.
                if _FORMATTING.intersection(names[index:]):
                    raise self.markup_error()
                del self.stack[index:]
        elif tag in names or tag in _HEADINGS and _HEADINGS.intersection(names):
            raise self.markup_error()
        # 그 밖에 열려 있지 않은 요소의 종료 태그는 브라우저도 버린다.

    def enter(self, rules, tag, attrs, error) -> list:
        """읽는 영역을 여는 요소와 그 조상이 모두 허용 목록 안이어야 한다."""
        pairs = _allowed(rules, tag, attrs)
        if pairs is None or not all(ok for _, _, ok in self.stack):
            raise ValueError(error)
        return pairs

    def end(self, tag, region, flag):
        pass


class _LinkParser(_Parser):
    message = _INVALID_LISTING

    def __init__(self):
        super().__init__()
        self.ids: list[str] = []

    def start(self, tag, attrs, region):
        if region:
            if _allowed(_LINK_TEXT, tag, attrs) is None:
                raise ValueError(_CONCEALED)
            return region, False
        values = dict(attrs)
        if tag == "a" and [name for name, _ in attrs].count("href") > 1:
            raise ValueError("체육시설 공지 목록 링크의 href가 중복되었습니다.")
        seq = _listed_seq(values["href"]) if tag == "a" and values.get("href") else None
        if not seq:
            return None, _allowed(_ANCESTORS, tag, attrs) is not None
        self.enter(_LINK, tag, attrs, _CONCEALED)
        if seq in self.ids:
            raise ValueError("체육시설 공지 목록에 같은 공지 번호가 있습니다.")
        self.ids.append(seq)
        return "link", False


def _listed_seq(href: str) -> str | None:
    """이 호스트 `index.do`의 seq 링크 번호. 상세 형식이 아닌 seq 링크는 형식 변경이다."""
    try:
        parts = urlsplit(href.strip())
    except ValueError:  # 깨진 주소(IPv6 호스트 등)는 이 호스트의 공지 링크가 아니다.
        return None
    if (parts.scheme not in ("", "http", "https") or parts.netloc not in ("", HOST)
            or parts.path not in ("index.do", "/index.do", "./index.do")):
        return None
    seq = dict(parse_qsl(parts.query, keep_blank_values=True)).get("seq")
    if seq is None:
        return None
    if _SEQ.fullmatch(seq) is None or href != _DETAIL_PATH.format(seq):
        raise ValueError("체육시설 공지 목록의 상세 링크 형식이 예상과 다릅니다.")
    return seq


def parse_listing(raw: bytes) -> list[str]:
    """목록 1쪽의 공지 번호(문서 순서). 링크와 그 안·조상의 허용 목록 밖 표기는 숨김일 수 있어 거부한다."""
    try:
        text = raw.decode("utf-8-sig")
    except (AttributeError, UnicodeDecodeError):
        raise ValueError("체육시설 공지 목록은 UTF-8이어야 합니다.") from None
    parser = _LinkParser()
    _feed(parser, text)
    if not parser.ids:
        raise ValueError("체육시설 공지 목록에서 공지 상세 링크를 찾지 못했습니다.")
    return parser.ids


class _DetailParser(_Parser):
    def __init__(self):
        super().__init__()
        self.seqs: list[str | None] = []
        self.titles: list[str] = []
        self.title: list[str] = []
        self.bodies = 0
        self.text: list[str] = []
        self.images: list[dict] = []

    def start(self, tag, attrs, region):
        values = dict(attrs)
        classes = (values.get("class") or "").split()
        if region == "title":
            raise ValueError(_INVALID_DETAIL)
        if region == "body":
            # 브라우저가 시작 태그로 열린 요소를 닫는 표기는 실제 원본에 없다.
            if (_allowed(_BODY, tag, attrs) is None or tag in _BREAK_TAGS - {"br"} and "p" in [e[0] for e in self.stack]
                    or tag == self.stack[-1][0] == "h1"):
                raise ValueError(_INVALID_BODY)
            return region, self._body_start(tag, values)
        if tag == "input" and values.get("name") == "seq":
            if _allowed(_FIELD, tag, attrs) is None:
                raise ValueError(_INVALID_DETAIL)
            self.seqs.append(values.get("value"))
        elif tag == "h3" and "bbsTitle" in classes:
            self.enter(_TITLE, tag, attrs, _INVALID_DETAIL)
            self.title = []
            return "title", False
        elif tag == "div" and "conts" in classes:
            self.bodies += 1
            self.enter(_BODY, tag, attrs, _INVALID_BODY)
            return "body", self._body_start(tag, values)
        return None, _allowed(_ANCESTORS, tag, attrs) is not None

    def _body_start(self, tag, values) -> bool:
        if tag in _BREAK_TAGS:
            self.text.append("\n")
        if tag == "img":
            self.images.append({"src": values.get("src")})
        return tag in _BREAK_TAGS

    def end(self, tag, region, breaks):
        if region == "title":
            self.titles.append(" ".join("".join(self.title).split()))
        elif region == "body":
            if breaks:
                self.text.append("\n")

    def handle_data(self, data):
        super().handle_data(data)
        if self.region == "body":
            # 브라우저는 소스 줄바꿈을 공백으로 보이지만 외부 CSS가 살릴 수 있어 `\r`로 남겨 합친 사실을 표시한다.
            self.text.append(data.replace("\r\n", "\r").replace("\n", "\r"))
        elif self.region == "title":
            self.title.append(data)


def _lines(text: str) -> list[str]:
    return [line for line in (" ".join(part.split()) for part in text.split("\n")) if line]


def parse_detail(text: str, *, seq: str) -> dict:
    """제목·본문 줄·이미지를 표시 문구 그대로 보관한다. 일정·자격·비용·중단 여부는 판정하지 않는다."""
    url = detail_url(seq)
    parser = _DetailParser()
    _feed(parser, text)
    if parser.seqs != [seq]:
        raise ValueError("체육시설 공지 상세의 공지 번호(seq)가 요청과 일치하지 않습니다.")
    if len(parser.titles) != 1 or not parser.titles[0]:
        raise ValueError("체육시설 공지 상세의 제목을 하나로 확정할 수 없습니다.")
    if parser.bodies != 1:
        raise ValueError("체육시설 공지 상세의 본문 영역을 하나로 확정할 수 없습니다.")
    shown = "".join(parser.text)
    lines = _lines(shown.replace("\r", " "))
    if not lines and not parser.images:
        raise ValueError("체육시설 공지 상세에 본문 글자와 이미지가 없습니다.")

    title = parser.titles[0]
    compact = [(line, "".join(line.split())) for line in (title, *lines)]
    flags = set()
    if parser.images:
        flags.add("inline_image")
        if not lines:
            flags.add("image_only")
    if lines != _lines(shown.replace("\r", "\n")) or [title] != _lines("".join(parser.title).replace("\r", "\n")):
        flags.add("source_newline_joined")
    return {
        "external_id": seq,
        "official_url": url,
        "title": title,
        "body_lines": lines,
        "images": parser.images,
        "keyword_lines": {key: [line for line, packed in compact if any(word in packed for word in words)]
                          for key, words in KEYWORD_GROUPS.items()},
        "review_flags": sorted(flags),
    }
