"""안성시 직영 공공체육시설 예약 누리집 공지의 robots.txt·목록·상세를 요청하고 읽는다.

이 호스트의 robots.txt는 2026-11-27·28 모두 HTTP 400(`Request Blocked`)이어서 실제 목록·상세 HTML을 받지 않았다.
상세 주소 형식만 조사 기록의 실제 주소에서 옮겼고, 상세 마크업(`input[name=seq]`·`h4`·`div.view_cont`)은 합성 원본의
가정이다. 실제 응답이 다르면 원본과 실패 사유를 남기고 멈춘다.
"""

from html.parser import HTMLParser
import re
from urllib.parse import parse_qsl, urlencode, urlsplit
from urllib.robotparser import RobotFileParser

from .official_web import _fetch

HOST = "reservation.anseong.go.kr"
ORIGIN = f"https://{HOST}"
USER_AGENT = "yeogi-it/official-source-capture"  # official_web._fetch가 보내는 값과 같다.
ROBOTS_URL = ORIGIN + "/robots.txt"
ROBOTS_MAX_BYTES = 512 * 1024
_LISTING_PATH = "/index.do?menu_id=0008"
LISTING_URL = ORIGIN + _LISTING_PATH
PARSER_VERSION = "sports-notice-parser-v1"
_DETAIL_QUERY = {"board_id": "notice", "cp": "/board/view.do", "menu_id": "0008", "pageIndex": "1"}
_SEQ = re.compile(r"[1-9][0-9]{0,17}")
_ROBOTS_LINE = re.compile(r"[A-Za-z-]+[ \t]*:.*")
_HIDDEN_TAGS = ("template", "noscript")
_VOID_TAGS = frozenset("area base br col embed hr img input link meta source track wbr".split())
_BREAK_TAGS = frozenset("br p div li tr h1 h2 h3 h4 h5 h6 table ul ol dl dt dd blockquote caption center hr pre".split())
_BODY_TAGS = _BREAK_TAGS | frozenset("a b strong em i u s span font sub sup small mark img tbody thead tfoot td th "
                                     "col colgroup".split())
_TITLE_TAGS = frozenset("b strong em i u span font".split())
_HIDDEN_STYLE = re.compile(r"display\s*:\s*none|visibility\s*:\s*hidden", re.I)
_INVALID_DETAIL = "체육시설 공지 상세 HTML 구조가 예상과 다릅니다."
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


def robots_rules(raw: bytes) -> RobotFileParser:
    """HTTP 200으로 받은 robots.txt만 해석한다. 규칙 줄이 아닌 내용(예: HTML 차단 화면)이 있으면 판단하지 않는다."""
    try:
        lines = raw.decode("utf-8-sig").splitlines()
    except UnicodeDecodeError:
        raise ValueError("체육시설 robots.txt를 UTF-8로 읽을 수 없습니다.") from None
    if any(line.split("#", 1)[0].strip() and not _ROBOTS_LINE.fullmatch(line.split("#", 1)[0].strip())
           for line in lines):
        raise ValueError("체육시설 robots.txt에 규칙이 아닌 줄이 있어 허용 여부를 확정할 수 없습니다.")
    rules = RobotFileParser()
    rules.parse(lines)
    return rules


def allowed(rules: RobotFileParser, url: str) -> bool:
    return rules.can_fetch(USER_AGENT, url)


def _feed(parser: HTMLParser, text: str, message: str) -> None:
    if "\x00" in text:
        raise ValueError(message)
    try:
        parser.feed(text)
        parser.close()
    except AssertionError:
        raise ValueError(message) from None


class _LinkParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hidden = 0
        self.hrefs: list[str] = []

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)  # 브라우저처럼 `<template/>`도 여는 태그로 본다.

    def handle_starttag(self, tag, attrs):
        if tag in _HIDDEN_TAGS:
            self.hidden += 1
        elif tag == "a" and not self.hidden:
            if [name for name, _ in attrs].count("href") > 1:
                raise ValueError("체육시설 공지 목록 링크의 href가 중복되었습니다.")
            href = dict(attrs).get("href")
            if href:
                self.hrefs.append(href)

    def handle_endtag(self, tag):
        if tag in _HIDDEN_TAGS and self.hidden:
            self.hidden -= 1


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
    """목록 1쪽의 공지 번호를 문서 순서대로 돌려준다. 고정 글·전체 페이지 수는 표시 형식을 몰라 읽지 않는다."""
    try:
        text = raw.decode("utf-8-sig")
    except (AttributeError, UnicodeDecodeError):
        raise ValueError("체육시설 공지 목록은 UTF-8이어야 합니다.") from None
    parser = _LinkParser()
    _feed(parser, text, "체육시설 공지 목록 HTML 구조가 올바르지 않습니다.")
    ids: list[str] = []
    for href in parser.hrefs:
        seq = _listed_seq(href)
        if seq in ids:
            raise ValueError("체육시설 공지 목록에 같은 공지 번호가 있습니다.")
        if seq:
            ids.append(seq)
    if not ids:
        raise ValueError("체육시설 공지 목록에서 공지 상세 링크를 찾지 못했습니다.")
    return ids


