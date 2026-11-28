import contextlib
import hashlib
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from processing.collection import sports_batch
from processing.collection.official_web import SourceHTTPError
from processing.collection.sports_batch import capture_sports_batch, read_sports_batch
from processing.collection.sports_notices import LISTING_URL, allowed, detail_url, parse_detail, parse_listing, robots_rules

# 실제 HTML을 받지 못해 만든 합성 원본이다. 상세 링크 형식만 조사 기록의 실제 주소(seq=96)를 따른다.
_LINK = "/index.do?board_id=notice&amp;cp=%2Fboard%2Fview.do&amp;menu_id=0008&amp;pageIndex=1&amp;seq={}"
ROBOTS = b"User-agent: *\nDisallow: /admin/\n"


def listing(*seqs, extra=""):
    rows = "".join(f'<tr><td class="tit"><a href="{_LINK.format(seq)}"><b>공지</b> {seq}</a></td></tr>' for seq in seqs)
    return (f'<!DOCTYPE html><html><body><a href="/index.do?menu_id=0008&amp;pageIndex=2">2</a>'
            f'<a href="javascript:void(0)">맨 위</a><table class="bod_list"><tbody>{rows}</tbody></table>{extra}</body></html>').encode()


def detail(seq, body="<p>예약 일정 : 3월 2일(월) 09:00 예약 오픈</p>", title="체육관 예약 안내", head=""):
    return (f'<!DOCTYPE html><html><head><script>var h4 = "<h4>x</h4>";</script></head><body>{head}'
            f'<form id="viewForm"><input type="hidden" name="seq" value="{seq}"></form>'
            f'<h4>{title}</h4><div class="view_cont">{body}</div></body></html>')


def parsed(*args, **options):
    return parse_detail(detail("96", *args, **options), seq="96")


