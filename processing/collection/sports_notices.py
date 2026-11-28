"""안성시 직영 공공체육시설 예약 누리집 공지의 robots.txt·목록·상세를 요청하고 읽는다.

robots.txt가 HTTP 400이라 실제 목록·상세는 받지 않았다. 상세 주소 형식만 조사 기록에서 옮겼고 마크업은 가정이다.
"""

import re
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit

from .html_tokens import PinnedHTMLParser
from .official_web import _fetch

HOST = "reservation.anseong.go.kr"
ORIGIN = f"https://{HOST}"
USER_AGENT = "yeogi-it/official-source-capture"  # official_web._fetch가 보내는 값과 같다.
ROBOTS_URL = ORIGIN + "/robots.txt"
ROBOTS_MAX_BYTES = 512 * 1024
_LISTING_PATH = "/index.do?menu_id=0008"
LISTING_URL = ORIGIN + _LISTING_PATH
PARSER_VERSION = "sports-notice-parser-v6"
_DETAIL_QUERY = {"board_id": "notice", "cp": "/board/view.do", "menu_id": "0008", "pageIndex": "1"}
_SEQ = re.compile(r"[1-9][0-9]{0,17}")
_ROBOTS_LINE = re.compile(r"([A-Za-z-]+)[ \t]*:(.*)")
_PRODUCT = USER_AGENT.split("/")[0]  # RFC 9309 그룹은 제품 토큰으로 고른다.
# 다섯 자리를 넘는 값은 sleep 한도를 넘을 수 있어 읽지 않는다.
_CRAWL_DELAY = re.compile(r"[0-9]{1,5}(?:\.[0-9]+)?")
_VOID_TAGS = frozenset("area base br col embed hr img input link meta source track wbr".split())
# 읽는 영역(목록의 상세 링크, 상세의 h4·div.view_cont, seq 입력)과 그 안·조상은 아래 허용 목록만 받는다. 이 호스트
# 원본이 없어 안성시 누리집 실제 원본(README 참고)에서 쓰인 표기만 옮겼다.
_BODY = {"a": "href style target title", "br": "style", "div": "class data-hjsonver data-jsonlen id style", "h1": "",
         "h2": "", "h3": "", "img": "alt height src style width", "li": "", "p": "class data-pm-slice style",
         "span": "lang style", "strong": "style", "u": "", "ul": ""}
_TITLE = {"h4": ""}  # 실제 제목 h4에는 속성도, 안의 태그도 없었다.
_FIELD = {"input": "id name type value"}
_LINK = {"a": "href onclick"}
_LINK_TEXT = {"b": "", "span": "class"}
_ANCESTORS = {"html": "lang", "body": "class", "div": "class id style", "section": "id", "form": "action id method name",
              "table": "class", "tbody": "", "tr": "", "td": "class"}
