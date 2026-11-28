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

# 합성 원본. 구조·링크·표기는 2026-11-29 실제 원본(목록 1쪽·상세 5건)을 따른다. 메뉴의 닫히지 않은 li, 남는 `</li>`,
# `</nav>`가 닫는 숨긴 li, `</br>`, 상세의 겹친 댓글 form도 실제와 같은 꼴이다.
_LINK = "/index.do?menu_id=0008&cp=/board/view.do&pageIndex=1&seq={}&board_id=notice&searchCondition=&searchKeyword="
ROBOTS = b"User-agent: *\nDisallow: /admin/\n"
_CHROME = ('<header id="header"><nav><ul class="gnb"><li data-menu-group="0004"><a href="/index.do?menu_id=0008">커뮤니티</a>'
           '<ul class="sub_menu"><li><a href="/index.do?menu_id=0008">공지사항</a></li></li></ul><li style="display:none;">'
           '<a href="/index.do?menu_id=0015">회원관리</a></nav></header><aside><ul><li><a href="/index.do?menu_id=0044">'
           '<span>나의</br>예약 관리</span></a></li></ul></aside>')


def listing(*seqs, extra=""):
    rows = "".join(f'<li><span class="date"><i>16</i>2026.10</span><a class="subject" data-button="boardView" '
                   f'data-board-seq="{seq}" href="{_LINK.format(seq)}"><em class=\'notice\'>공지</em> 공지 {seq}</a></li>'
                   for seq in seqs)
    return (f'<html lang="ko"><head><title></title></head><body class="body_bg ">{_CHROME}<div id="container">'
            f'<div id="content"><form id="gnBoardVOL" class="gn-mx-5" action="/index.do;jsessionid=A?menu_id=0008" '
            f'method="post"><ul class="bbsList">{rows}</ul></form>{extra}</div></div></body></html>').encode()


def detail(seq, body="<p>예약 일정 : 3월 2일(월) 09:00 예약 오픈</p>", title="체육관 예약 안내", head=""):
    return (f'<html lang="ko"><head><script>var h3 = "<h3 class=bbsTitle>";</script></head><body class="body_bg ">'
            f'{_CHROME}{head}<div id="container"><div id="content"><form id="gnBoardVO" action="/index.do" method="post">'
            f'<input type="hidden" id="seq" name="seq" value="{seq}" /><h3 class="bbsTitle">{title}</h3>'
            f'<table class="bbsView"><caption>게시판 상세보기</caption><tbody><tr><td colspan="4" class="conts">'
            f'<div class="conts"><div class="img"></div>{body}</div></td></tr></tbody></table><div class="commentArea">'
            f'<form id="commentVOL" method="post"></form></div></form><div id="checkPassword" style="display:none;">'
            f'<h4 class="modal-title">비밀번호 확인</h4></div></div></div></body></html>')


def parsed(*args, **options):
    return parse_detail(detail("96", *args, **options), seq="96")