class SportsParserTest(unittest.TestCase):
    def test_listing_reads_detail_links_in_order(self):
        absolute = "https://reservation.anseong.go.kr/index.do?board_id=notice&cp=/board/view.do&menu_id=0008&pageIndex=1&seq=7"
        raw = listing("111", "96", extra='<div hidden><div><a href="/index.do?menu_id=0001">메뉴</a></div></div><br hidden>'
                      f'<a href="{absolute}">x</a>'
                      '<a href="https://example.com/index.do?seq=3">외부</a><a href="http://[x/index.do?seq=4">깨짐</a>')
        self.assertEqual(parse_listing(raw), ["111", "96", "7"])

    def test_listing_rejects_unexpected_shapes(self):
        cases = {
            "형식": listing("1", extra='<a href="/index.do?board_id=notice&seq=2">x</a>'),
            "같은 공지": listing("1", "1"),
            "찾지 못했": listing(),
            "UTF-8": "<a>공지</a>".encode("cp949"),
            "목록 HTML 구조": listing("1", extra='<p class="a"\xa0id="b">x</p>'),
        }
        for message, raw in cases.items():
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                parse_listing(raw)
        with self.assertRaisesRegex(ValueError, "형식"):
            parse_listing(listing("1").replace(b"pageIndex=1", b"pageIndex=2"))
        # 화면에 없는 공지를 요청하고 complete로 남기지 않는다. 링크·안·조상은 실제 목록에서 본 표기만 받는다.
        link = f'<a href="{_LINK.format(2)}">x</a>'
        for extra in (f'<div style="display: none"><div></div>{link}</div>', f'<p>{link}</p>', f"<details open>{link}</details>",
                      link.replace("<a", "<a hidden"), link.replace("<a", "<a popover"), f'<div popover>{link}</div>',
                      f'<div style="display/**/:none">{link}</div>', link.replace("x<", "<i>x</i><"),
                      *(f'<{tag}>{link}</{tag}>' for tag in "details dialog object template ul".split())):
            with self.subTest(extra=extra), self.assertRaisesRegex(ValueError, "허용 목록 밖"):
                parse_listing(listing("1", extra=extra))
        # 경계가 브라우저와 갈릴 수 있는 중첩(브라우저가 td 안의 </div>를 무시함 등)과 뒤에 나온 body 속성도 거부한다.
        for extra in ("<div><span></div></span>", f"<div hidden><table><tr><td></div>{link}", "<div>", "<body hidden>",
                      "<frameset></frameset>"):
            with self.subTest(extra=extra), self.assertRaisesRegex(ValueError, "목록 HTML 구조"):
                parse_listing(listing("1", extra=extra))

    def test_detail_keeps_display_text_and_keyword_lines_verbatim(self):
        body = ("<p>예약 일정 : 3월 2일(월) 09:00</p><p>관내 거주자 <strong>우선</strong>&nbsp;배정</p>"
                "<div>3월 9일 정기 점검으로 예약 중단<br>이용 시간 06:00~22:00</div>"
                '<p><a href="/board/download.do?id=1">안내문.hwp</a></p>')
        record = parsed(body, title="2026년 상반기\n 예약 안내")
        self.assertEqual(record["official_url"],
                         "https://reservation.anseong.go.kr/index.do?board_id=notice&cp=%2Fboard%2Fview.do"
                         "&menu_id=0008&pageIndex=1&seq=96")
        self.assertEqual(record["title"], "2026년 상반기 예약 안내")
        self.assertEqual(record["body_lines"], ["예약 일정 : 3월 2일(월) 09:00", "관내 거주자 우선 배정",
                                                "3월 9일 정기 점검으로 예약 중단", "이용 시간 06:00~22:00", "안내문.hwp"])
        self.assertEqual(record["keyword_lines"], {
            "reservation_schedule": ["예약 일정 : 3월 2일(월) 09:00"],
            "priority": ["관내 거주자 우선 배정"],
            "suspension": ["3월 9일 정기 점검으로 예약 중단"],
        })
        self.assertEqual(record["links"], [{"href": "/board/download.do?id=1", "text": "안내문.hwp"}])
        self.assertEqual(record["review_flags"], ["link", "markup_unverified"])

    def test_inline_white_space_that_keeps_newlines_is_rejected(self):
        # 브라우저는 이 줄바꿈을 줄로 보이므로 합치면 예약기간과 이용기간이 섞인다.
        text = "예약기간: 3.2.~3.6.\n이용기간: 4.1.~6.30."
        for style in ("white-space: pre", "white-space:pre-wrap", "WHITE-SPACE: PRE-LINE", "white-space: break-spaces",
                      "white-space: normal !important", "white-space-collapse: preserve-breaks"):
            with self.subTest(style=style), self.assertRaisesRegex(ValueError, "허용하지 않는"):
                parsed(f'<p style="color: red; {style}">{text}</p>')
        # view_cont 자신과 pre 안의 지정도 받지 않는다.
        for text in (detail("96", text).replace('class="view_cont"', 'class="view_cont" style="white-space:pre-wrap"'),
                     detail("96", '<pre><span style="white-space: normal">가\n나</span></pre>')):
            with self.subTest(text=text[-90:]), self.assertRaisesRegex(ValueError, "허용하지 않는"):
                parse_detail(text, seq="96")
        # 실제 공지 원본에서 본 white-space 값은 normal뿐이다.
        self.assertEqual(parsed('<p style="white-space: normal">가</p><br style="white-space: normal">나')["body_lines"], ["가", "나"])

    def test_boxes_break_lines_and_unseen_layout_is_rejected(self):
        # 상자가 된 인라인 태그를 앞뒤 글과 붙이면 예약기간과 이용기간이 섞인다. 실제 원본에 없던 배치는 받지 않는다.
        for style in ("display:table-cell", "display: inherit", "float: left", "position: fixed", "visibility: collapse",
                      "display:inline-block;width:100%", "display:inline-block;inline-size:100%",
                      "display:inline-block;min-inline-size:100%", "display:inline-block;padding-right:100%",
                      "diſplay:block"):
            with self.subTest(style=style), self.assertRaisesRegex(ValueError, "허용하지 않는"):
                parsed(f'<p>예약기간: 3.2.<span style="{style}">이용기간: 4.1.</span></p>')
        # inline-block·block은 내용 길이·너비와 무관하게 앞뒤를 끊는다(README의 과분할). inline !important는 붙인다.
        body = ('<p>예약기간: 3.2.<span style="display: inline-block">이용기간: 4.1.~6.30. 매주 월요일 휴관</span>'
                '<span style="DISPLAY:block">다</span><span style="display: inline !important; float: none">라</span>'
                '<strong style="font-variant-position: inherit">마</strong></p>')
        self.assertEqual(parsed(body)["body_lines"], ["예약기간: 3.2.", "이용기간: 4.1.~6.30. 매주 월요일 휴관", "다", "라마"])

    def test_joined_source_newlines_are_flagged_for_review(self):
        # 외부 CSS의 white-space는 알 수 없으므로 합친 줄을 사람이 원문과 대조하게 한다.
        record = parsed("<p>예약기간: 3.2.~3.6.\n이용기간: 4.1.~6.30.</p>")
        self.assertEqual(record["body_lines"], ["예약기간: 3.2.~3.6. 이용기간: 4.1.~6.30."])
        self.assertEqual(record["review_flags"], ["markup_unverified", "source_newline_joined"])
        self.assertEqual(parsed("<p>가\r\n 나\r다</p>")["body_lines"], ["가 나 다"])
        # 태그 사이의 빈 줄바꿈은 줄을 합치지 않는다.
        record = parsed("<p>\n가\n</p>\n<p>나</p>")
        self.assertEqual((record["body_lines"], record["review_flags"]), (["가", "나"], ["markup_unverified"]))

    def test_image_only_restriction_is_flagged_for_review(self):
        record = parse_detail(detail("111", '<p><img src="/upload/limit.jpg" alt="이용 제한 안내"></p>',
                                     title="체육관 이용 제한 안내"), seq="111")
        self.assertEqual(record["body_lines"], [])
        self.assertEqual(record["images"], [{"src": "/upload/limit.jpg", "alt": "이용 제한 안내"}])
        self.assertEqual(record["keyword_lines"]["suspension"], ["체육관 이용 제한 안내"])
        self.assertEqual(record["review_flags"], ["image_only", "inline_image", "markup_unverified"])

    def test_detail_rejects_unverifiable_structure(self):
        for message, options in (
            ("일치하지", {"head": '<input name="seq" value="5">'}),
            ("제목", {"head": "<h4>메뉴</h4>"}),
            ("본문 영역", {"head": '<div class="view_cont">x</div>'}),
            ("글자와 이미지", {"body": "<p> </p>"}),
            ("허용하지 않는", {"body": "<iframe src=x></iframe>"}),
            ("허용하지 않는", {"body": '<p style="display: none">숨김</p>'}),
            ("허용하지 않는", {"body": "<img src=a src=b>"}),
            ("허용하지 않는", {"body": '<p style="display/**/:none">숨김</p>'}),
            ("상세 HTML 구조", {"head": "<!--><h4>숨김</h4>-->"}),
            *(("허용하지 않는", {"body": body}) for body in (
                "<table><tr><td>x</td></tr></table>", "<pre>x</pre>", "<p popover>x</p>", "<object><p>x</p></object>")),
            # 실제 제목 h4 안에는 태그가 없었다.
            *(("구조", {"title": title}) for title in ("<span>2026년</span> 안내", "예약<br>안내", "<b popover>x</b>안내")),
            ("구조", {"body": "<p><strong>x</p></strong>"}),
            ("구조", {"head": "<div><span></div></span>"}),
            ("구조", {"head": "<body hidden>"}),
        ):
            with self.subTest(options=options), self.assertRaisesRegex(ValueError, message):
                parsed(**options)
        with self.assertRaisesRegex(ValueError, "일치하지"):
            parse_detail(detail("95"), seq="96")
        page = detail("96")
        for text in (page.replace('value="96"', 'value="96" value="95"'), page.replace('type="hidden"', 'type="hidden" x')):
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, "구조"):
                parse_detail(text, seq="96")
        # 제목·본문의 조상도 실제 원본에서 본 표기만 받는다.
        for wrapper in ("<div hidden>", '<div style="display:none">', "<details>", "<div popover>", "<template>"):
            tag = wrapper[1:].split()[0].strip(">")
            for text in (page.replace("<h4>", wrapper + "<h4>").replace("</h4>", f"</h4></{tag}>"),
                         page.replace('<div class="view_cont">', wrapper + '<div class="view_cont">').replace(
                             "</body>", f"</{tag}></body>")):
                with self.subTest(text=text), self.assertRaisesRegex(ValueError, "구조|허용하지 않는"):
                    parse_detail(text, seq="96")

    def test_robots_rules_need_plain_rule_lines(self):
        rules = robots_rules(b"User-agent: *\nDisallow: /index.do?board_id=\n")
        self.assertFalse(allowed(rules, detail_url("1")))
        # 빈 파일과, 적용되지 않는 그룹의 이상한 값은 판단을 막지 않는다.
        for raw in (b"# empty\n\n", b"User-agent: other\nDisallow: x\n\nUser-agent: *\nDisallow: /admin/\n"):
            self.assertTrue(allowed(robots_rules(raw), detail_url("1")))
        for raw in (b"<html><h1>Request Blocked</h1></html>", "규칙".encode("cp949"),
                    b"User-agent: *\nCrawl-delay: soon\n", b"Error: Request Blocked\n",
                    b"User-agent: *\nDisallow: index.do\n", b"User-agent: yeogi-it\nAllow: https://x/\n"):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                robots_rules(raw)

    def test_robots_follow_rfc_9309_on_every_python(self):
        # 표준 라이브러리 robotparser가 3.13 또는 3.14에서 상세를 허용해 버리던 경우다.
        for raw, listing_allowed in (
            (b"User-agent: *\nAllow: /\nDisallow: /index.do\n", False),
            (b"User-agent: *\nDisallow: /x\n\nUser-agent: *\nDisallow: /index.do\n", False),
            (b"User-agent: *\nDisallow: /*.do\n", False),
            (b"User-agent: *\nDisallow: /*seq=\n", True),
            (b"User-agent: *\nAllow: /index.do?menu_id=\nDisallow: /index.do\n", True),
            (b"User-agent: *\nDisallow: /index.do?board_id=notice&cp=/board\n", True),
            (b"User-agent: yeogi\nDisallow:\n\nUser-agent: *\nDisallow: /index.do?b\n", True),
            (b"User-agent: YEOGI-IT/1.0\nDisallow: /index.do?b\n\nUser-agent: *\nDisallow:\n", True),
        ):
            with self.subTest(raw=raw):
                rules = robots_rules(raw)
                self.assertEqual(allowed(rules, LISTING_URL), listing_allowed)
                self.assertFalse(allowed(rules, detail_url("96")))
        rules = robots_rules(b"User-agent: *\nDisallow: /index.do$\nDisallow: /*seq=97$\nCrawl-delay: 2.5\n")
        self.assertEqual((allowed(rules, LISTING_URL), allowed(rules, detail_url("96"))), (True, True))
        self.assertFalse(allowed(rules, detail_url("97")))
        self.assertEqual(rules["delay"], 2.5)