_BREAK_TAGS = frozenset("br div h1 h2 h3 li p ul".split())
_HEX = "#[0-9a-f]{6}"
# 선언 값은 본 값만 받는다. 글자색·배경색·글꼴·테두리만 본 값의 형태(16진수 색 등)로 넓혔다.
_STYLE = {name: re.compile("|".join(map(re.escape, values.split("|")))) for names, values in {
    "-ms-word-break word-break": "keep-all", "-webkit-text-stroke-width word-spacing": "0px",
    "align-items justify-content text-align": "center", "box-sizing": "border-box", "cursor": "pointer",
    "border-radius": "0 0 10px 10px|10px|10px 10px 0 0|12px|14px|16px|18px|20px|4px|6px|8px",
    "display": "block|flex|inline !important|inline-block", "float mso-pagination text-autospace text-transform": "none",
    "font-feature-settings font-kerning font-language-override font-optical-sizing font-size-adjust font-stretch "
    "font-variant-alternates font-variant-east-asian font-variant-emoji font-variant-numeric font-variant-position "
    "font-variation-settings": "inherit",
    "font-size": "14pt|15.0pt|15px|16.0pt|16.15px|16px|17.0526px|17.05px|17px|18.0pt|18pt|18px|19px|20.0pt|20px|21px|"
                 "22px|23px|24px|26px|27px|5.0pt",
    "font-style font-variant-caps font-variant-ligatures white-space": "normal", "font-weight": "400|bold|normal",
    "height": "50px", "letter-spacing": "-0.3pt|-0.3px|-0.54px|-0.57px|-0.5px|-0.6pt|-0.7pt|-1.4pt|0pt|normal",
    "line-height": "1.3|1.35|1.4|1.5|1.6|1.8|120%|140%|21px|24.23px|25.57px", "margin": "0 6px|0 auto|0px|4px 0",
    "margin-bottom": "10px|12px|14px|16px|18px|22px|2px|4px|6px|8px", "margin-left": "29.1pt|31.4pt|31.9pt|32.8pt|auto",
    "margin-right": "6px|8px|auto", "margin-top": "10px|2.0pt|2px|4px|6px|8px", "max-width": "720px|760px|780px|800px",
    "mso-font-width": "100%|90%", "mso-padding-alt": "0pt 0pt 0pt 0pt", "mso-text-raise": "0pt",
    "opacity": "0.95", "orphans widows": "2", "overflow": "hidden",
    "padding": "0 4px|0px|10px 12px|10px 14px|10px 16px|10px 4px|10px 4px 4px 4px|10px 6px|12px|12px 14px|12px 15px|"
               "12px 16px|14px|14px 16px|14px 18px|16px 18px|16px 20px|18px|18px 16px|18px 20px|20px 16px|22px 16px|"
               "24px 18px|24px 20px|26px 22px|2px 10px|2px 12px|2px 8px|3px 0|3px 14px|3px 9px|4px 0|4px 12px|"
               "4px 14px|4px 16px|5px 0|6px 18px|8px 12px",
    "padding-bottom": "6px|8px", "padding-left": "10px|12px|14px|4px|58px|66px|6px", "padding-top": "10px|8px",
    "text-decoration-color text-decoration-style text-decoration-thickness": "initial",
    "text-indent": "-29.1pt|-31.4pt|-31.9pt|-32.8pt|0px", "vertical-align": "baseline", "width": "350px",
}.items() for name in names.split()} | {name: re.compile(shape) for names, shape in {
    "color": f"{_HEX}|white", "background-color": rf"{_HEX}|rgba\(255, 255, 255, 0\.2\)|rgba\(0, 0, 0, 0\.15\)",
    "font-family mso-ascii-font-family mso-fareast-font-family mso-hansi-font-family": r"[\w ,'-]+",
    "border border-bottom border-left border-top": rf"[1-5]px (?:solid|dashed) {_HEX}|0px(?: currentcolor)?|none",
}.items() for name in names.split()}
# 브라우저가 강제 줄바꿈으로 보이는 문자(UAX #14 BK·NL)를 str.split은 공백으로 접고 `&#11;`은 Python이 지운다.
_UNREAD = re.compile(r"[\x00\x0b\x0c\x85\u2028\u2029]|&#(?:0*(?:1[12]|823[23])(?![0-9])|x0*(?:[bc]|202[89])(?![0-9a-f]))", re.I)
_INVALID_DETAIL = "체육시설 공지 상세 HTML 구조가 예상과 다릅니다."
_INVALID_LISTING = "체육시설 공지 목록 HTML 구조가 올바르지 않습니다."
_INVALID_BODY = "체육시설 공지 본문에 허용하지 않는 태그·속성이 있습니다."
_CONCEALED = "체육시설 공지 목록의 상세 링크나 그 조상에 허용 목록 밖 태그·속성이 있습니다."
# 원문 줄을 고르는 검색어(공백 무시). 줄을 해석하지 않고 옮기는 색인이며, 고르지 못한 줄도 body_lines에 남는다.
KEYWORD_GROUPS = {
    "reservation_schedule": ("예약일정", "예약기간", "예약일시", "예약접수", "예약개시", "예약오픈", "예약시작",
                             "접수기간", "신청기간"),
    "priority": ("우선",),
    "suspension": ("중단", "중지", "제한", "휴관", "폐쇄"),
}


