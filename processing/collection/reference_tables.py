"""안성시 도서관 이용시간·정기휴관일 기준표 페이지를 원본과 함께 보관하고 표를 원문 그대로 읽는다."""

from datetime import UTC, datetime
import hashlib
import html
import json
import os
from pathlib import Path
import re
import stat
import sys

from .__main__ import decode_input
from .capture import (
    CAPTURE_ROOT, bundle_directory, capture_timestamp, open_archive, read_capture_file, read_receipt,
    validate_name, write_new, write_receipt,
)
from .cli import CollectionArguments
from .html_tokens import PinnedHTMLParser
from .official_web import DETAIL_MAX_BYTES, OFFICIAL_ORIGIN, _fetch

REFERENCE_SECTION = "collection-reference-tables"
REFERENCE_ROOT = CAPTURE_ROOT.with_name(REFERENCE_SECTION)
SCHEMA = "citizen-reference-table-capture-v1"
RECORD_SCHEMA = "citizen-reference-table-v1"
PARSER_VERSION = "library-hours-parser-v2"
PAGES = ("library-hours",)
_PATH = "/library/contents.do?mId=0501040000"
SOURCE_URL = OFFICIAL_ORIGIN + _PATH
_LABEL = "도서관 이용시간"
_TITLE = "이용시간 및 정기휴관일"
_INVALID = "도서관 이용시간 페이지 HTML 구조가 올바르지 않습니다"
_INVALID_ARCHIVE = "완료된 도서관 이용시간 수집 기록을 확인할 수 없습니다."

# div#conts 안에서 허용하는 부모별 자식 요소. 2026-11-28 실제 페이지에 쓰인 것만 받고 나머지는 형식 변경으로 본다.
_CHILDREN = {
    "conts": {"h4", "div", "p"},
    "div": {"h4", "div", "p", "table"},
    "table": {"caption", "thead", "tbody"},
    "thead": {"tr"},
    "tbody": {"tr"},
    "tr": {"th", "td"},
}
_TEXT_TAGS = {"h4", "p", "caption", "th", "td"}
# 속성 이름별 허용 값. None은 아래 형식 검사만 한다. 숨김 class·style은 받지 않는다.
_ATTRS = {
    "div": {"class": {"tbl-respon", "tbl-box"}},
    "p": {"class": {"guide", "tip", "mT10"}},
    "table": {"class": {"tbl", "taC"}},
    "th": {"scope": {"col", "row"}, "rowspan": None, "colspan": None},
    "td": {"rowspan": None, "colspan": None},
}
_SPAN = re.compile(r"[1-9][0-9]?")


