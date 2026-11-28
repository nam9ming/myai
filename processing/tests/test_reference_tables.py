import contextlib
import hashlib
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from processing.collection import reference_tables
from processing.collection.official_web import SourceHTTPError
from processing.collection.reference_tables import (
    PARSER_VERSION, REFERENCE_SECTION, SOURCE_URL, capture_reference, content_sha256, fetch_page, main,
    parse_library_hours, read_reference_capture,
)

_TABLES = """
<h4>공공도서관 2개관</h4>
<div class="tbl-respon">
<p class="guide">표를 좌우로 이동합니다.</p>
<div class="tbl-box">
<table class="tbl taC"><caption>합성 공공도서관 표</caption>
<thead><tr><th scope="col">도서관</th><th scope="col">구분</th><th scope="col">정기휴관일</th></tr></thead>
<tbody>
<tr><th scope="row" rowspan="2">가 도서관</th>
<td>자료실</td>
<td rowspan="2">매주 월요일<br /> 법정공휴일</td>
</tr>
<tr><td>열람실</td></tr>
<tr><th scope="row">나 도서관</th><td> 자료실 </td><td></td></tr>
</tbody>
</table>
</div>
<p class="tip mT10">토&middot;일 합성 안내</p>
</div>
<h4>작은도서관 1개관</h4>
<div class="tbl-respon"><div class="tbl-box">
<table class="tbl taC"><caption>합성 작은도서관 표</caption>
<thead>
<tr><th scope="col" rowspan="2">도서관</th><th scope="col" colspan="2">이용시간</th></tr>
<tr><th scope="col">구분</th><th scope="col">운영시간</th></tr>
</thead>
<tbody>
<tr><th scope="row" rowspan="2">다 작은도서관</th><td>동절기</td><td>09:00~18:00</td></tr>
<tr><td>하절기</td><td>10:00~19:00</td></tr>
</tbody>
</table>
</div></div>
"""


def page(body=_TABLES, *, title="이용시간 및 정기휴관일 | 이용안내 | 안성시 도서관", outside=""):
    return f"""<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8"><title>{title}</title>
<script>var marker = "<div id='conts' class='conts'>";</script></head>
<body><!-- 본문 영역 밖의 주석은 읽지 않는다 --><div id="tit_wrap"><h3>이용시간 및 정기휴관일</h3></div>{outside}
<div class="sub"><div id="conts" class="conts">{body}</div></div>
<svg><title>아이콘</title></svg></body></html>"""


def cell(tag, text, *, scope=None, rowspan=1, colspan=1):
    return {"tag": tag, "scope": scope, "rowspan": rowspan, "colspan": colspan, "text": text}