def _seq(value: str) -> str:
    if not isinstance(value, str) or _SEQ.fullmatch(value) is None:
        raise ValueError("체육시설 공지 번호(seq)는 18자리 이하의 양의 ASCII 정수여야 합니다.")
    return value


def _detail_path(seq: str) -> str:
    # urlencode는 `/`를 `%2F`로 바꾸므로 조사 기록의 실제 주소(cp=%2Fboard%2Fview.do)와 같은 문자열이 된다.
    return "/index.do?" + urlencode({**_DETAIL_QUERY, "seq": _seq(seq)})


def detail_url(seq: str) -> str:
    return ORIGIN + _detail_path(seq)


def fetch_robots() -> bytes:
    return _fetch("GET", "/robots.txt", None, ROBOTS_MAX_BYTES, host=HOST, source="체육시설 robots.txt")


def fetch_listing(*, limit: int) -> bytes:
    return _fetch("GET", _LISTING_PATH, None, limit, host=HOST, source="체육시설 공지 목록")


def fetch_detail(seq: str, *, limit: int) -> bytes:
    return _fetch("GET", _detail_path(seq), None, limit, host=HOST, source="체육시설 공지 상세")


def robots_rules(raw: bytes) -> dict:
    """HTTP 200으로 받은 robots.txt를 RFC 9309대로 읽어 이 수집기에 적용할 규칙과 Crawl-delay를 돌려준다.

    표준 라이브러리 robotparser는 판(3.13·3.14)마다 최장 일치·와일드카드·그룹 병합·제품 토큰 비교가 달라 쓰지 않는다.
    """
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ValueError("체육시설 robots.txt를 UTF-8로 읽을 수 없습니다.") from None
    # RFC 9309의 줄 끝은 CR·LF, 공백은 SP·HTAB뿐이다. 주석 밖의 다른 공백 문자는 값을 바꿀 수 있어 멈춘다.
    lines = [line.split("#", 1)[0].strip(" \t") for line in re.split(r"\r\n?|\n", text)]
    if re.search(r"[^\S \t]", "".join(lines)):
        raise ValueError("체육시설 robots.txt에 SP·HTAB 밖의 공백 문자가 있어 허용 여부를 확정할 수 없습니다.")
    groups: list[tuple[set[str], list[tuple[str, str]]]] = []
    for line in filter(None, lines):
        match = _ROBOTS_LINE.fullmatch(line)
        if match is None:
            raise ValueError("체육시설 robots.txt에 규칙이 아닌 줄이 있어 허용 여부를 확정할 수 없습니다.")
        key, value = match[1].lower(), match[2].strip()
        if key == "user-agent":
            # Allow·Disallow 뒤에 나온 user-agent 줄만 새 그룹을 연다. Crawl-delay는 RFC 9309의 규칙이 아니다.
            if not groups or any(k != "crawl-delay" for k, _ in groups[-1][1]):
                groups.append((set(), []))
            groups[-1][0].add(value.split("/", 1)[0].strip().lower())
        elif key in ("allow", "disallow", "crawl-delay") and groups:
            groups[-1][1].append((key, value))
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


def allowed(rules: dict, url: str) -> bool:
    """가장 긴 일치 규칙을 따르고 길이가 같으면 Allow를 쓴다. 퍼센트 인코딩을 푼 주소·규칙에서 막혀도 막힌 것으로 본다."""
    parts = urlsplit(url)
    path = parts.path + ("?" + parts.query if parts.query else "")
    decoded = [(allow, unquote(pattern)) for allow, pattern in rules["rules"]]
    return _verdict(rules["rules"], path) and _verdict(decoded, unquote(path))