class _PageParser(PinnedHTMLParser):
    """`head`의 제목과 유일한 `div#conts` 안의 제목·문단·표를 문서 순서대로 읽는다."""

    def __init__(self):
        super().__init__()
        self.in_head = False
        self.title: list[str] | None = None
        self.titles: list[str] = []
        self.stack: list[str] | None = None
        self.conts_seen = False
        self.blocks: list[dict] = []
        self.text: list[str] | None = None
        self.paragraph_class: str | None = None
        self.table: dict | None = None
        self.parts: list[str] = []
        self.group: list | None = None
        self.row: list | None = None
        self.cell: dict | None = None

    def fail(self, detail: str):
        raise ValueError(f"{_INVALID} ({detail}).")

    def markup_error(self) -> ValueError:
        return ValueError(f"{_INVALID} (브라우저·Python 버전마다 해석이 갈리는 태그·주석·스크립트 표기).")

    def _check_attrs(self, tag, attrs):
        names = [name for name, _ in attrs]
        if len(set(names)) != len(names):
            self.fail(f"{tag} 속성 중복")
        allowed = _ATTRS.get(tag, {})
        for name, value in attrs:
            if name not in allowed:
                self.fail(f"허용하지 않은 속성 {tag}[{name[:40]}]")
            if name in ("rowspan", "colspan"):
                if value is None or _SPAN.fullmatch(value) is None:
                    self.fail(f"{tag} {name} 값")
            elif name == "class":
                if not value or not set(value.split()) <= allowed[name]:
                    self.fail(f"허용하지 않은 {tag} {name} 값")
            elif value not in allowed[name]:
                self.fail(f"허용하지 않은 {tag} {name} 값")

    def handle_starttag(self, tag, attrs):
        super().handle_starttag(tag, attrs)
        if self.stack is None:
            values = dict(attrs)
            if tag == "head":
                self.in_head = True
            elif tag == "title" and self.in_head:
                self.title = []
            elif tag == "div" and values.get("id") == "conts":
                if self.conts_seen or sorted(name for name, _ in attrs) != ["class", "id"] or values["class"] != "conts":
                    self.fail("본문 영역 div#conts")
                self.conts_seen = True
                self.stack = ["conts"]
            return
        if tag == "br":
            if attrs or self.text is None:
                self.fail("글자 밖의 br")
            self.text.append("\n")
            return
        if tag not in _CHILDREN.get(self.stack[-1], ()):
            self.fail(f"{self.stack[-1]} 안의 {tag[:40]}")
        self._check_attrs(tag, attrs)
        self.stack.append(tag)
        if tag in _TEXT_TAGS:
            self.text = []
        if tag == "p":
            self.paragraph_class = dict(attrs).get("class")
        elif tag == "table":
            self.table, self.parts = {"kind": "table", "caption": None, "head": [], "body": []}, []
        elif tag in ("thead", "tbody"):
            self.group = self.table["head" if tag == "thead" else "body"]
        elif tag == "tr":
            self.row = []
        elif tag in ("th", "td"):
            values = dict(attrs)
            self.cell = {"tag": tag, "scope": values.get("scope"), "rowspan": int(values.get("rowspan") or 1),
                         "colspan": int(values.get("colspan") or 1)}

    def handle_startendtag(self, tag, attrs):
        if self.stack is not None and tag != "br":
            self.fail(f"스스로 닫는 {tag[:40]}")
        super().handle_startendtag(tag, attrs)

    def parse_endtag(self, i):
        if self.stack is not None and re.match(r"</[a-zA-Z]", self.rawdata[i:i + 3]) is None:
            # 브라우저가 주석으로 읽는 `</ x>`와 버리는 `</>`를 기반 클래스는 콜백 없이 건너뛴다. 본문 영역에서는 주석처럼 거부한다.
            self.fail("본문 영역의 선언·처리 지시문·주석")
        return super().parse_endtag(i)

    def handle_endtag(self, tag):
        if self.title is not None:
            # title은 원문 텍스트 요소라 `</title`까지 원본 그대로 온다. 브라우저처럼 문자 참조만 푼다.
            title = html.unescape("".join(self.title))
            if "<" in title:
                # 태그·주석처럼 보이는 글자나 `&lt;`는 Python 버전·브라우저마다 제목을 다르게 만들 수 있어 받지 않는다.
                self.fail("제목 안의 마크업")
            self.titles.append(title)
            self.title = None
            return
        if self.stack is None:
            if tag == "head":
                self.in_head = False
            return
        top = self.stack[-1]
        if tag != ("div" if top == "conts" else top):
            self.fail(f"{top} 안에서 닫는 {tag[:40]}")
        self.stack.pop()
        if not self.stack:
            self.stack = None
            return
        text = None
        if tag in _TEXT_TAGS:
            text, self.text = "".join(self.text), None
        if tag == "h4":
            self.blocks.append({"kind": "heading", "text": text})
        elif tag == "p":
            self.blocks.append({"kind": "paragraph", "class": self.paragraph_class, "text": text})
        elif tag == "caption":
            self.table["caption"] = text
            self.parts.append(tag)
        elif tag in ("th", "td"):
            self.row.append({**self.cell, "text": text})
        elif tag == "tr":
            if not self.row:
                self.fail("빈 행")
            self.group.append(self.row)
        elif tag in ("thead", "tbody"):
            self.parts.append(tag)
        elif tag == "table":
            if self.parts != ["caption", "thead", "tbody"] or not self.table["head"] or not self.table["body"]:
                self.fail("표는 caption·thead·tbody 순서로 하나씩 있어야 함")
            width = sum(cell["colspan"] for cell in self.table["head"][0])
            _check_grid(self, self.table["head"], width)
            _check_grid(self, self.table["body"], width)
            self.blocks.append(self.table)

    def handle_data(self, data):
        super().handle_data(data)
        if self.title is not None:
            self.title.append(data)
        if self.stack is None:
            return
        if "\x00" in data:
            self.fail("NUL 문자")
        if self.text is not None:
            # 원본 줄바꿈은 화면에서 공백이 되므로, 남기면 `br`에서 온 줄바꿈과 구별할 수 없다.
            if "\n" in data or "\r" in data:
                self.fail("글자 안의 원본 줄바꿈")
            self.text.append(data)
        elif data.strip():
            self.fail(f"{self.stack[-1]} 안의 글자")

    def _reject_in_body(self, *_):
        # 2026-11-28 실제 본문 영역에는 주석·선언이 없었다. 화면에 없는 표기도 허용 목록 밖의 형식 변경으로 본다.
        if self.stack is not None:
            self.fail("본문 영역의 선언·처리 지시문·주석")

    handle_decl = handle_pi = unknown_decl = handle_comment = _reject_in_body


