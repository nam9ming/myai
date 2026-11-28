import contextlib
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from processing.collection import arthall_batch
from processing.collection.arthall import PARSER_VERSION, detail_url, listing_path, parse_detail, parse_listing
from processing.collection.arthall_batch import capture_arthall_batch, read_arthall_batch
from processing.collection.official_web import SourceHTTPError

_ACTION = "/arthall/concert/list.do?scCategory=&amp;mId=0202010100"


def _item(concert_id):
    return f"""<ul><li><div class="m_title"><span class="category_program">기획</span><h4>합성 공연</h4></div>
      <div class="con_listInfo"><h4>합성 공연</h4><ul><li><span class="title">기간</span><span class="sub">x</span></li></ul></div>
      <div class="fR"><button data-button="booking" data-idx="{concert_id}" data-goods="1">예매하기</button>
      <button class="mL10" onclick="go_view('{concert_id}'); return false;" title="상세">자세히보기</button></div></li></ul>"""


def listing(*ids, year=2026, month=12, page=1, total=1, action=_ACTION, pager=None):
    items = "".join(_item(item) for item in ids) or "<ul><li>\n검색된 전체일정이 없습니다.\n</li></ul>"
    if pager is None:
        pager = "".join(f"<span>{number}</span>" if number == page else
                        f'<a href="#" onclick="goPage({number}); return false;" title="{number}페이지로 이동">{number}</a>'
                        for number in range(1, total + 1))
    pages = f'<div class="bod_page">{pager}</div>' if ids else ""
    return f"""<html><body><script>function go_view(idx) {{ location.href = 'x<y'; }}</script>
    <form id="listForm" name="listForm" action="{action}" method="POST">
      <input id="idx" name="idx" type="hidden" value=""/><input id="year" name="year" type="hidden" value="{year}"/>
      <input id="month" name="month" type="hidden" value="{month:02d}"/>
      <input id="rangeType" name="rangeType" type="hidden" value=""/><input id="page" name="page" type="hidden" value="{page}"/>
      <div class="con_listHead"><h4>안성맞춤아트홀 전체일정 안내</h4></div>
      <div class="con_list">{items}</div>{pages}
    </form><form id="researchForm"><input type="hidden" name="page" value="9"/></form></body></html>""".encode()


_FIELDS = (
    ("장르", "클래식"), ("기간", "2026-12-09 ~ 2026-12-10"), ("시간", "19:30 "), ("관람시간", "약 100분"),
    ("장소", "안성맞춤아트홀 <b>대공연장</b>"), ("관람연령", "초등학생 이상부터 관람가능 "),
    ("입장권", "R석 30,000원,  S석 20,000원<br>초중고등학생 전석 1만원"), ("티켓 오픈 일시", "2026-10-08 16:00 ~ "),
    ("문의처", "안성맞춤아트홀 031-000-0000"), ("주최/주관", "안성맞춤아트홀"),
)
_TABS = '<ul class="tab_view"><li data-index="1"><a href="#" onclick="goTab(1); return false;">공연 소개</a></li>' \
        '<li data-index="2"><a href="#" onclick="goTab(2); return false;">할인정보</a></li></ul>'
_SECTIONS = """<div id="tap_wrapper1" class="mT30 tap_wrapper" style="display: none;"><div class="info_responsive">
    <p class="p_notice">모바일 사용시 이미지를 좌우로 이동하여 내용을 확인 할 수 있습니다.</p>
    <img src="/common/imgView.do?attachId=a&amp;fileSn=b&mode=originView" alt="소개"><!-- 주석 --></div></div>
  <div id="tap_wrapper2" class="mT30 tap_wrapper" style="display: none;"><div>- 안성시민 15%<br />&nbsp;* 인증 후
    <a href="https://example.invalid/pass">안내</a></div><p><font><strong>증빙 필요</strong></font></p></strong></div>
  <div id="tap_wrapper3" class="mT30 tap_wrapper" style="display: none;"><p class="p_notice">안내</p></div>"""