class SportsBatchTest(unittest.TestCase):
    def setUp(self):
        self.private = Path(self.enterContext(TemporaryDirectory())).resolve()
        self.root = self.private / sports_batch.SPORTS_SECTION
        self.sleep = self.enterContext(patch("processing.collection.sports_batch.sleep"))
        self.robots = self.enterContext(patch("processing.collection.sports_batch.fetch_robots", return_value=ROBOTS))
        self.listing = self.enterContext(patch("processing.collection.sports_batch.fetch_listing"))
        self.detail = self.enterContext(patch("processing.collection.sports_batch.fetch_detail"))
        self.detail.side_effect = lambda seq, **_options: detail(seq).encode()

    def capture(self, name="run", **limits):
        summary = capture_sports_batch(name, self.root, **limits)
        receipt = json.loads((self.root / name / "batch.json").read_text(encoding="utf-8"))
        return summary, receipt, self.root / name

    def test_capture_keeps_raw_and_records_then_rereads_archive(self):
        self.listing.return_value = listing("111", "96")
        summary, receipt, directory = self.capture()
        self.assertEqual(summary, {"batch_id": "run", "status": "complete", "discovery_status": "first_page_only",
                                   "selected": 2, "parsed": 2})
        self.assertEqual((receipt["schema_version"], receipt["board"], receipt["robots"]["status"]),
                         ("citizen-sports-notice-batch-v1", "notice", "allowed"))
        self.assertEqual((directory / "robots.txt").read_bytes(), ROBOTS)
        self.assertEqual(receipt["pages"][0]["sha256"], hashlib.sha256(listing("111", "96")).hexdigest())
        self.assertEqual(receipt["pages"][0]["source_url"], "https://reservation.anseong.go.kr/index.do?menu_id=0008")
        self.assertEqual([item["web_id"] for item in receipt["items"]], ["111", "96"])
        parsed = json.loads((directory / "parsed-96.json").read_text(encoding="utf-8"))
        self.assertEqual((parsed["parser_version"], parsed["record"]["external_id"]), ("sports-notice-parser-v6", "96"))

        assets = read_sports_batch(self.private, "run")
        self.assertEqual(list(assets), ["111", "96"])
        self.assertEqual(assets["96"]["raw_asset_path"], "collection-sports-notices/run/detail-96.html")
        self.assertEqual(assets["96"]["record"], parsed["record"])

        changed = dict(parsed, record={**parsed["record"], "title": "바뀐 제목"})
        (directory / "parsed-96.json").write_text(json.dumps(changed, ensure_ascii=False), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "파싱 결과가 원본과 다릅니다"):
            read_sports_batch(self.private, "run")
        (directory / "detail-96.html").write_bytes(detail("96", title="다른 제목").encode())
        with self.assertRaisesRegex(ValueError, "해시"):
            read_sports_batch(self.private, "run")

    def test_unconfirmed_robots_stops_before_page_requests(self):
        for name, side_effect, status in (
            ("blocked", SourceHTTPError(400, "체육시설 robots.txt"), "fetch_failed"),
            ("html", [b"<html>Request Blocked</html>"], "parse_failed"),
            ("denied", [b"User-agent: *\nDisallow: /index.do\n"], "disallowed"),
        ):
            with self.subTest(name=name):
                self.robots.side_effect = side_effect
                summary, receipt, _ = self.capture(name)
                self.assertEqual((summary["status"], summary["discovery_status"], summary["selected"]),
                                 ("partial", "robots_not_allowed", 0))
                self.assertEqual((receipt["robots"]["status"], receipt["pages"]), (status, []))
                self.assertEqual(read_sports_batch(self.private, name), {})
        self.assertIn("HTTP 응답 오류(400)", json.loads((self.root / "blocked" / "batch.json").read_text())["robots"]["error"])
        self.listing.assert_not_called()
        self.detail.assert_not_called()

    def test_detail_failures_robots_rules_and_limits(self):
        self.robots.return_value = b"User-agent: *\nDisallow: /index.do?board_id=notice&cp=%2Fboard%2Fview.do&menu_id=0008&pageIndex=1&seq=2\n"
        self.listing.return_value = listing("1", "2", "3", "4")
        self.detail.side_effect = [detail("99").encode(), SourceHTTPError(429)]
        summary, receipt, directory = self.capture(max_items=3)
        self.assertEqual((summary["status"], summary["discovery_status"], summary["parsed"]), ("partial", "item_limit", 0))
        self.assertEqual([item["status"] for item in receipt["items"]], ["parse_failed", "not_attempted", "fetch_failed"])
        self.assertIn("robots.txt", receipt["items"][1]["error"])
        self.assertEqual((directory / "detail-1.html").read_bytes(), detail("99").encode())
        self.assertEqual(receipt["stop_http_status"], 429)
        self.assertEqual([call.args for call in self.detail.call_args_list], [("1",), ("3",)])
        self.assertEqual(read_sports_batch(self.private, "run"), {})

    def test_waf_block_and_crawl_delay(self):
        self.robots.return_value = b"User-agent: *\nCrawl-delay: 30\nDisallow: /admin/\n"
        self.listing.return_value = listing("1", "2", "3")
        self.detail.side_effect = SourceHTTPError(400, "체육시설 공지 상세")
        _, receipt, _ = self.capture()
        self.assertEqual([item["status"] for item in receipt["items"]], ["fetch_failed", "not_attempted", "not_attempted"])
        self.assertEqual(receipt["stop_http_status"], 400)
        self.assertEqual(self.detail.call_count, 1)
        self.assertEqual([call.args for call in self.sleep.call_args_list], [(30.0,), (30.0,)])

    def test_listing_failure_keeps_original(self):
        self.listing.return_value = b"<html><a href='javascript:fnView(96)'>x</a></html>"
        summary, receipt, directory = self.capture()
        self.assertEqual((summary["discovery_status"], receipt["pages"][0]["status"]), ("failed", "parse_failed"))
        self.assertTrue((directory / "list-1.html").exists())
        self.detail.assert_not_called()

    def test_cli_exit_codes(self):
        self.listing.return_value = listing("5")
        runs = ((["--name", "cli"], 0, {"batch_id": "cli", "status": "complete"}),
                (["--name", "cli", "--verify"], 0, {"batch_id": "cli", "verified": ["5"]}),
                (["--name", "none", "--verify"], 1, None), (["--name", "cli"], 1, None))
        with patch.object(sports_batch, "SPORTS_ROOT", self.root):
            for argv, code, output in runs:
                with (self.subTest(argv=argv), patch("sys.argv", ["sports_batch", *argv]),
                      contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO())):
                    self.assertEqual(sports_batch.main(), code)
                    if output:
                        self.assertLessEqual(output.items(), json.loads(out.getvalue()).items())
        self.robots.side_effect = SourceHTTPError(400, "체육시설 robots.txt")
        with (patch.object(sports_batch, "SPORTS_ROOT", self.root), patch("sys.argv", ["x", "--name", "blocked"]),
              contextlib.redirect_stdout(io.StringIO())):
            self.assertEqual(sports_batch.main(), 2)

if __name__ == "__main__":
    unittest.main()