class SportsParserTest(unittest.TestCase):
    def test_listing_reads_detail_links_in_order(self):
        raw = listing("111", "96", extra='<div hidden><div><a href="/index.do?menu_id=0001">메뉴</a></div></div><br hidden>'
                      '<div><span></div></span>'
                      '<a href="https://example.com/index.do?seq=3">외부</a><a href="http://[x/index.do?seq=4">깨짐</a>')
        self.assertEqual(parse_listing(raw), ["111", "96"])

    def test_listing_rejects_unexpected_shapes(self):
        cases = {
            "형식": listing("1", extra='<a href="/index.do?board_id=notice&seq=2">x</a>'),
            "상세 링크 형식": listing("1", extra=f'<a href="https://reservation.anseong.go.kr{_LINK.format(2)}">x</a>'),
            "같은 공지": listing("1", "1"),
            "찾지 못했": listing(),
            "UTF-8": "<a>공지</a>".encode("cp949"),
            "목록 HTML 구조": listing("1", extra='<p class="a"\xa0id="b">x</p>'),
            "링크 형식": listing("1").replace(b"pageIndex=1", b"pageIndex=2"),
            "링크 형식이": listing("1", extra=f'<a href="{_LINK.format(7).replace("x.do", "x.do;jsessionid=A")}">x</a>'),
        }
        for message, raw in cases.items():
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                parse_listing(raw)
        link = f'<a href="{_LINK.format(2)}">x</a>'
        for extra in (f'<div style="display: none"><div></div>{link}</div>', f'<p>{link}</p>', f"<details open>{link}</details>",
                      link.replace("<a", "<a hidden"), link.replace("<a", "<a popover"), f'<div popover>{link}</div>',
                      f'<div style="display/**/:none">{link}</div>',
                      f'<div style="height: 50px">{link}</div>', f'<ul><li style="display:none;">{link}</li></ul>',
                      # 남는 `</li>`는 범위 밖이라 버려지고 링크는 숨긴 li 안에 남는다. `</div>`도 칸을 넘어 닫지 못한다.
                      f'<ul><li hidden><ul><li></li></li></ul>{link}</li></ul>',
                      f'<div hidden><table><tbody><tr><td></div>{link}</td></tr></tbody></table></div>',
                      *(f'<{tag}>{link}</{tag}>' for tag in "details dialog object".split())):
            with self.subTest(extra=extra), self.assertRaisesRegex(ValueError, "허용 목록 밖"):
                parse_listing(listing("1", extra=extra))
        # 브라우저가 서식 요소를 다시 열거나 요소를 닫고 옮길 표기, 닫히지 않은 요소, 뒤 body 속성, 켈빈 기호(U+212A) 태그.
        for extra in ("<div><b></div></b>", "<b><i></b></i>", "<p><div></div></p>", "<div><li></li></div>",
                      '<a href="#"><a href="#">x</a></a>', f"<table><tr><td>{link}</td></tr></table>", "<template></template>",
                      "<div>", "<body hidden>", "<frameset></frameset>",
                      f"<lin\u212a hidden>{link}", f"<ak hidden>x</a\u212a>{link}"):
            with self.subTest(extra=extra), self.assertRaisesRegex(ValueError, "목록 HTML 구조"):
                parse_listing(listing("1", extra=extra))
        # `form#gnBoardVOL > ul.bbsList > li > a.subject` 밖 링크(팝업 등)도 거부한다.
        for message, old, new in (("허용 목록 밖", b"</em>", b"</em><i>x</i>"), ("구조", b"</a>", b"</br></a>"),
                                  *(("구조", old, b"x") for old in (b"subject", b"bbsList", b"gnBoardVOL", b"<li>")),
                                  ("구조", b"</form>", f'</form><div id="popup">{link}</div>'.encode())):
            with self.subTest(new=new), self.assertRaisesRegex(ValueError, message):
                parse_listing(listing("1").replace(old, new))

    def test_detail_keeps_display_text_verbatim(self):
        body = ('<p>예약 일정 : 3월 2일(월) 09:00</p><p>관내 거주자 <span style="font-weight: bolder;">우선</span>&nbsp;배정</p>'
                "<div>3월 9일 정기 점검으로 예약 중단<br>이용 시간 06:00~22:00</div>"
                '<p><font color="#666666" face="NanumSquareRoundExtraBold">일반(누구나) 예약: 11.30일(09:00부터) ~</font></p>')
        record = parsed(body, title="2026년 상반기\n 예약 안내")
        self.assertEqual(record["official_url"], "https://reservation.anseong.go.kr" + _LINK.format(96))
        self.assertEqual(record["title"], "2026년 상반기 예약 안내")
        self.assertEqual(record["body_lines"], [
            "예약 일정 : 3월 2일(월) 09:00", "관내 거주자 우선 배정", "3월 9일 정기 점검으로 예약 중단", "이용 시간 06:00~22:00",
            "일반(누구나) 예약: 11.30일(09:00부터) ~"])
        # 이용 시간 줄은 예약 일정에 넣지 않는다.
        self.assertEqual(record["keyword_lines"], {
            "reservation_schedule": ["예약 일정 : 3월 2일(월) 09:00", "일반(누구나) 예약: 11.30일(09:00부터) ~"],
            "priority": ["관내 거주자 우선 배정"], "suspension": ["3월 9일 정기 점검으로 예약 중단"]})
        self.assertEqual(record["review_flags"], ["source_newline_joined"])

    def test_newline_keeping_white_space_is_rejected(self):
        text = "예약기간: 3.2.~3.6.\n이용기간: 4.1.~6.30."
        for style in ("white-space: pre", "white-space:pre-wrap", "WHITE-SPACE: PRE-LINE", "white-space: break-spaces",
                      "white-space: normal !important", "white-space-collapse: preserve-breaks"):
            with self.subTest(style=style), self.assertRaisesRegex(ValueError, "허용하지 않는"):
                parsed(f'<p style="color: rgb(102, 102, 102); {style}">{text}</p>')
        for text in (detail("96", text).replace('<div class="conts">', '<div class="conts" style="white-space:pre-wrap">'),
                     detail("96", '<pre><span style="white-space: normal">가\n나</span></pre>')):
            with self.subTest(text=text[-90:]), self.assertRaisesRegex(ValueError, "허용하지 않는"):
                parse_detail(text, seq="96")
        style = "letter-spacing: 0.1px; color: rgb(102, 102, 102); font-family: NanumSquareRoundExtraBold;"
        self.assertEqual(parsed(f'<p style="{style}">가</p><br>나')["body_lines"], ["가", "나"])

    def test_headings_break_lines_and_unseen_layout_is_rejected(self):
        for style in ("display:table-cell", "display: inherit", "float: left", "position: fixed", "visibility: collapse",
                      "display:inline-block;width:100%", "display:inline-block;inline-size:100%",
                      "display:inline-block;min-inline-size:100%", "display:inline-block;padding-right:100%",
                      "diſplay:block"):
            with self.subTest(style=style), self.assertRaisesRegex(ValueError, "허용하지 않는"):
                parsed(f'<p>예약기간: 3.2.<span style="{style}">이용기간: 4.1.</span></p>')
        # 실제 seq=110처럼 h1 안의 p·div도 줄을 끊고 span·font는 잇는다.
        body = ('<h1 style="letter-spacing: 0.1px;"> <span style="font-family: 함초롬바탕;">점검 안내</span></h1><h1>'
                '<p class="0" style="font-size: 16px;"><span>예약기간</span><span lang="EN-US" style="letter-spacing: 0pt;">: '
                '</span><font face="함초롬바탕">3.2.</font></p><div id="hwpEditorBoardContent" class="hwp_editor_board_content" '
                'data-hjsonver="1.0" data-jsonlen="10"></div><p>이용기간: 4.1.~6.30.</p></h1>')
        self.assertEqual(parsed(body)["body_lines"], ["점검 안내", "예약기간: 3.2.", "이용기간: 4.1.~6.30."])

    def test_joined_source_newlines_are_flagged(self):
        record = parsed("<p>예약기간: 3.2.~3.6.\n이용기간: 4.1.~6.30.</p>")
        self.assertEqual(record["body_lines"], ["예약기간: 3.2.~3.6. 이용기간: 4.1.~6.30."])
        self.assertEqual(record["review_flags"], ["source_newline_joined"])
        self.assertEqual(parsed("<p>가\r\n 나\r다</p>")["body_lines"], ["가 나 다"])
        # 태그 사이 줄바꿈은 합치지 않는다.
        record = parsed("<p>\n가\n</p>\n<p>나</p>", title="\r\n제목\n")
        self.assertEqual((record["body_lines"], record["review_flags"]), (["가", "나"], []))
        self.assertIn("source_newline_joined", parsed(title="접수기간 3.2.\r이용기간 4.1.")["review_flags"])

    def test_image_only_restriction_is_flagged(self):
        image = ('<p> <br></p><p style="" data-loading-node=""><img src="/data/upload/limit.jpg" '
                 'style="opacity: 1; max-width: 100%;" data-editor-image="edit" data-file-cnt="1"></p>')
        record = parse_detail(detail("111", image, title="체육관 이용 제한 안내"), seq="111")
        self.assertEqual((record["body_lines"], record["images"], record["keyword_lines"]["suspension"]),
                         ([], [{"src": "/data/upload/limit.jpg"}], ["체육관 이용 제한 안내"]))
        self.assertEqual(record["review_flags"], ["image_only", "inline_image"])

    def test_detail_rejects_unverifiable_structure(self):
        for message, options in (
            ("일치하지", {"head": '<input name="seq" value="5">'}),
            ("제목", {"head": '<h3 class="bbsTitle">메뉴</h3>'}),
            ("본문 영역", {"body": '가</div><div class="conts">나'}), ("구조", {"head": '<div class="conts">x</div>'}),
            ("글자와 이미지", {"body": "<p> </p>"}),
            ("상세 HTML 구조", {"head": "<!--><h4>숨김</h4>-->"}),
            *(("허용하지 않는", {"body": body}) for body in (
                "<iframe src=x></iframe>", '<p style="display: none">숨김</p>', "<img src=a src=b>",
                '<p style="display/**/:none">숨김</p>', '<p style="mso-a{}display:none">숨김</p>',
                "<table><tr><td>x</td></tr></table>", "<pre>x</pre>", "<p popover>x</p>", "<object><p>x</p></object>",
                "<p>가<div>나</div></p>", "<ul><li><div><li>가</li></div></li></ul>", "<h1><h2>가</h2></h1>",
                "<h1><h1>가</h1></h1>", '<a href="/x">안내문</a>', "<strong>x</strong>", '<img src="a" alt="b">',
                '<font face="a;display:none">x</font>', '<font size="7">x</font>', '<span style="color: white">x</span>')),
            *(("구조", {"title": title}) for title in ("<span>2026년</span> 안내", "예약<br>안내", "<b popover>x</b>안내", "예약\u2029안내", "예약\x1c일정")),
            *(("구조", {"body": f"<p>가{c}나</p>"})
              for c in ("\u2028", "&#x2028;", "&#8233;", "\x85", "\x0b", "&#11;", "&#xC;", "\x1c", "\x1f", "&#28;", "&#x1F;")),
            ("구조", {"body": "<p><span>x</p></span>"}), ("구조", {"body": "가</br>나"}),
            # 숨긴 form을 `</form>`이 스택에서 빼면 안쪽 요소의 조상이 사라진다.
            *(("구조", {"head": head}) for head in ("<div><b></div></b>", "<body hidden>", "<lin\u212a hidden>",
                                                   "<ak hidden>x</a\u212a>", "<form hidden><div><form></form></div>")),
        ):
            with self.subTest(options=options), self.assertRaisesRegex(ValueError, message):
                parsed(**options)
        with self.assertRaisesRegex(ValueError, "일치하지"):
            parse_detail(detail("95"), seq="96")
        page = detail("96")
        for text in (page.replace('value="96"', 'value="96" value="95"'), page.replace('type="hidden"', 'type="hidden" x'),
                     page.replace('<h3 class="bbsTitle">', '<h3 class="bbsTitle" id="t">'), page.replace('4" class="conts', '4" class="c')):
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, "구조"):
                parse_detail(text, seq="96")
        for wrapper in ("<div hidden>", '<div style="display:none">', "<details>", "<div popover>", "<template>",
                        '<div style="height: 50px">'):
            tag = wrapper[1:].split()[0].strip(">")
            for text in (page.replace('<h3 class="bbsTitle">', wrapper + '<h3 class="bbsTitle">').replace(
                             "</h3>", f"</h3></{tag}>"),
                         page.replace('<div class="conts">', wrapper + '<div class="conts">').replace("</td>", f"</{tag}></td>")):
                with self.subTest(text=text), self.assertRaisesRegex(ValueError, "구조|허용하지 않는"):
                    parse_detail(text, seq="96")

    def test_robots_rules_need_plain_rule_lines(self):
        rules = robots_rules(b"User-agent: *\nDisallow: /index.do?menu_id=0008&cp=\n")
        self.assertFalse(allowed(rules, detail_url("1")))
        for raw in (b"# empty\n\n", b"User-agent: other\nDisallow: x\n\nUser-agent: *\nDisallow: /admin/\n",
                    "# 안내\u3000\x85\nUser-agent: *\nDisallow: /admin/\n".encode()):
            self.assertTrue(allowed(robots_rules(raw), detail_url("1")))
        for raw in (b"<html><h1>Request Blocked</h1></html>", "규칙".encode("cp949"),
                    b"User-agent: *\nCrawl-delay: soon\n", b"Error: Request Blocked\n",
                    b"User-agent: *\nDisallow: index.do\n", b"User-agent: yeogi-it\nAllow: https://x/\n",
                    *(f"User-agent: *\nDisallow: /index\nAllow: /index.do{c}\n".encode() for c in "\xa0\u3000\x85\x1c\u2028"),
                    b"User-agent: yeogi-it, otherbot\nDisallow: /\n", b"User-agent: yeogi-it;\nDisallow: /\n",
                    b"User-agent: * all\nDisallow: /\n", b"User-agent: *\nDisalow: /\n",
                    b"User-agent: *\nDissallow: /\n", b"User-agent: *\nDisallowed: /index.do\n"):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                robots_rules(raw)

    def test_robots_follow_rfc_9309_on_every_python(self):
        # 표준 robotparser가 허용하던 경우 등.
        for raw, listing_allowed in (
            (b"User-agent: *\nAllow: /\nDisallow: /index.do\n", False),
            (b"User-agent: *\nDisallow: /x\n\nUser-agent: *\nDisallow: /index.do\n", False),
            (b"User-agent: *\nDisallow: /*.do\n", False),
            (b"User-agent: *\nDisallow: /*seq=\n", True),
            (b"User-agent: *\nAllow: /index.do?menu_id=0008$\nDisallow: /index.do\n", True),
            (b"User-agent: *\nDisallow: /index.do?menu_id=0008&cp=%2Fboard\n", True),
            (b"User-agent: yeogi\nDisallow:\n\nUser-agent: *\nDisallow: /index.do?menu_id=0008&\n", True),
            (b"User-agent: YEOGI-IT/1.0\nDisallow: /index.do?menu_id=0008&\n\nUser-agent: *\nDisallow:\n", True),
            (b"User-agent: *\nCrawl-delay: 5\nUser-agent: badbot\nDisallow: /\n", False),
            (b"User-agent: *\r\nDisallow: /index.do\rAllow: /\n", False),
            (b"User-agent: *\nDisallow: /index.do?menu_id=%30\nAllow: /index.do?menu_id=000%2A\n"
             b"Allow: /index.do?menu_id=0008%24\nDisallow: /*seq\n", False),
        ):
            with self.subTest(raw=raw):
                rules = robots_rules(raw)
                self.assertEqual(allowed(rules, LISTING_URL), listing_allowed)
                self.assertFalse(allowed(rules, detail_url("96")))
        rules = robots_rules(b"User-agent: *\nDisallow: /index.do$\nDisallow: /*seq=97&\nCrawl-delay: 2.5\n")
        self.assertEqual((allowed(rules, LISTING_URL), allowed(rules, detail_url("96"))), (True, True))
        self.assertFalse(allowed(rules, detail_url("97")))
        self.assertEqual(rules["delay"], 2.5)