def detail(concert_id="3809", *, init_id=None, goods="26014378", title="합성 공연 <테오팀 & 듀오>", fields=_FIELDS,
           buttons=True, tabs=_TABS, sections=_SECTIONS, action=_ACTION, category='<span class="category_program">기획</span>',
           head='<div id="layer_popup1" style="display:none;"><div></div></div><img hidden>'):
    rows = "".join(f'<li><span class="title">{label}</span><span class="sub">{value}</span></li>' for label, value in fields)
    booking = ('<div class="ticket_btns"><p class="ticketbooking"><a href="javascript:void(0);" '
               'onclick="module.booking(); return false;">예매하기</a></p></div>') if buttons else ""
    return f"""<!DOCTYPE html><html><body>{head}
    <form id="cancel" name="cancel" action="{action}" method="post"><input name="page" type="hidden" value="1"/></form>
    <div class="con_list"><div class="m_title taC">{category}<h4>{title}</h4></div>
      <div class="conInfo_img"><img src="/common/imgView.do?attachId=p&amp;fileSn=q&width=550&mode=ratio" alt="포스터 <x>">
        <!-- 기존 noimage -->{booking}<p class="ticketing">새로고침 <span class="red">금지</span></p></div>
      <div class="conInfo_list">{category}<h4 class="sph4 pT10">{title}</h4><ul>{rows}</ul></div></div>
    <div class="cleB"></div>{tabs}{sections}<div class="btnboxR"><a href="#" onclick="history.back(); return false;">목록</a></div>
    <script>$(function () {{ module.init('{init_id or concert_id}', '', '{goods}', '', '', ''); }});
      if (a < b) {{ x = "</div>"; }}</script></body></html>"""


def _body(html):
    return detail(tabs="", sections=f'<div id="tap_wrapper1" class="tap_wrapper">{html}</div>')


class ArthallListingTest(unittest.TestCase):
    def test_reads_ids_and_page_count(self):
        self.assertEqual(parse_listing(listing("3", "1", page=2, total=3), year=2026, month=12, page=2), (3, ["3", "1"]))
        self.assertEqual(parse_listing(listing("5"), year=2026, month=12, page=1), (1, ["5"]))
        self.assertEqual(parse_listing(listing(month=6), year=2026, month=6, page=1), (1, []))
        self.assertEqual(listing_path(2026, 6, 2), "/arthall/concert/list.do?mId=0202010100&year=2026&month=6&page=2")
        # `</ div>`·`</div\xa0>`는 브라우저처럼 영역을 닫지 않는다(3.13.5만 `</div>`로 읽었다).
        for odd in (b"</ div>", b"</\ndiv>", "</div\xa0>".encode()):
            self.assertEqual(parse_listing(listing("1").replace(b'"fR">', b'"fR">' + odd), year=2026, month=12, page=1),
                             (1, ["1"]))

    def test_rejects_mismatch_and_format_changes(self):
        cases = {
            "연월": (listing("1"), {"month": 11}),
            "요청 쪽": (listing("1", page=1, total=2), {"page": 2}),
            "현재 쪽": (listing("1", page=2, pager='<span>1</span><a onclick="goPage(2); return false;">2</a>'), {"page": 2}),
            "다음": (listing("1", pager='<span>1</span><a onclick="goPage(2); return false;">다음</a>'), {}),
            "건너뜀": (listing("1", pager='<span>1</span><a onclick="goPage(3); return false;">3</a>'), {}),
            "구조": (listing("1", "1"), {}),
            # 쪽 번호 영역의 class가 바뀌면 여러 쪽짜리 달도 1쪽으로 보일 수 있다.
            "쪽 번호 없음": (listing("1", total=2).replace(b'class="bod_page"', b'class="paging"'), {}),
            "다른 목록": (listing("1", action="/arthall/other/list.do"), {}),
        }
        # 남는 `</div>`가 영역을 닫아도 뒤 공연·쪽 번호·항목은 보인다.
        cases["남는 끝 태그"] = (listing("11", "12").replace(b"</div></li>", b"</div></div></li>", 1), {})
        cases["쪽 번호 밖"] = (listing("1", pager='<span>1</span></div><a onclick="goPage(2); return false;">2</a>'), {})
        cases["중복 onclick"] = (listing("1").replace(b'onclick="go', b'onclick="x" onclick="go'), {})
        cases["숨김"] = (listing("1").replace(b"<ul>", b"<ul hidden>", 1), {})
        cases["빈 안내"] = (listing().replace("검색된 전체일정이 없습니다.".encode(), b""), {})
        for name, (raw, override) in cases.items():
            with self.subTest(name), self.assertRaises(ValueError):
                parse_listing(raw, **{"year": 2026, "month": 12, "page": 1, **override})
        with self.assertRaisesRegex(ValueError, "2000~2100"):
            parse_listing(listing("1"), year=2026, month=13, page=1)