def _allowed(rules: dict, tag: str, attrs) -> list | None:
    """태그·속성 이름·인라인 스타일 선언이 모두 허용 목록 안이면 선언 (이름, 값) 목록을, 아니면 None을 돌려준다."""
    names = [name for name, _ in attrs]
    # 속성이 중복되면 브라우저는 첫 값을, 이 파서는 마지막 값을 쓴다. CSS 주석·이스케이프는 선언 경계와 이름을 바꾼다.
    style = dict(attrs).get("style") or ""
    if tag not in rules or len(set(names)) < len(names) or not set(names) <= set(rules[tag].split()) or (
            "/*" in style or "\\" in style):
        return None
    pairs = [(name.strip().lower(), " ".join(value.lower().split()))
             for name, _, value in (part.partition(":") for part in style.split(";") if part.strip())]
    styles = _STYLE if rules is _BODY else {}  # 조상의 style은 실제 원본에서 늘 비어 있었다.
    return pairs if all(name in styles and styles[name].fullmatch(value) for name, value in pairs) else None


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
    """종료 태그는 문서 어디서든 가장 안쪽의 열린 요소를 닫아야 하고, 문서 끝에 열린 요소가 없어야 한다.

    이 스택으로 읽는 영역의 끝과 조상을 정한다. 실제 원본은 모두 이 조건을 지켰다.
    """
    message = _INVALID_DETAIL

    def __init__(self):
        super().__init__()
        # (태그, 읽는 영역, 플래그). 플래그는 영역 밖에서는 조상 허용 여부, 본문에서는 줄을 끊는지다.
        self.stack: list[tuple[str, str | None, bool]] = []

    def markup_error(self):
        return ValueError(self.message)

    @property
    def region(self) -> str | None:
        return self.stack[-1][1] if self.stack else None

    def handle_starttag(self, tag, attrs):
        super().handle_starttag(tag, attrs)
        # 브라우저는 뒤에 나온 html·body 태그의 속성도 그 요소에 더하고, frameset 뒤의 본문은 보이지 않는다.
        if tag in ("html", "body", "frameset") and _allowed(_ANCESTORS, tag, attrs) is None:
            raise self.markup_error()
        entry = self.start(tag, attrs, self.region)
        if tag not in _VOID_TAGS:
            self.stack.append((tag, *entry))

    def handle_endtag(self, tag):
        if not self.stack or self.stack[-1][0] != tag:
            raise self.markup_error()
        self.end(*self.stack.pop())

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
    """이 호스트 `index.do`의 seq 링크면 번호를 돌려준다. seq가 있는데 공지 상세 형식이 아니면 형식 변경으로 본다."""
    try:
        parts = urlsplit(href.strip())
    except ValueError:  # 주소로 읽을 수 없는 링크(예: 깨진 IPv6 호스트)는 이 호스트의 공지 링크가 아니다.
        return None
    if (parts.scheme not in ("", "http", "https") or parts.netloc not in ("", HOST)
            or parts.path not in ("index.do", "/index.do", "./index.do")):
        return None
    pairs = parse_qsl(parts.query, keep_blank_values=True)
    values = dict(pairs)
    if "seq" not in values:
        return None
    seq = values.pop("seq")
    if len(pairs) != 5 or values != _DETAIL_QUERY or parts.fragment or _SEQ.fullmatch(seq) is None:
        raise ValueError("체육시설 공지 목록의 상세 링크 형식이 예상과 다릅니다.")
    return seq