class SportsBatchTest(unittest.TestCase):
    def setUp(self):
        self.private = Path(self.enterContext(TemporaryDirectory())).resolve()
        self.root = self.private / sports_batch.SPORTS_SECTION
        self.sleep = self.enterContext(patch.object(sports_batch, "sleep"))
        self.robots = self.enterContext(patch.object(sports_batch, "fetch_robots", return_value=ROBOTS))
        self.listing = self.enterContext(patch.object(sports_batch, "fetch_listing"))
        self.detail = self.enterContext(patch.object(sports_batch, "fetch_detail"))
        self.detail.side_effect = lambda seq, **_options: detail(seq).encode()

    def capture(self, name="run", **limits):
        summary = capture_sports_batch(name, self.root, **limits)
        receipt = json.loads((self.root / name / "batch.json").read_text(encoding="utf-8"))
        return summary, receipt, self.root / name

    def rejects(self, name, filename, data=b"x"):
        path = self.root / name / filename
        original, data = path.read_bytes(), data if isinstance(data, bytes) else json.dumps(data).encode()
        for change in (lambda: path.write_bytes(data), path.unlink):
            change()
            with self.assertRaises(ValueError):
                read_sports_batch(self.private, name)
            path.write_bytes(original)
            path.chmod(0o600)
            read_sports_batch(self.private, name)

    def test_capture_then_verify_archive(self):
        self.listing.return_value = listing("111", "96")
        summary, receipt, directory = self.capture()
        self.assertEqual(summary, {
            "batch_id": "run", "status": "complete", "discovery_status": "first_page_only", "selected": 2, "parsed": 2})
        self.assertEqual((receipt["schema_version"], receipt["board"], receipt["robots"]["status"]),
                         ("citizen-sports-notice-batch-v2", "notice", "allowed"))
        self.assertEqual((directory / "robots.txt").read_bytes(), ROBOTS)
        page = receipt["pages"][0]
        self.assertEqual((page["sha256"], page["source_url"]), (hashlib.sha256(listing("111", "96")).hexdigest(),
                                                                "https://reservation.anseong.go.kr/index.do?menu_id=0008"))
        self.assertEqual([item["web_id"] for item in receipt["items"]], ["111", "96"])
        parsed = json.loads((directory / "parsed-96.json").read_text(encoding="utf-8"))
        self.assertEqual((parsed["parser_version"], parsed["record"]["external_id"]), ("sports-notice-parser-v8", "96"))

        assets = read_sports_batch(self.private, "run")
        self.assertEqual(list(assets), ["111", "96"])
        self.assertEqual(assets["96"]["raw_asset_path"], "collection-sports-notices/run/detail-96.html")
        self.assertEqual(assets["96"]["record"], parsed["record"])
        self.rejects("run", "batch.json", {**receipt, "items": [], "selected": 0, "parsed": 0})

        changed = dict(parsed, record={**parsed["record"], "title": "바뀐 제목"})
        (directory / "parsed-96.json").write_text(json.dumps(changed, ensure_ascii=False), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "파싱 결과가 원본과 다릅니다"):
            read_sports_batch(self.private, "run")
        first = directory / "parsed-111.json"
        kept = first.read_bytes()  # 지금 파서가 거부해도 버전 오류다.
        first.write_text(json.dumps(dict(json.loads(kept), parser_version="v6")), encoding="utf-8")
        with patch.object(sports_batch, "parse_detail", side_effect=ValueError), self.assertRaisesRegex(ValueError, "다른 파서"):
            read_sports_batch(self.private, "run")
        first.write_bytes(kept)
        (directory / "detail-96.html").write_bytes(detail("96", title="다른 제목").encode())
        with self.assertRaisesRegex(ValueError, "해시"):
            read_sports_batch(self.private, "run")

    def test_unconfirmed_robots_stops_requests(self):
        for name, side_effect, status in (
            ("throttled", SourceHTTPError(429, "체육시설 robots.txt"), "fetch_failed"),
            ("down", SourceHTTPError(503, "체육시설 robots.txt"), "fetch_failed"),
            ("offline", ValueError("체육시설 robots.txt 응답을 받지 못했습니다."), "fetch_failed"),
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
                for change in ({"status": "complete"}, {"robots": {**receipt["robots"], "status": "allowed"}},
                               {"robots": {**receipt["robots"], "status": "unavailable", "http_status": 429}}):
                    self.rejects(name, "batch.json", {**receipt, **change})
                if status != "fetch_failed":
                    self.rejects(name, "robots.txt")
                else:  # 원본 없는 기록은 주소·키까지 맞아야 한다.
                    for change in ({"source_url": "x"}, {"http_status": None}, {"sha256": "0" * 64}):
                        self.rejects(name, "batch.json", {**receipt, "robots": {**receipt["robots"], **change}})
        self.assertIn("HTTP 응답 오류(429)", json.loads((self.root / "throttled" / "batch.json").read_text())["robots"]["error"])
        self.listing.assert_not_called()
        self.detail.assert_not_called()

    def test_robots_4xx_is_unavailable_and_allows_all(self):
        # RFC 9309 2.3.1.3. 실제 robots.txt는 HTTP 400 "Request Blocked"였다.
        self.listing.return_value = listing("111", "96")
        for code in (400, 404):
            with self.subTest(code=code):
                self.robots.side_effect = SourceHTTPError(code, "체육시설 robots.txt")
                summary, receipt, directory = self.capture(f"r{code}")
                self.assertEqual((summary["status"], summary["parsed"]), ("complete", 2))
                self.assertEqual(receipt["robots"], {
                    "source_url": "https://reservation.anseong.go.kr/robots.txt", "status": "unavailable",
                    "error": f"체육시설 robots.txt HTTP 응답 오류({code}).", "http_status": code})
                self.assertFalse((directory / "robots.txt").exists())
                self.assertEqual(list(read_sports_batch(self.private, f"r{code}")), ["111", "96"])
        self.assertEqual([call.args for call in self.sleep.call_args_list], [(1.5,)] * 6)
        robots = receipt["robots"]
        for change in ({**robots, "http_status": 400}, {**robots, "http_status": "404"}, {**robots, "http_status": 404.0},
                       {**robots, "status": "fetch_failed"}, {**robots, "error": "x"}, {"source_url": robots["source_url"],
                       "status": "unavailable", "error": robots["error"]}, {**robots, "file": "robots.txt"},
                       {**robots, "http_status": 429, "error": str(SourceHTTPError(429, "체육시설 robots.txt"))},
                       {**robots, "source_url": "https://evil.example/robots.txt"}, {**robots, "sha256": "0" * 64},
                       {**robots, "fetched_at": "x"}):
            self.rejects("r404", "batch.json", {**receipt, "robots": change})

    def test_detail_failures_robots_rules_and_limits(self):
        self.robots.return_value = b"User-agent: *\nDisallow: /*seq=2&\n"
        self.listing.return_value = listing("1", "2", "3", "4")
        self.detail.side_effect = [detail("99").encode(), SourceHTTPError(429, "체육시설 공지 상세")]
        summary, receipt, directory = self.capture(max_items=3)
        self.assertEqual((summary["status"], summary["discovery_status"], summary["parsed"]), ("partial", "item_limit", 0))
        self.assertEqual(([item["status"] for item in receipt["items"]], receipt["stop_http_status"]),
                         (["parse_failed", "not_attempted", "fetch_failed"], 429))
        self.assertIn("robots.txt", receipt["items"][1]["error"])
        self.assertEqual((directory / "detail-1.html").read_bytes(), detail("99").encode())
        self.assertEqual([call.args for call in self.detail.call_args_list], [("1",), ("3",)])
        self.assertEqual(read_sports_batch(self.private, "run"), {})
        for filename in ("robots.txt", "list-1.html", "detail-1.html"):
            self.rejects("run", filename)
        first, denied, failed = receipt["items"]
        # 중단 없는 건너뜀, 막힌 주소 요청, 틀린 중단 상태.
        for change in ({"items": [{**first, "status": "fetch_failed"}, denied, failed]}, {"stop_http_status": None},
                       {"items": [first, {**denied, "status": "fetch_failed"}, failed]},
                       {"items": [first, denied, {**failed, "status": "not_attempted"}]}):
            self.rejects("run", "batch.json", {**receipt, **change})

    def test_waf_block_and_crawl_delay(self):
        self.robots.return_value = b"User-agent: *\nCrawl-delay: 30\nDisallow: /admin/\n"
        self.listing.return_value = listing("1", "2", "3")
        self.detail.side_effect = SourceHTTPError(400, "체육시설 공지 상세")
        _, receipt, _ = self.capture()
        self.assertEqual([item["status"] for item in receipt["items"]], ["fetch_failed", "not_attempted", "not_attempted"])
        self.assertEqual((receipt["stop_http_status"], self.detail.call_count), (400, 1))
        self.assertEqual([call.args for call in self.sleep.call_args_list], [(30.0,), (30.0,)])
        failed, *rest = receipt["items"]
        for change in ({"stop_http_status": 429}, {"items": [{**failed, "error": "x"}, *rest], "stop_http_status": None}):
            self.rejects("run", "batch.json", {**receipt, **change})

    def test_listing_failure_keeps_original(self):
        self.listing.return_value = b"<html><a href='javascript:fnView(96)'>x</a></html>"
        summary, receipt, directory = self.capture()
        self.assertEqual((summary["discovery_status"], receipt["pages"][0]["status"]), ("failed", "parse_failed"))
        self.assertTrue((directory / "list-1.html").exists())
        self.rejects("run", "list-1.html")
        receipt["pages"][0]["status"] = "fetch_failed"
        self.rejects("run", "batch.json", receipt)
        self.listing.side_effect = SourceHTTPError(429, "체육시설 공지 목록")
        _, receipt, _ = self.capture("stopped")
        self.rejects("stopped", "batch.json", {**receipt, "stop_http_status": None})
        self.detail.assert_not_called()

    def test_cli_exit_codes(self):
        self.listing.return_value = listing("5")
        self.robots.side_effect = [ROBOTS, SourceHTTPError(503, "체육시설 robots.txt")]
        runs = ((["--name", "cli"], 0, {"batch_id": "cli", "status": "complete"}),
                (["--name", "cli", "--verify"], 0, {"batch_id": "cli", "verified": ["5"]}),
                (["--name", "none", "--verify"], 1, None), (["--name", "cli"], 1, None), (["--name", "blocked"], 2, None))
        with patch.object(sports_batch, "SPORTS_ROOT", self.root):
            for argv, code, output in runs:
                with (self.subTest(argv=argv), patch("sys.argv", ["sports_batch", *argv]),
                      contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO())):
                    self.assertEqual(sports_batch.main(), code)
                    if output:
                        self.assertLessEqual(output.items(), json.loads(out.getvalue()).items())

if __name__ == "__main__":
    unittest.main()