class ArthallDetailTest(unittest.TestCase):
    def test_keeps_display_text_and_separates_schedules(self):
        record = parse_detail(detail(), concert_id="3809")
        self.assertEqual(record["title"], "합성 공연 <테오팀 & 듀오>")
        self.assertEqual(record["official_url"], "https://www.anseong.go.kr/arthall/concert/view.do?idx=3809&mId=0202010100")
        self.assertEqual(record["category"], "기획")
        fields = record["fields"]
        self.assertEqual(fields["admission"], "R석 30,000원, S석 20,000원 초중고등학생 전석 1만원")
        self.assertEqual((fields["venue"], fields["age_rating"], fields["time"]),
                         ("안성맞춤아트홀 대공연장", "초등학생 이상부터 관람가능", "19:30"))
        self.assertIsNone(fields["cast"])
        self.assertEqual(record["performance_period"], {"start": "2026-12-09", "end": "2026-12-10"})
        self.assertEqual(record["ticket_open_at"], "2026-10-08T16:00")
        self.assertEqual((record["booking_buttons"], record["ticketing_goods_code"]), (["예매하기"], "26014378"))
        self.assertEqual(record["poster_url"], "/common/imgView.do?attachId=p&fileSn=q&width=550&mode=ratio")
        first, second = record["sections"]
        self.assertEqual((first["title"], first["text"], first["images"]),
                         ("공연 소개", None, ["/common/imgView.do?attachId=a&fileSn=b&mode=originView"]))
        self.assertEqual(second["text"], "- 안성시민 15% * 인증 후 안내 증빙 필요")
        self.assertEqual(second["links"], ["https://example.invalid/pass"])
        self.assertEqual(record["review_flags"], [])
        adjacent = _body("<div>안성시민 15%</div><div>경로 50%</div>")
        self.assertEqual(parse_detail(adjacent, concert_id="3809")["sections"][0]["text"], "안성시민 15% 경로 50%")

    def test_missing_values_stay_null_with_flags(self):
        fields = [("장르", ""), ("기간", "2026-12-10 ~ 2026-12-09"), ("티켓 오픈 일시", " ~ "), ("입장권", "무료"),
                  ("출연", "합성 출연"), ("기획", "합성 기획사")]
        sections = '<div id="tap_wrapper1" class="tap_wrapper"></div>' \
                   '<div id="tap_wrapper2" class="tap_wrapper"><img src="/x.png"></div>'
        record = parse_detail(detail("7", fields=fields, buttons=False, goods="", tabs="", sections=sections, category=""),
                              concert_id="7")
        self.assertIsNone(record["category"])
        self.assertEqual((record["fields"]["admission"], record["fields"]["cast"]), ("무료", "합성 출연"))
        self.assertEqual(record["fields"]["ticket_open"], "~")
        self.assertEqual(record["other_fields"], [{"label": "기획", "value": "합성 기획사"}])
        self.assertEqual((record["performance_period"], record["ticket_open_at"]), (None, None))
        self.assertEqual((record["booking_buttons"], record["ticketing_goods_code"]), ([], None))
        self.assertEqual(record["sections"], [{"index": 2, "title": None, "text": None, "images": ["/x.png"], "links": []}])
        self.assertEqual(record["review_flags"], [
            "missing:age_rating", "missing:contact", "missing:genre", "missing:host", "missing:time", "missing:venue",
            "period_inverted", "sections_without_text", "ticket_open_blank", "unmapped_field", "untitled_section:2"])
        odd = parse_detail(detail(fields=[("티켓 오픈 일시", "2026-10-08 오후 4시")]), concert_id="3809")
        self.assertIn("ticket_open_unparsed", odd["review_flags"])

    def test_raw_text_elements_hide_markup_on_every_version(self):
        # 원문 요소 안의 영역 표기는 3.13에서도 마크업으로 읽지 않는다.
        base = parse_detail(detail(), concert_id="3809")
        for tag in ("xmp", "iframe", "noembed", "noframes", "noscript", "textarea", "title"):
            text = detail(head=f'<{tag}><div class="conInfo_list"><h4>가짜</h4></div></{tag}>')
            with self.subTest(tag):
                self.assertEqual(parse_detail(text, concert_id="3809"), base)

    def test_reads_tag_borders_like_browsers(self):
        # 브라우저처럼 `</ div>`·`</div\xa0>`는 div를 닫지 않고 void가 아닌 `<div/>`는 열어 둔다(3.13.5는 달리 읽었다).
        for markup, text in (("1</ div>2", "12"), ("1</\ndiv>2", "12"), ("1</div\xa0>2", "12"), ("<div/>1</div>2", "1 2"),
                             ("<!x>1<?x>", "1")):
            with self.subTest(markup):
                self.assertEqual(parse_detail(_body(f"<div>{markup}</div>"), concert_id="3809")["sections"][0]["text"], text)

    def test_rejects_unconfirmed_pages(self):
        cases = {
            "번호": detail(init_id="1"),
            "제목 태그": detail(title="합성 <Art Story>"),
            "숨김": detail(fields=[("장소", '<span style="display:none">숨김</span>')]),
            "본문 태그": _body('<iframe src="/x"></iframe>'),
            "중복 항목": detail(fields=[("장소", "a"), ("장소", "b")]),
            "없는 탭": detail(sections=""),
            "다른 화면": detail(action="/arthall/other/list.do"),
            "값 없는 항목": detail(fields=[("장소", "a")]).replace('<span class="sub">a</span>', ""),
            "안내 안 태그": _body('<p class="p_notice">모바일<div>본문1</div></div>'
                                 '<div id="tap_wrapper2" class="tap_wrapper"><div>본문2</div>'),
            "안내 밖 닫힘": _body('<div><p class="p_notice">모바일</div>본문</p>'),
            "스스로 닫은 영역": detail(tabs="", sections='<div id="tap_wrapper1" class="tap_wrapper"/>본문'),
            "plaintext": detail(head="<plaintext>"),
            # 브라우저는 뒤 영역까지 script 글자로 읽는다.
            "script 주석": detail(head="<script><!--<script>\n</script>"),
            "항목 밖": detail().replace("</h4><ul>", "</h4></div><ul>"),
            "예매 밖": detail().replace("<!-- 기존 noimage -->", "</div>"),
            # 남는 `</div>`가 영역을 일찍 닫으면 뒤 버튼·포스터·본문이 표시 없이 버려진다.
            "버튼 밖 링크": detail().replace('<div class="ticket_btns">', '<div class="ticket_btns"></div><div>'),
            "포스터 밖": detail(buttons=False).replace('<div class="conInfo_img">', '<div class="conInfo_img"></div>'),
            "본문 밖 글자": _body("<div>본문1</div></div>본문2"),
            "본문 밖 태그": _body('<div>본문1</div></div><img src="/x.png">'),
            "영역 사이 글자": detail().replace('<div class="cleB"></div>', '<div class="cleB"></div>보이는글'),
            "중복 숨김": _body('<p style="display:none" style>숨김</p>'),
            "중복 src": detail().replace("<img", '<img src="/b.png"'),
            "CSS 이스케이프": _body(r'<p style="disp\lay:none">숨김</p>'),
        }
        # 끝 태그가 빠진 숨김 요소가 뒤 영역을 감싼다.
        for head in ('<div style="display:none;">', "<div hidden><div></div>", "<template>"):
            cases[head] = detail(head=head)
        # 공용 파서의 거부 규칙 전체는 test_html_tokens가 본다.
        for markup in ("<!-- a --!>보이는글<!-- b -->", "<!-- 끝없음", "<![CDATA[x]]>보이는글", 'a</div x=">">b',
                       # 3.13.5는 따옴표 밖 `\xa0`와 `==`를 속성 구분자로 읽어 3.14·브라우저와 속성이 달랐다.
                       '<span class="a"\xa0id="b">x</span>', "<span title==x>x</span>"):
            cases[markup] = _body(f"<div>{markup}</div>")
        for tag in ("script", "title"):
            # 브라우저는 `/>`를 무시하고 뒤 영역까지 원문 텍스트로 읽는다.
            cases[f"<{tag}/>"] = detail(head=f"<{tag}/>")
        for name, text in cases.items():
            # 공용 파서가 거부해도 이 모듈의 오류 문구를 남긴다.
            with self.subTest(name), self.assertRaisesRegex(ValueError, "^안성맞춤아트홀"):
                parse_detail(text, concert_id="3809")
        missing = "<html><head><script>alert('존재하지 않는 공연/전시입니다.'); history.back(-1);</script></head></html>"
        with self.assertRaisesRegex(ValueError, "존재하지 않는"):
            parse_detail(missing, concert_id="3809")


class ArthallBatchTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(TemporaryDirectory())).resolve() / "collection-arthall"
        self.enterContext(patch("processing.collection.arthall_batch.sleep"))
        self.listing = self.enterContext(patch("processing.collection.arthall_batch.fetch_listing"))
        self.detail = self.enterContext(patch("processing.collection.arthall_batch.fetch_detail"))

    def test_capture_keeps_raw_and_reads_back(self):
        pages = [listing("9", "7", page=1, total=2), listing("8", page=2, total=2)]
        self.listing.side_effect = pages
        self.detail.side_effect = lambda concert_id, **_options: detail(concert_id).encode()
        summary = capture_arthall_batch(2026, 12, "run", self.root)
        self.assertEqual(summary, {"batch_id": "run", "status": "complete", "discovery_status": "complete",
                                   "selected": 3, "parsed": 3})
        self.assertEqual([call.args for call in self.listing.call_args_list], [(2026, 12, 1), (2026, 12, 2)])
        directory = self.root / "run"
        receipt = json.loads((directory / "batch.json").read_text(encoding="utf-8"))
        self.assertEqual((receipt["schema_version"], receipt["year"], receipt["month"]), ("citizen-arthall-batch-v1", 2026, 12))
        self.assertEqual((directory / "list-2.html").read_bytes(), pages[1])
        self.assertEqual(receipt["items"][0]["source_url"], detail_url("9"))
        parsed = json.loads((directory / "parsed-9.json").read_text(encoding="utf-8"))
        self.assertEqual(parsed["parser_version"], PARSER_VERSION)
        receipt, records = read_arthall_batch(self.root.parent, "run")
        self.assertEqual(receipt["status"], "complete")
        self.assertEqual(list(records), ["9", "7", "8"])
        self.assertEqual(records["9"], parsed["record"])

        def tamper(path, old, new):
            original = path.read_bytes()
            path.write_bytes(original.replace(old, new))
            with self.assertRaises(ValueError):
                read_arthall_batch(self.root.parent, "run")
            path.write_bytes(original)

        tamper(directory / "detail-7.html", "합성".encode(), "변조".encode())
        tamper(directory / "list-1.html", b"go_view('7')", b"go_view('6')")
        tamper(directory / "parsed-8.json", "클래식".encode(), "무용".encode())
        tamper(directory / "parsed-8.json", PARSER_VERSION.encode(), b"arthall-concert-parser-v0")
        tamper(directory / "batch.json", b'"month": 12', b'"month": 11')
        # 목록에 있는 공연을 지우고 건수를 맞춘 완료 기록도 거부한다.
        dropped = {**receipt, "items": [row for row in receipt["items"] if row["web_id"] != "7"], "selected": 2, "parsed": 2}
        original = (directory / "batch.json").read_bytes()
        tamper(directory / "batch.json", original, json.dumps(dropped).encode())
        # 2쪽 목록과 그 공연을 함께 빼거나 실패로 바꾸거나, 한도 도달 묶음을 완료로 적은 기록도 거부한다.
        first, second = receipt["pages"]
        kept = {**receipt, "items": receipt["items"][:2], "selected": 2, "parsed": 2}
        for changed in ({**kept, "pages": [first]}, {**kept, "pages": [first, {**second, "status": "fetch_failed"}]},
                        {**receipt, "discovery_status": "item_limit"}):
            tamper(directory / "batch.json", original, json.dumps(changed).encode())
        self.assertEqual(len(read_arthall_batch(self.root.parent, "run")[1]), 3)

    def test_failures_keep_raw_and_partial_reads(self):
        self.listing.return_value = listing("1", "2", "3")
        self.detail.side_effect = [detail("99").encode(), ValueError("합성 수신 실패"), SourceHTTPError(429)]
        summary = capture_arthall_batch(2026, 12, "part", self.root)
        self.assertEqual((summary["status"], summary["parsed"]), ("partial", 0))
        receipt = json.loads((self.root / "part" / "batch.json").read_text(encoding="utf-8"))
        self.assertEqual([item["status"] for item in receipt["items"]], ["parse_failed", "fetch_failed", "fetch_failed"])
        self.assertIn("번호가 요청과 일치하지 않습니다", receipt["items"][0]["error"])
        self.assertEqual(receipt["stop_http_status"], 429)
        self.assertEqual(read_arthall_batch(self.root.parent, "part")[1], {})

    def test_cli_capture_and_verify(self):
        self.listing.return_value = listing("5")
        self.detail.return_value = detail("5").encode()

        def run(*argv):
            with patch("sys.argv", ["arthall_batch", *argv]), contextlib.redirect_stdout(io.StringIO()) as out, \
                    contextlib.redirect_stderr(io.StringIO()) as error:
                return arthall_batch.main(), out.getvalue() and json.loads(out.getvalue()), error.getvalue()

        capture = ("capture", "--year", "2026", "--month", "12", "--name")
        with patch.object(arthall_batch, "ARTHALL_ROOT", self.root):
            code, out, _ = run(*capture, "cli")
            self.assertEqual((code, out["status"]), (0, "complete"))
            code, out, _ = run("verify", "--name", "cli")
            self.assertEqual((code, out["status"], out["batch_status"]), (0, "verified", "complete"))
            # 일부 실패 묶음은 검증을 통과해도 원래 상태와 함께 종료 코드 2를 돌려준다.
            self.detail.side_effect = ValueError("합성 수신 실패")
            self.assertEqual(run(*capture, "part")[0], 2)
            self.assertEqual(run("verify", "--name", "part")[:2], (2, {"batch_id": "part", "status": "verified",
                                                                        "batch_status": "partial", "selected": 1, "parsed": 0}))
            code, _, error = run("verify", "--name", "none")
            self.assertEqual(code, 1)
            self.assertIn("아트홀 일정 수집 실패", error)


if __name__ == "__main__":
    unittest.main()