def _check_grid(parser: _PageParser, rows: list[list[dict]], width: int) -> None:
    """행 병합·열 병합을 펼쳤을 때 모든 행이 머리글 너비를 빈칸 없이 채우는지 확인한다. 값은 펼치지 않는다."""
    pending = [0] * width
    for row in rows:
        column = 0
        for cell in row:
            while column < width and pending[column]:
                column += 1
            end = column + cell["colspan"]
            if end > width or any(pending[column:end]):
                parser.fail("표의 칸 수가 머리글과 다름")
            pending[column:end] = [cell["rowspan"]] * cell["colspan"]
            column = end
        if not all(pending):
            parser.fail("표의 칸 수가 머리글과 다름")
        pending = [count - 1 for count in pending]
    if any(pending):
        parser.fail("행 병합이 표 구역을 넘음")


def parse_library_hours(text: str) -> dict:
    """제목·문단·표 칸 글자를 원문 그대로(`br`만 줄바꿈으로) 남긴다. 글자 안의 원본 줄바꿈은 거부한다.

    요일·시간·휴관일을 해석하지 않는다.
    """
    if not isinstance(text, str):
        raise ValueError(f"{_INVALID}.")
    parser = _PageParser()
    try:
        parser.feed(text)
        parser.close()
    except AssertionError:
        raise ValueError(f"{_INVALID}.") from None
    if not parser.conts_seen or parser.stack is not None or parser.title is not None:
        raise ValueError(f"{_INVALID} (본문 영역 div#conts가 없거나 닫히지 않음).")
    if (len(parser.titles) != 1 or not parser.titles[0].startswith(f"{_TITLE} | ")
            or not parser.titles[0].endswith(" | 안성시 도서관")):
        raise ValueError("도서관 이용시간 및 정기휴관일 페이지가 아닌 응답입니다.")
    if not any(block["kind"] == "table" for block in parser.blocks):
        raise ValueError("도서관 이용시간 페이지에 표가 없습니다.")
    return {"source_url": SOURCE_URL, "page_title": parser.titles[0], "blocks": parser.blocks}