class _DetailParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hidden = 0
        self.seqs: list[str | None] = []
        self.titles: list[str] = []
        self.title: list[str] | None = None
        self.title_tags: list[str] = []
        self.bodies = 0
        self.body: list[str] | None = None
        self.text: list[str] = []
        self.images: list[dict] = []
        self.links: list[dict] = []
        self.link: dict | None = None

    def handle_startendtag(self, tag, attrs):
        # HTML에서 빈 요소가 아닌 태그의 `/>`는 무시되므로 시작 태그로만 읽는다.
        self.handle_starttag(tag, attrs)

    def handle_starttag(self, tag, attrs):
        names = [name for name, _ in attrs]
        values = dict(attrs)
        if self.body is not None:
            self._body_start(tag, names, values)
        elif self.title is not None:
            if tag != "br" and tag not in _TITLE_TAGS:
                raise ValueError(_INVALID_DETAIL)
            if tag == "br":
                self.title.append(" ")
            else:
                self.title_tags.append(tag)
        elif tag in _HIDDEN_TAGS:
            self.hidden += 1
        elif self.hidden:
            return
        elif tag == "input" and values.get("name") == "seq":
            self.seqs.append(values.get("value"))
        elif tag == "h4":
            self.title = []
        elif tag == "div" and "view_cont" in (values.get("class") or "").split():
            self.bodies += 1
            self.body = []
            self._body_start(tag, names, values)

    def _body_start(self, tag, names, values):
        # 속성이 중복되면 브라우저는 첫 값을, 이 파서는 마지막 값을 쓰므로 받지 않는다.
        if (tag not in _BODY_TAGS or len(set(names)) != len(names) or "hidden" in values
                or _HIDDEN_STYLE.search(values.get("style") or "")):
            raise ValueError("체육시설 공지 본문에 허용하지 않는 태그·속성이 있습니다.")
        if tag in _BREAK_TAGS:
            self.text.append("\n")
        if tag == "img":
            self.images.append({"src": values.get("src"), "alt": values.get("alt")})
        if tag == "a":
            if "a" in self.body:
                raise ValueError(_INVALID_DETAIL)
            self.link = {"href": values["href"], "text": []} if values.get("href") else None
        if tag not in _VOID_TAGS:
            self.body.append(tag)

    def handle_endtag(self, tag):
        if self.body is not None:
            if tag in _VOID_TAGS:
                if tag == "br":
                    self.text.append("\n")
                return
            if self.body[-1] != tag:
                raise ValueError(_INVALID_DETAIL)
            self.body.pop()
            if tag in _BREAK_TAGS:
                self.text.append("\n")
            if tag == "a" and self.link is not None:
                self.links.append({"href": self.link["href"], "text": " ".join("".join(self.link["text"]).split())})
                self.link = None
            if not self.body:
                self.body = None
        elif self.title is not None:
            if self.title_tags and self.title_tags[-1] == tag:
                self.title_tags.pop()
            elif not self.title_tags and tag == "h4":
                self.titles.append(" ".join("".join(self.title).split()))
                self.title = None
            elif tag != "br":
                raise ValueError(_INVALID_DETAIL)
        elif tag in _HIDDEN_TAGS and self.hidden:
            self.hidden -= 1

    def handle_data(self, data):
        if self.body is not None:
            self.text.append(data)
            if self.link is not None:
                self.link["text"].append(data)
        elif self.title is not None:
            self.title.append(data)


def parse_detail(text: str, *, seq: str) -> dict:
    """제목·본문 줄·이미지·링크를 표시 문구 그대로 보관한다. 일정·자격·비용·중단 여부는 판정하지 않는다."""
    url = detail_url(seq)
    parser = _DetailParser()
    _feed(parser, text, _INVALID_DETAIL)
    if parser.body is not None or parser.title is not None or parser.hidden:
        raise ValueError(_INVALID_DETAIL)
    if parser.seqs != [seq]:
        raise ValueError("체육시설 공지 상세의 공지 번호(seq)가 요청과 일치하지 않습니다.")
    if len(parser.titles) != 1 or not parser.titles[0]:
        raise ValueError("체육시설 공지 상세의 제목을 하나로 확정할 수 없습니다.")
    if parser.bodies != 1:
        raise ValueError("체육시설 공지 상세의 본문 영역을 하나로 확정할 수 없습니다.")
    lines = [line for line in (" ".join(part.split()) for part in "".join(parser.text).split("\n")) if line]
    if not lines and not parser.images:
        raise ValueError("체육시설 공지 상세에 본문 글자와 이미지가 없습니다.")

    title = parser.titles[0]
    compact = [(line, "".join(line.split())) for line in (title, *lines)]
    # 실제 마크업을 확인하기 전까지 모든 기록은 사람 확인 대상이다. 이용 제한 세부가 이미지에만 있는 공지가 있다.
    flags = {"markup_unverified"}
    if parser.images:
        flags.add("inline_image")
        if not lines:
            flags.add("image_only")
    if parser.links:
        flags.add("link")
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