class LibraryHoursParserTest(unittest.TestCase):
    def test_keeps_blocks_and_cell_text_verbatim_with_spans(self):
        record = parse_library_hours(page())
        self.assertEqual(record["source_url"], "https://www.anseong.go.kr/library/contents.do?mId=0501040000")
        self.assertEqual(record["page_title"], "이용시간 및 정기휴관일 | 이용안내 | 안성시 도서관")
        blocks = record["blocks"]
        self.assertEqual([block["kind"] for block in blocks],
                         ["heading", "paragraph", "table", "paragraph", "heading", "table"])
        self.assertEqual(blocks[1], {"kind": "paragraph", "class": "guide", "text": "표를 좌우로 이동합니다."})
        self.assertEqual(blocks[3], {"kind": "paragraph", "class": "tip mT10", "text": "토·일 합성 안내"})
        first = blocks[2]
        self.assertEqual(first["caption"], "합성 공공도서관 표")
        self.assertEqual(first["head"], [[cell("th", "도서관", scope="col"), cell("th", "구분", scope="col"),
                                          cell("th", "정기휴관일", scope="col")]])
        self.assertEqual(first["body"], [
            [cell("th", "가 도서관", scope="row", rowspan=2), cell("td", "자료실"),
             cell("td", "매주 월요일\n 법정공휴일", rowspan=2)],
            [cell("td", "열람실")],
            # 앞뒤 공백과 빈 칸도 고치거나 채우지 않는다.
            [cell("th", "나 도서관", scope="row"), cell("td", " 자료실 "), cell("td", "")],
        ])
        self.assertEqual(blocks[5]["head"][0][1], cell("th", "이용시간", scope="col", colspan=2))
        self.assertEqual(len(content_sha256(record)), 64)
        # 제목은 원본 위치로 다시 확인하므로 앞에 줄(CRLF 포함)이 있어도, 문자 참조가 있어도 읽혀야 한다.
        moved = page(title="이용시간 및 정기휴관일 | 이용&middot;안내 | 안성시 도서관").replace("<head>", "<head>\n\r\n")
        self.assertEqual(parse_library_hours(moved)["page_title"], "이용시간 및 정기휴관일 | 이용·안내 | 안성시 도서관")

    def test_rejects_format_changes(self):
        grid = "표의 칸 수가 머리글과 다름"
        cases = {
            "inline_tag": (_TABLES.replace("열람실", "<strong>열람실</strong>"), "td 안의 strong"),
            "style": (_TABLES.replace("<td>열람실", '<td style="display:none">열람실'), r"td\[style\]"),
            "hidden_class": (_TABLES.replace('class="guide"', 'class="guide blind"'), "p class 값"),
            "scope_tokens": (_TABLES.replace('scope="row">나', 'scope="col row">나'), "th scope 값"),
            "zero_span": (_TABLES.replace('colspan="2"', 'colspan="0"'), "th colspan 값"),
            "empty_row": (_TABLES.replace("<tr><td>열람실</td></tr>", "<tr></tr>"), "빈 행"),
            "short_row": (_TABLES.replace("<td></td></tr>", "</tr>"), grid),
            "wide_row": (_TABLES.replace("<td></td></tr>", "<td></td><td>더</td></tr>"), grid),
            "span_collision": (_TABLES.replace('<td rowspan="2">매주', '<td rowspan="3">매주'), grid),
            "rowspan_overflow": (_TABLES.replace("<td></td></tr>", '<td rowspan="2"></td></tr>'), "구역을 넘음"),
            "no_thead": (_TABLES.replace("<thead>", "").replace("</thead>", "", 1), "table 안의 tr"),
            "text_in_div": (_TABLES.replace('<div class="tbl-box">', '<div class="tbl-box">흩어진 글'),
                            "div 안의 글자"),
            "script": (_TABLES + "<script>x()</script>", "conts 안의 script"),
            "self_closing": (_TABLES.replace("<td></td>", "<td/>"), "스스로 닫는 td"),
            "br_outside_text": (_TABLES.replace("<h4>작은", "<br><h4>작은"), "글자 밖의 br"),
            "unclosed_caption": (_TABLES.replace("</caption>\n", "", 1), "caption 안의 thead"),
            "unclosed_row": (_TABLES.replace("</tbody>", "<tr></tbody>", 1), "tr 안에서 닫는 tbody"),
            # 3.13.5는 주석을 첫 `-->`까지 읽어 `--!>` 뒤의 행·글자를 오류 없이 빼고, 3.14.6은 `--!>`에서 끝낸다.
            "comment": (_TABLES.replace("<h4>작은", "<!-- 주석 --><h4>작은"), "선언·처리 지시문·주석"),
            "comment_hides_row": (_TABLES.replace('<tr><th scope="row">나', '<!-- a --!><tr><th scope="row">나')
                                  .replace("<td></td></tr>", "<td></td></tr><!-- b -->"), "선언·처리 지시문·주석"),
            "comment_in_cell": (_TABLES.replace("열람실", "열<!-- x --!>람-->실"), "선언·처리 지시문·주석"),
            "bogus_comment": (_TABLES.replace("<h4>작은", "<!x><h4>작은"), "선언·처리 지시문·주석"),
            "nul": (_TABLES.replace("열람실", "열람\x00실"), "NUL 문자"),
            # 화면에서 공백이 되는 원본 줄바꿈은 `br`에서 온 줄바꿈과 구별할 수 없다.
            "raw_newline": (_TABLES.replace("<br />", "\n"), "글자 안의 원본 줄바꿈"),
            "raw_cr": (_TABLES.replace("열람실", "열람\r실"), "글자 안의 원본 줄바꿈"),
            "newline_reference": (_TABLES.replace("열람실", "열람&#10;실"), "글자 안의 원본 줄바꿈"),
            "no_table": ("<h4>표 없음</h4>", "표가 없습니다"),
        }
        fixtures = {name: (page(body), message) for name, (body, message) in cases.items()}
        fixtures.update({
            "title": (page(title="공지사항 | 안성시 도서관"), "페이지가 아닌 응답"),
        })
        # 3.13은 title 안의 태그·주석을 마크업으로, 3.14는 원문 글자로 읽으므로 어느 버전에서든 거부한다.
        # `</>`는 3.13.5가 콜백 없이 건너뛰어 글자만 빠진다.
        markup = ("<b>이용안내</b>", "</b>", "<!-- x -->", "<?x>", "<!x>", "&lt;", "1 < 2", "A</>B")
        fixtures.update({
            f"title_markup_{index}": (page(title=f"이용시간 및 정기휴관일 | {text} | 안성시 도서관"), "제목 안의 마크업")
            for index, text in enumerate(markup)
        })
        fixtures.update({
            "second_conts": (page(outside='<div id="conts" class="conts"></div>'), r"\(본문 영역 div#conts\)"),
            "no_conts": (page().replace('id="conts"', 'id="other"'), "없거나 닫히지 않음"),
            "unterminated": (page().rsplit("</div></div>", 1)[0], "없거나 닫히지 않음"),
        })
        for name, (fixture, message) in fixtures.items():
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, message):
                parse_library_hours(fixture)


class ReferenceCaptureTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(TemporaryDirectory())).resolve() / "private"
        self.root.mkdir(mode=0o700)
        self.section = self.root / REFERENCE_SECTION
        self.fetch = self.enterContext(patch("processing.collection.reference_tables.fetch_page"))
        self.fetch.return_value = page().encode()

    def receipt(self, name):
        return json.loads((self.section / name / "capture.json").read_text(encoding="utf-8"))

    def test_capture_keeps_raw_parsed_record_and_rereads_archive(self):
        self.assertEqual(capture_reference("library-hours", "first", self.section),
                         {"capture_id": "first", "status": "parsed", "content_changed": None})
        directory = self.section / "first"
        raw = page().encode()
        self.assertEqual((directory / "page.html").read_bytes(), raw)
        receipt = self.receipt("first")
        record = parse_library_hours(page())
        self.assertEqual({key: receipt[key] for key in ("schema_version", "page", "source_url", "status", "raw",
                                                        "parsed_file", "content_sha256", "parse_error", "previous")},
                         {"schema_version": "citizen-reference-table-capture-v1", "page": "library-hours",
                          "source_url": SOURCE_URL, "status": "parsed",
                          "raw": {"file": "page.html", "sha256": hashlib.sha256(raw).hexdigest()},
                          "parsed_file": "parsed.json", "content_sha256": content_sha256(record),
                          "parse_error": None, "previous": None})
        self.assertEqual(json.loads((directory / "parsed.json").read_text(encoding="utf-8")),
                         {"schema_version": "citizen-reference-table-v1", "parser_version": PARSER_VERSION,
                          "sha256": hashlib.sha256(raw).hexdigest(), "record": record})
        self.assertEqual(read_reference_capture(self.section, "first"), (record, receipt))
        self.assertEqual(oct(directory.stat().st_mode & 0o777), "0o700")

    def test_previous_capture_hashes_separate_page_changes_from_table_changes(self):
        capture_reference("library-hours", "first", self.section)
        variants = {
            "same": (page(), False, False),
            "menu": (page(outside="<p>메뉴 변경</p>"), True, False),
            "cell": (page(_TABLES.replace("10:00~19:00", "10:00~20:00")), True, True),
        }
        for name, (fixture, raw_changed, content_changed) in variants.items():
            with self.subTest(name=name):
                self.fetch.return_value = fixture.encode()
                summary = capture_reference("library-hours", name, self.section, previous="first")
                self.assertEqual(summary["content_changed"], content_changed)
                change = self.receipt(name)["previous"]
                first = self.receipt("first")
                self.assertEqual(change, {"capture_id": "first", "fetched_at": first["fetched_at"],
                                          "raw_sha256": first["raw"]["sha256"],
                                          "content_sha256": first["content_sha256"],
                                          "raw_changed": raw_changed, "content_changed": content_changed})

    def test_parse_failure_keeps_raw_and_reason_and_is_not_readable(self):
        capture_reference("library-hours", "first", self.section)
        self.fetch.return_value = page(title="점검 중 | 안성시 도서관").encode()
        with (patch.object(reference_tables, "REFERENCE_ROOT", self.section),
              patch("sys.argv", ["reference_tables", "library-hours", "--name", "broken", "--previous", "first"]),
              contextlib.redirect_stdout(io.StringIO()) as output):
            self.assertEqual(main(), 2)
        self.assertEqual(json.loads(output.getvalue()),
                         {"capture_id": "broken", "status": "parse_failed", "content_changed": None})
        receipt = self.receipt("broken")
        self.assertEqual(receipt["parse_error"], "도서관 이용시간 및 정기휴관일 페이지가 아닌 응답입니다.")
        self.assertEqual((receipt["parsed_file"], receipt["content_sha256"]), (None, None))
        self.assertTrue(receipt["previous"]["raw_changed"])
        self.assertIsNone(receipt["previous"]["content_changed"])
        self.assertFalse((self.section / "broken" / "parsed.json").exists())
        self.assertEqual((self.section / "broken" / "page.html").read_bytes(), self.fetch.return_value)
        with self.assertRaisesRegex(ValueError, "완료된 도서관 이용시간 수집 기록"):
            read_reference_capture(self.section, "broken")
        with self.assertRaisesRegex(ValueError, "완료된 도서관 이용시간 수집 기록"):
            capture_reference("library-hours", "after", self.section, previous="broken")

    def test_reader_rejects_tampered_archives(self):
        capture_reference("library-hours", "first", self.section)
        directory = self.section / "first"
        original = {name: (directory / name).read_bytes() for name in ("page.html", "parsed.json", "capture.json")}
        parsed = json.loads(original["parsed.json"])
        older = dict(parsed, parser_version="library-hours-parser-v0")
        edited = json.loads(original["parsed.json"])
        edited["record"]["blocks"][0]["text"] = "바뀐 제목"
        receipt = json.loads(original["capture.json"])
        cases = {
            "raw": ("page.html", page(_TABLES.replace("열람실", "자료실2")).encode(), "원본 해시"),
            "parser_version": ("parsed.json", json.dumps(older).encode(), "다른 버전"),
            "record": ("parsed.json", json.dumps(edited).encode(), "파싱 결과"),
            "content": ("capture.json", json.dumps(dict(receipt, content_sha256="0" * 64)).encode(), "파싱 결과"),
            "url": ("capture.json", json.dumps(dict(receipt, source_url="https://example.com/")).encode(), "완료된"),
            "time": ("capture.json", json.dumps(dict(receipt, fetched_at="2026-11-28")).encode(), "수신 시각"),
        }
        for name, (filename, content, message) in cases.items():
            with self.subTest(name=name):
                (directory / filename).write_bytes(content)
                with self.assertRaisesRegex(ValueError, message):
                    read_reference_capture(self.section, "first")
                (directory / filename).write_bytes(original[filename])
        self.assertEqual(read_reference_capture(self.section, "first")[1], receipt)

    def test_rejects_inputs_before_requests(self):
        capture_reference("library-hours", "first", self.section)
        (self.section / "dangling").symlink_to(self.root / "nowhere")
        (self.root / "link").symlink_to(self.section)
        self.fetch.reset_mock()
        for args, message in {
            ("library-hours", "../x", None): "수집 이름",
            ("garbage", "x", None): "지원하지 않는 기준표",
            ("library-hours", "x", "missing"): "안전하게 읽을 수 없습니다",
            ("library-hours", "first", "first"): "이름이 달라야",
            ("library-hours", "first", None): "이미 사용 중인",
            ("library-hours", "dangling", None): "이미 사용 중인",
        }.items():
            with self.subTest(args=args), self.assertRaisesRegex(ValueError, message):
                capture_reference(args[0], args[1], self.section, previous=args[2])
        with self.assertRaisesRegex(ValueError, "심볼릭 링크"):
            capture_reference("library-hours", "x", self.root / "link")
        self.section.chmod(0o755)
        with self.assertRaisesRegex(ValueError, "실행 사용자만"):
            capture_reference("library-hours", "x", self.section)
        self.section.chmod(0o700)
        self.fetch.assert_not_called()
        self.fetch.side_effect = ValueError("도서관 이용시간 응답을 받지 못했습니다.")
        with self.assertRaisesRegex(ValueError, "받지 못했습니다"):
            capture_reference("library-hours", "offline", self.section)
        self.assertFalse((self.section / "offline").exists())

    @patch("processing.collection.official_web.HTTPSConnection")
    def test_fetch_sends_bodyless_get_to_fixed_host(self, connect):
        response = connect.return_value.getresponse.return_value.__enter__.return_value
        response.status, response.getheader.return_value = 200, None
        response.read.return_value = b"<html></html>"
        self.assertEqual(fetch_page(), b"<html></html>")
        self.assertEqual(connect.call_args.args[0], "www.anseong.go.kr")
        request = connect.return_value.request.call_args
        self.assertEqual(request.args, ("GET", "/library/contents.do?mId=0501040000"))
        self.assertNotIn("body", request.kwargs)
        self.assertEqual(request.kwargs["headers"]["User-Agent"], "yeogi-it/official-source-capture")
        response.status = 302
        with self.assertRaisesRegex(SourceHTTPError, r"도서관 이용시간 HTTP 응답 오류\(302\)"):
            fetch_page()


if __name__ == "__main__":
    unittest.main()