def content_sha256(record: dict) -> str:
    """원본 HTML의 메뉴·화면 요소 변경과 구별해 표 내용 변경만 보는 해시."""
    encoded = json.dumps(record["blocks"], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def fetch_page() -> bytes:
    return _fetch("GET", _PATH, None, DETAIL_MAX_BYTES, source=_LABEL)


def read_reference_capture(root: Path, name: str) -> tuple[dict, dict]:
    """보관 원본을 다시 파싱해 해시·파싱 결과·수집 기록과 대조한다. `root`는 수집 구역 디렉터리다."""
    validate_name(name)
    with open_archive(root.parent, Path(root.name) / name) as directory:
        receipt = read_receipt(directory, "capture.json")
        if (receipt.get("schema_version") != SCHEMA or receipt.get("capture_id") != name
                or receipt.get("page") != PAGES[0] or receipt.get("source_url") != SOURCE_URL
                or receipt.get("status") != "parsed" or not isinstance(receipt.get("raw"), dict)
                or receipt["raw"].get("file") != "page.html" or receipt.get("parsed_file") != "parsed.json"):
            raise ValueError(_INVALID_ARCHIVE)
        capture_timestamp(receipt.get("fetched_at"))
        raw = read_capture_file(directory, "page.html", DETAIL_MAX_BYTES)
        text, digest = decode_input(raw, f"{_LABEL} 원본")
        if receipt["raw"].get("sha256") != digest:
            raise ValueError("도서관 이용시간 원본 해시가 수집 기록과 다릅니다.")
        parsed = read_receipt(directory, "parsed.json")
        if parsed.get("parser_version") != PARSER_VERSION:
            raise ValueError("현재 파서와 다른 버전으로 만든 도서관 이용시간 기록입니다. 다시 수집해 주세요.")
        record = parse_library_hours(text)
        if (parsed != {"schema_version": RECORD_SCHEMA, "parser_version": PARSER_VERSION, "sha256": digest,
                       "record": record} or receipt.get("content_sha256") != content_sha256(record)):
            raise ValueError("도서관 이용시간 파싱 결과가 원본 또는 수집 기록과 다릅니다.")
    return record, receipt


def capture_reference(page: str, name: str, root: Path, *, previous: str | None = None) -> dict:
    """원본·파싱 결과·`capture.json`을 남기고, 이전 수집이 있으면 원본·표 내용 해시 변화를 기록한다."""
    validate_name(name)
    if page not in PAGES:
        raise ValueError("지원하지 않는 기준표입니다.")
    earlier = None
    if previous is not None:
        if previous == name:
            raise ValueError("비교할 이전 수집은 이번 수집과 이름이 달라야 합니다.")
        _, earlier = read_reference_capture(root, previous)
    # 받은 원본을 버리지 않도록 저장할 수 없는 경우는 요청 전에 거부한다. 묶음은 요청이 성공한 뒤에 만든다.
    if root.resolve() != root:
        raise ValueError("수집 디렉터리에 심볼릭 링크를 사용할 수 없습니다.")
    if root.exists() and (root.stat().st_uid != os.geteuid() or stat.S_IMODE(root.stat().st_mode) & 0o077):
        raise ValueError("수집 디렉터리는 실행 사용자만 접근할 수 있어야 합니다.")
    if (root / name).exists() or (root / name).is_symlink():
        raise ValueError("이미 사용 중인 수집 이름입니다.")
    raw = fetch_page()
    fetched_at = datetime.now(UTC).isoformat()
    digest = hashlib.sha256(raw).hexdigest()
    record = parse_error = content = None
    try:
        record = parse_library_hours(decode_input(raw, f"{_LABEL} 원본")[0])
        content = content_sha256(record)
    except ValueError as error:
        parse_error = str(error)
    status = "parsed" if record is not None else "parse_failed"
    change = None
    if earlier is not None:
        change = {"capture_id": previous, "fetched_at": earlier["fetched_at"],
                  "raw_sha256": earlier["raw"]["sha256"], "content_sha256": earlier["content_sha256"],
                  "raw_changed": digest != earlier["raw"]["sha256"],
                  "content_changed": None if content is None else content != earlier["content_sha256"]}
    with bundle_directory(root, name) as directory:
        write_new(directory, "page.html", raw)
        if record is not None:
            write_receipt(directory, "parsed.json", {"schema_version": RECORD_SCHEMA, "parser_version": PARSER_VERSION,
                                                     "sha256": digest, "record": record})
        write_receipt(directory, "capture.json", {
            "schema_version": SCHEMA, "capture_id": name, "page": page, "source_url": SOURCE_URL,
            "fetched_at": fetched_at, "status": status, "raw": {"file": "page.html", "sha256": digest},
            "parsed_file": "parsed.json" if record is not None else None, "parser_version": PARSER_VERSION,
            "content_sha256": content, "parse_error": parse_error, "previous": change,
        })
    return {"capture_id": name, "status": status,
            "content_changed": None if change is None else change["content_changed"]}


def main() -> int:
    parser = CollectionArguments(description=__doc__)
    parser.add_argument("page", choices=PAGES)
    parser.add_argument("--name", required=True)
    parser.add_argument("--previous")
    args = parser.parse_args()
    try:
        summary = capture_reference(args.page, args.name, REFERENCE_ROOT, previous=args.previous)
    except ValueError as error:
        print(f"기준표 수집 실패: {error}", file=sys.stderr)
        return 1
    except OSError:
        print("기준표 원본 또는 완료 기록을 저장할 수 없습니다.", file=sys.stderr)
        return 1
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if summary["status"] == "parsed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