def parse_listing(raw: bytes) -> list[str]:
    """목록 1쪽의 공지 번호를 문서 순서대로 돌려준다. 고정 글·전체 페이지 수는 표시 형식을 몰라 읽지 않는다.

    상세 링크와 그 안·조상에 허용 목록 밖 표기(숨김 속성·스타일, template 등)가 있으면 화면에 없을 수 있어 거부한다.
    """
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
        self.links: list[dict] = []
        self.link: dict | None = None

    def start(self, tag, attrs, region):
        values = dict(attrs)
        if region == "title":
            raise ValueError(_INVALID_DETAIL)
        if region == "body":
            pairs, top, opened = _allowed(_BODY, tag, attrs), self.stack[-1][0], {entry[0] for entry in self.stack}
            # 브라우저가 시작 태그로 열린 요소를 닫는 표기는 실제 원본에 없다.
            if pairs is None or tag == "a" and "a" in opened or tag in _BREAK_TAGS - {"br"} and "p" in opened or (
                    tag == "li" and top != "ul") or {tag, top} <= {"h1", "h2", "h3"}:
                raise ValueError(_INVALID_BODY)
            return region, self._body_start(tag, values, pairs)
        if tag == "input" and values.get("name") == "seq":
            if _allowed(_FIELD, tag, attrs) is None:
                raise ValueError(_INVALID_DETAIL)
            self.seqs.append(values.get("value"))
        elif tag == "h4":
            self.enter(_TITLE, tag, attrs, _INVALID_DETAIL)
            self.title = []
            return "title", False
        elif tag == "div" and "view_cont" in (values.get("class") or "").split():
            self.bodies += 1
            return "body", self._body_start(tag, values, self.enter(_BODY, tag, attrs, _INVALID_BODY))
        return None, _allowed(_ANCESTORS, tag, attrs) is not None

    def _body_start(self, tag, values, pairs) -> bool:
        # inline-block·block·flex 상자는 너비·내용과 무관하게 앞뒤를 끊는다(과분할될 수 있다).
        breaks = tag in _BREAK_TAGS or any(name == "display" and value != "inline !important" for name, value in pairs)
        if breaks:
            self.text.append("\n")
        if tag == "img":
            self.images.append({"src": values.get("src"), "alt": values.get("alt")})
        if tag == "a":
            self.link = {"href": values["href"], "text": []} if values.get("href") else None
        return breaks

    def end(self, tag, region, breaks):
        if region == "title":
            self.titles.append(" ".join("".join(self.title).split()))
        elif region == "body":
            if breaks:
                self.text.append("\n")
            if tag == "a" and self.link is not None:
                self.links.append({"href": self.link["href"], "text": " ".join("".join(self.link["text"]).split())})
                self.link = None

    def handle_data(self, data):
        super().handle_data(data)
        if self.region == "body":
            # 브라우저는 소스 줄바꿈을 공백으로 보이지만 외부 CSS가 살릴 수 있어 `\r`로 남겨 합친 사실을 표시한다.
            self.text.append(data.replace("\r\n", "\r").replace("\n", "\r"))
            if self.link is not None:
                self.link["text"].append(data)
        elif self.region == "title":
            self.title.append(data)


def _lines(text: str) -> list[str]:
    return [line for line in (" ".join(part.split()) for part in text.split("\n")) if line]


def parse_detail(text: str, *, seq: str) -> dict:
    """제목·본문 줄·이미지·링크를 표시 문구 그대로 보관한다. 일정·자격·비용·중단 여부는 판정하지 않는다."""
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
    # 실제 마크업을 확인하기 전까지 모든 기록은 사람 확인 대상이다.
    flags = {"markup_unverified"}
    if parser.images:
        flags.add("inline_image")
        if not lines:
            flags.add("image_only")
    if parser.links:
        flags.add("link")
    if lines != _lines(shown.replace("\r", "\n")):
        flags.add("source_newline_joined")  # 외부 CSS가 white-space:pre-wrap 등이면 화면에서는 줄이 나뉜다.
    return {
        "external_id": seq,
        "official_url": url,
        "title": title,
        "body_lines": lines,
        "images": parser.images,
        "links": parser.links,
        "keyword_lines": {key: [line for line, packed in compact if any(word in packed for word in words)]
                          for key, words in KEYWORD_GROUPS.items()},
        "review_flags": sorted(flags),
    }
