import contextlib
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from processing.collection import gosi_batch
from processing.collection.gosi_batch import capture_gosi_batch, read_gosi_batch
from processing.collection.gosi_notices import (
    fetch_gosi_detail, fetch_gosi_listing, gosi_detail_url, parse_gosi_detail, parse_gosi_listing,
)

_HEAD = "".join(f'<th scope="col" class="{name}">{text}</th>' for name, text in (
    ("wp20 gosi_num", "고시공고번호"), ("gosi_tit", "제목"), ("wp10 gosi_dept", "담당부서"), ("wp15 gosi_date", "등록일")))
_LICENSE = '본 공공저작물은 공공누리 제4유형: "출처표시" + 상업적 이용 및 변경 금지 조건에 따라 이용할 수 있습니다.'
_FILE = ("공고문[(주)합성].hwpx", "공고문[(주)합성]_ofr_ofr_X_1.hwpx", "/ntishome/file/upload/ofr/ofr/20261126")


def _row(notice_id, page=1, *, number="안성시 고시 <br/> 제2026-343호", title="합성 도로정비 허가", dept="도로시설과"):
    return (f'<tr><td class="gosi_num">{number}</td><td class="taL gosi_tit">'
            f'<a href="#" onclick="javascript:boardView(\'{page}\', \'{notice_id}\');return false;">\n {title}\n</a></td>'
            f'<td class="gosi_dept">{dept}</td><td class="gosi_date">\n 2026.11.27\n</td></tr>')


def listing(*ids, page=1, total=1, rows=None, caption="고시/공고게시판 목록 고시공고번호,제목 순서의 표", action=None):
    rows = rows if rows is not None else "".join(_row(notice_id, page) for notice_id in ids)
    action = action or f"/portal/saeol/gosiList.do?seCode=01&amp;mId=0501040000&amp;page={page}"
    return f"""<html><body><form id="searchForm" action="/search/front/Search.jsp"></form>
<script>function boardView(page, idx) {{ frm.action = '<form id="listForm">'; }}</script>
<form id="listForm" name="listForm" action="{action}" method="post">
<input id="page" name="page" type="hidden" value="{page}"/>
<div class="search_box"><div class="board_page">Total 6579\tPage <span class="red"><strong>{page}</strong></span>
 / {total}</div></div>
<div class="gosi_wrap"><table class="tableSt_list row_over"><caption>{caption}</caption>
<thead><tr>{_HEAD}</tr></thead>
<tbody>{rows}</tbody></table></div>
<div class="box_page"><a href="#" onclick="goPage(2); return false;">2</a></div>
</form></body></html>""".encode()


def _links(notice_id, files, preview_id=None):
    return "".join(
        f"""<!-- 20461 20458 --><p><a href="javascript:goDownload('{user}', '{system}', '{path}')">
{user}
</a><a href="#" onclick="fn_egov_gosi_preview('{preview_id or notice_id}','{notice_id}-{number}.hwpx','{user}','{system}','{path}'); return false;" target="_blank" title="새창으로 열림" class="bt_white_s"><span class="blank">바로 보기</span></a></p>"""
        for number, (user, system, path) in enumerate(files))


def detail(notice_id="75365", *, title="합성 도로정비 허가", number="안성시 고시 제2026-343호", registered="2026.11.27",
           dept="도로시설과", body="우리시&nbsp;미양면&nbsp;일원<br><br>붙임&nbsp;공고문&nbsp;1부.", files=(_FILE,),
           links=None, action="/portal/saeol/gosiView.do?mId=0501040000"):
    links = links if links is not None else _links(notice_id, files)
    return f"""<!DOCTYPE html><html><head><title>고시/공고 상세</title><script>
var yh = {{"contextPath": ""}};
</script></head><body>
<form id="detailForm" name="detailForm" action="{action}" method="post">
<input type="hidden" name="page" value="1" /><h4 class="hidden">고시/공고게시판 내용보기</h4>
<div class="bod_wrap"><div class="bod_view"><h4>{title}</h4>
<div class="view_info gosi_b"><ul>
<li class="view_write"><span>고시공고번호</span> : {number}</li>
<li class="view_date"><span>등록일</span> :
  {registered}
</li>
<li class="view_hit"><span>담당부서</span> : {dept}</li>
</ul></div>
<div class="view_cont">
{body}
</div>
<dl class="view_file"><dt><span>첨부 파일</span></dt><dd>{links}</dd></dl>
<div class="open_license clFix mB20"><a rel="license" href="https://www.kogl.or.kr/info/license.do" target="_blank"
 title="새창열기"><img src="/common/img/KOGL/new_img_opentype04.png" alt="공공누리 제4유형"></a><p>{_LICENSE}</p></div>
</div></div></form></body></html>"""


def _cut(text, start, end):
    head, _, rest = text.partition(start)
    return head + rest.partition(end)[2]


def row(notice_id="75365", **changes):
    return {"notice_id": notice_id, "notice_number": "안성시 고시 제2026-343호", "title": "합성 도로정비 허가",
            "department": "도로시설과", "registered_date": "2026.11.27", **changes}


class GosiParserTest(unittest.TestCase):
    def test_listing_keeps_rows_verbatim_and_checks_request_echo(self):
        total, items = parse_gosi_listing(listing("75365", "64", page=3, total=658), page=3)
        self.assertEqual(total, 658)
        self.assertEqual(items, [row(), row("64")])
        cases = {
            "요청한 게시판·페이지": listing("1", page=2),
            "페이지 번호": listing(rows=_row("1", 3), page=2, total=5,
                                action="/portal/saeol/gosiList.do?seCode=01&amp;mId=0501040000&amp;page=3"),
            "게시판 구분": listing("1", caption="입법예고 목록"),
            "구조": listing(rows=_row("1", page=2)),
            "같은 게시물": listing("1", "1"),
        }
        for message, raw in cases.items():
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                parse_gosi_listing(raw, page=3 if message == "페이지 번호" else 1)
        searched = "/portal/saeol/gosiList.do?seCode=01&amp;mId=0501040000&amp;page=1&amp;searchTxt=x"
        with self.assertRaisesRegex(ValueError, "요청한 게시판"):
            parse_gosi_listing(listing("1", action=searched), page=1)
        broken = _row("1").replace('class="gosi_dept"', 'class="other"')
        for rows in (broken, _row("1").replace("</a>", "</a><div>x</div>"), "<tr><td colspan='4'>없음</td></tr>"):
            with self.subTest(rows=rows), self.assertRaisesRegex(ValueError, "구조"):
                parse_gosi_listing(listing(rows=rows), page=1)

    def test_listing_reads_tag_borders_like_a_browser(self):
        # 빈 요소가 아닌 태그의 `/>`는 무시되고 textarea 안 글은 태그가 아니다(표준 파서는 가짜 listForm을 읽었다).
        rows = _row("1").replace('<td class="gosi_dept">', '<td class="gosi_dept"/>')
        decoy = '<body><textarea><form id="listForm" action="/x"></form></textarea>'.encode()
        self.assertEqual(parse_gosi_listing(listing(rows=rows).replace(b"<body>", decoy), page=1), (1, [row("1")]))
        for markup in ("<!-->", "</b title='>'>", "<![CDATA[x]]>", '<b class="a"\xa0id="b">', "</br>"):
            with self.subTest(markup=markup), self.assertRaisesRegex(ValueError, "고시·공고 목록 HTML에 브라우저와 해석이"):
                parse_gosi_listing(listing("1").replace(b"<tbody>", f"<tbody>{markup}".encode()), page=1)

    def test_listing_accepts_only_sampled_markup_in_read_regions(self):
        # 종료 태그는 가장 안쪽에 열린 요소를 닫아야 한다.
        cell = '<td class="gosi_dept">'
        for old, new in ((cell, '<td class="gosi_dept blind">'), (cell, '<td class="gosi_dept" style="color:red">'),
                         (cell, '<td class="gosi_dept" hidden>'), (cell, cell + "<span>x</span>"), ("<thead>", "<thead><br>"),
                         ("<tbody>", "<tbody><template></template>"), ("<strong>", "<strong hidden>"),
                         ("<strong>", '<strong><span class="blind">9</span>'), ("</strong>", "</strong></b>"),
                         ("<strong>", "<strong><div>x</div>"), ('"red"', '"red" class="red"'), ("<tbody>", "<tbody>마감"),
                         ("제목</th>", "제목 마감</th>"), ('"red">', '"red">9'), ("<a href", "<a class href")):
            with self.subTest(new=new), self.assertRaisesRegex(ValueError, "구조"):
                parse_gosi_listing(listing("1").replace(old.encode(), new.encode(), 1), page=1)
        # template 안 짝 없는 종료 태그는 브라우저가 무시해 목록이 숨은 채로 남는다.
        hidden = listing("1").replace(b'<form id="listForm" name', b'<template></style><form id="listForm" name')
        with self.assertRaisesRegex(ValueError, "목록 HTML 구조"):
            parse_gosi_listing(hidden.replace(b"</form></body>", b"</form></template></body>"), page=1)

    def test_detail_accepts_only_sampled_markup_in_body(self):
        # 공지 게시판이 받는 표기라도 표본에 없으면 거부한다.
        empty = detail(body="")
        texts = [detail(body=body) for body in (
            "<b>마감</b>", '<span style="color:red">마감</span>', '<p class="blind">마감</p>', '<div data-x="1">마감</div>',
            '<a href="#" href="#">x</a>', "<table><tr><td>x</td></tr></table>", "<p>가<p>나</p>", '<img src="/x" alt="x">',
            "<ul><li>가<ul><li>나</li></ul></li></ul>")] + [detail(title="가<h4>나</h4>")] + [
            # 값 없는 class는 class 없는 자리(`a[href]`·`h4`)로 맞추지 않는다.
            detail().replace(old, new, 1) for old, new in (("<p><a href", "<p><a class href"), ("<h4>합성", "<h4 class>합성"))] + [
            empty.replace("</div>\n<dl", f"</div>{extra}\n<dl") for extra in (
                "<p>접수기간 2026.12.01~12.05</p>", '<div class="gosi_b">마감</div>', "<ul><li>지원금 50만원</li></ul>")]
        for text in texts:
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, "숨김"):
                parse_gosi_detail(text, notice_id="75365", listing=row())
        # 읽는 칸 밖 글자는 버려지므로 표본 고정 문구만 받고, 종료 태그는 가장 안쪽 요소만 닫아야 한다.
        for old, new in (("</div>\n<dl", "</div>접수기간 2026.12.01~12.05\n<dl"), ("</ul>", "</ul>신청 마감 12.05"),
                         ("첨부 파일", "첨부 파일 12.05 마감"), ("변경 금지", "변경 금지 12.05 마감"),
                         ("</div>\n<dl", "</span></div>\n<dl"), ('alt="공공누리 제4유형">', 'alt="공공누리 제4유형"></img>')):
            with self.subTest(new=new), self.assertRaisesRegex(ValueError, "구조가 올바르지"):
                parse_gosi_detail(empty.replace(old, new), notice_id="75365", listing=row())

    def test_repeated_class_or_id_fails_anywhere(self):
        # 브라우저는 중복 속성의 첫 값을 써서 미끼가 보인다.
        url = "/portal/saeol/gosiList.do?seCode=01&amp;mId=0501040000&amp;page=1"
        table = f'<table class="tableSt_list row_over" class="x"><tbody>{_row("2")}</tbody></table><div class="box_page">'
        for old, new in (('<div class="box_page">', table), ("<body>", f'<body><form id="listForm" id="z" action="{url}"></form>')):
            with self.subTest(new=new), self.assertRaisesRegex(ValueError, "구조"):
                parse_gosi_listing(listing("1").replace(old.encode(), new.encode()), page=1)
        body = '<div class="bod_view" class="x"><h4>가짜</h4><div class="view_cont">지원금 100만원</div></div>'
        for new in (body, '<form id="detailForm" id="z" action="/portal/bbs/view.do?mId=0501010000"></form>'):
            with self.subTest(new=new), self.assertRaisesRegex(ValueError, "class·id 속성이 중복"):
                parse_gosi_detail(detail().replace("<body>", "<body>" + new), notice_id="75365", listing=row())

    def test_detail_keeps_text_and_attachment_candidates(self):
        odd = ("A&B.hwp", "A%26B.hwp", "a\\x26b.hwp", "안내%20문.hwp", "안내\t문.hwp")
        files = (_FILE, ("포스터.JPG", "포스터_1.jpg", "/p"), ("조서.xlsx", "조서_2.xlsx", "/p"),
                 *((name, "s_3.hwp", "/p") for name in odd))
        record = parse_gosi_detail(detail(files=files), notice_id="75365", listing=row())
        self.assertEqual(record["official_url"],
                         "https://www.anseong.go.kr/portal/saeol/gosiView.do?notAncmtMgtNo=75365&mId=0501040000")
        self.assertEqual(record["fields"], {"notice_number": "안성시 고시 제2026-343호", "registered_date": "2026.11.27",
                                            "department": "도로시설과",
                                            "description": "우리시 미양면 일원\n붙임 공고문 1부."})
        self.assertEqual(record["registered_on"], "2026-11-27")
        self.assertEqual(record["review_flags"], ["attachment"])
        self.assertEqual([(item["label"], item["format"]) for item in record["attachments"][:4]],
                         [(_FILE[0], "hwpx"), ("포스터.JPG", "jpeg"), ("조서.xlsx", None), ("A&B.hwp", "hwp")])
        self.assertEqual(record["attachments"][0]["source_url"],
                         "https://eminwon.anseong.go.kr/emwp/jsp/ofr/FileDown.jsp?user_file_nm=%EA%B3%B5%EA%B3%A0%EB%AC%B8"
                         "%5B(%EC%A3%BC)%ED%95%A9%EC%84%B1%5D.hwpx&sys_file_nm=%EA%B3%B5%EA%B3%A0%EB%AC%B8%5B(%EC%A3%BC)"
                         "%ED%95%A9%EC%84%B1%5D_ofr_ofr_X_1.hwpx&file_path=/ntishome/file/upload/ofr/ofr/20261126")
        # 표본에 없던 문자(질의 구분자, 실행 전에 바뀌는 `%`·`\`·탭)가 든 인자는 주소를 확정하지 않는다.
        self.assertEqual([item["source_url"] for item in record["attachments"][3:]], [None] * 5)
        self.assertEqual(record["referenced_notice_numbers"], [])

    def test_detail_without_attachments_body_or_date_keeps_null_reasons(self):
        record = parse_gosi_detail(detail(body="", links="", registered="2026.13.01", dept=""), notice_id="1",
                                   listing=row("1", registered_date="2026.13.01", department=None))
        self.assertEqual((record["fields"]["description"], record["fields"]["department"]), (None, None))
        self.assertIsNone(record["registered_on"])
        self.assertEqual(record["attachments"], [])
        self.assertEqual(record["review_flags"],
                         ["missing:department", "missing:description", "registered_date_unparsed"])
        direct = "<p><a href=\"javascript:goDownload_direct('a.hwp', '/old')\">a.hwp</a><a href=\"\">b.pdf</a></p>"
        record = parse_gosi_detail(detail(body="", links=direct), notice_id="1", listing=row("1"))
        self.assertEqual([(item["source_url"], item["label"], item["format"]) for item in record["attachments"]],
                         [(None, "a.hwp", "hwp"), (None, "b.pdf", "pdf")])
        self.assertEqual(record["review_flags"], ["attachment", "missing:description"])

    def test_detail_records_only_stated_notice_numbers(self):
        # 다른 주체의 같은 번호는 남기고, 주체 없는 번호는 번호만 둔다.
        body = ("안성시 공고 제2026-343호(2026.11.1.)를 정정합니다.<br>안성시 고시 제 2026-343호 참조."
                " 안성시&nbsp;농업기술센터 공고 제2026-268호, 제2026-100호, 제 2026-100호")
        record = parse_gosi_detail(detail(body=body, title="합성 공고(정정)"), notice_id="75365",
                                   listing=row(title="합성 공고(정정)"))
        self.assertEqual(record["referenced_notice_numbers"],
                         ["안성시 공고 제2026-343호", "안성시 농업기술센터 공고 제2026-268호", "제2026-100호"])
        record = parse_gosi_detail(detail(title="합성 공고(정정)"), notice_id="75365", listing=row(title="합성 공고(정정)"))
        self.assertEqual(record["referenced_notice_numbers"], [])

    def test_detail_keeps_issuer_of_spaced_or_bracketed_numbers(self):
        # 경기도·붙여 쓴 주체·괄호 표기는 주체까지 남기고 괄호·공백만 다른 번호는 하나로, 모르는 주체·짝 없는 괄호는 번호만 남긴다.
        body = ("경기도 고시 제2026-100호, 안성시공도읍 공고 제2026-79호, 안성시 공고(제2026-3155호)를 정정합니다."
                " 안성시 공고 (제2026-3155호), 안성시 고시(제2026-343호), 다시 공고 제2026-5호, 안성시 공고(제2026-6호 참조")
        record = parse_gosi_detail(detail(body=body), notice_id="75365", listing=row())
        self.assertEqual(record["referenced_notice_numbers"],
                         ["경기도 고시 제2026-100호", "안성시공도읍 공고 제2026-79호", "안성시 공고(제2026-3155호)",
                          "제2026-5호", "제2026-6호"])

    def test_detail_treats_gyeonggi_prefixed_anseong_number_as_same(self):
        # `경기도 (및) 안성시 고시`는 `안성시 고시`와 같아 자기 번호로 빠지고, 같은 번호는 처음 원문 하나만 남는다.
        body = ("경기도 안성시 고시 제2026-343호, 안성시 고시 제2026-1호 및 경기도 안성시 고시 제2026-1호,"
                " 경기도 고시 제2026-1호, 경기도 및 안성시 고시 제2026-343호, 경기도와 안성시 고시 제2026-343호")
        record = parse_gosi_detail(detail(body=body), notice_id="75365", listing=row())
        self.assertEqual(record["referenced_notice_numbers"], ["안성시 고시 제2026-1호", "경기도 고시 제2026-1호"])
        # 한계: 붙여 쓴 낱말과 조사를 가리지 못해 `안성시에서 공고`는 다른 값이다(README).
        body = "안성시에서 공고 제2026-5호와 안성시 공고 제2026-5호"
        record = parse_gosi_detail(detail(body=body), notice_id="75365", listing=row())
        self.assertEqual(record["referenced_notice_numbers"], ["안성시에서 공고 제2026-5호", "안성시 공고 제2026-5호"])

    def test_detail_rejects_other_notices_and_format_changes(self):
        cases = {
            "목록 항목과 일치하지": (detail(), row(title="다른 제목")),
            "번호가 요청과": (detail(links=_links("75365", (_FILE,), preview_id="75366")), row()),
            "제목이 없습니다": (detail(title="", number="", registered="", dept="", body="", links=""), row()),
            "게시판이 요청과": (detail(action="/portal/bbs/view.do?mId=0501010000"), row()),
            "바로 보기 정보": (detail(links=_links("75365", (_FILE,)).replace("_1.hwpx','/nt", "_9.hwpx','/nt")), row()),
            "숨김": (detail(body='<div style="display:none">숨은 마감</div>'), row()),
            "해석이 갈리는": (detail(body="<!--> 마감"), row()),
            "해석이 갈리는 태그·주석": (detail(body="가</br>나"), row()),
            # 태그 경계 검사가 상세 폼 검사보다 먼저다.
            "해석이 갈리는 태그": (detail().replace('id="detailForm"', 'id="detailForm" action="/x" title=a`b'), row()),
            "view_cont": (_cut(detail(), '<div class="view_cont">', "</div>\n"), row()),
            "view_file": (_cut(detail(), '<dl class="view_file">', "</dl>"), row()),
            # template 안 짝 없는 종료 태그는 브라우저가 무시해 본문이 숨은 채로 남는다.
            "본문 영역을 확인할 수 없습니다": (detail().replace('<div class="bod_wrap">', "<template></script><div>")
                                     .replace("</div></div></form>", "</div></div></template></form>"), row()),
            "첨부 영역이 중복": (detail().replace("</dl>", '</dl><dl class="view_file"><dd></dd></dl>'), row()),
        }
        for message, (text, listed) in cases.items():
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                parse_gosi_detail(text, notice_id="75365", listing=listed)
        moved = detail().replace('<dl class="view_file">', '<div><dl class="view_file">').replace("</dl>", "</dl></div>")
        with self.assertRaisesRegex(ValueError, "숨김"):
            parse_gosi_detail(moved, notice_id="75365", listing=row())
        with self.assertRaisesRegex(ValueError, "18자리"):
            gosi_detail_url("0")

    def test_requests_use_fixed_get_paths(self):
        with patch("processing.collection.gosi_notices._fetch", return_value=b"ok") as fetch:
            fetch_gosi_listing(2, limit=10)
            fetch_gosi_detail("75365", limit=20)
        self.assertEqual([call.args for call in fetch.call_args_list], [
            ("GET", "/portal/saeol/gosiList.do?seCode=01&mId=0501040000&page=2", None, 10),
            ("GET", "/portal/saeol/gosiView.do?notAncmtMgtNo=75365&mId=0501040000", None, 20),
        ])


class GosiBatchTest(unittest.TestCase):
    def setUp(self):
        self.private = Path(self.enterContext(TemporaryDirectory())).resolve()
        self.root = self.private / gosi_batch.GOSI_SECTION
        self.enterContext(patch("processing.collection.gosi_batch.sleep"))
        self.listing = self.enterContext(patch("processing.collection.gosi_batch.fetch_gosi_listing"))
        self.detail = self.enterContext(patch("processing.collection.gosi_batch.fetch_gosi_detail"))
        self.detail.side_effect = lambda notice_id, **_options: detail(notice_id).encode()

    def run_cli(self, *argv, redirect=contextlib.redirect_stdout):
        with (patch.object(gosi_batch, "GOSI_ROOT", self.root), patch("sys.argv", ["gosi_batch", *argv]),
              redirect(io.StringIO()) as output):
            return gosi_batch.main(), output.getvalue()

    def test_capture_keeps_raw_and_read_revalidates(self):
        self.listing.side_effect = [listing("3", "2", total=2), listing("1", page=2, total=2)]
        summary = capture_gosi_batch("run", self.root)
        self.assertEqual(summary, {"batch_id": "run", "status": "complete", "discovery_status": "complete",
                                   "selected": 3, "parsed": 3})
        receipt = json.loads((self.root / "run" / "batch.json").read_text(encoding="utf-8"))
        self.assertEqual(receipt["schema_version"], "citizen-gosi-batch-v1")
        self.assertEqual(receipt["pages"][1]["source_url"],
                         "https://www.anseong.go.kr/portal/saeol/gosiList.do?seCode=01&mId=0501040000&page=2")
        records = read_gosi_batch(self.private, "run")
        self.assertEqual(list(records), ["3", "2", "1"])
        self.assertEqual(records["1"]["raw_asset_path"], "collection-gosi/run/detail-1.html")
        self.assertEqual(records["1"]["record"]["attachments"][0]["format"], "hwpx")

        parsed = self.root / "run" / "parsed-2.json"
        stored = json.loads(parsed.read_text(encoding="utf-8"))
        stored["record"]["title"] = "바뀐 제목"
        parsed.write_text(json.dumps(stored, ensure_ascii=False), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "파싱 결과가 원본과 다릅니다"):
            read_gosi_batch(self.private, "run")
        (self.root / "run" / "detail-2.html").write_bytes(b"x")
        with self.assertRaisesRegex(ValueError, "원본 해시"):
            read_gosi_batch(self.private, "run")

    def test_mismatched_detail_keeps_raw_and_reason(self):
        self.listing.side_effect = [listing("5", "6", total=2), b"bad"]
        self.detail.side_effect = [detail("5", title="다른 글").encode(), ValueError("합성 수신 실패")]
        summary = capture_gosi_batch("run", self.root)
        self.assertEqual((summary["status"], summary["parsed"]), ("partial", 0))
        receipt = json.loads((self.root / "run" / "batch.json").read_text(encoding="utf-8"))
        self.assertEqual([entry["status"] for entry in receipt["pages"] + receipt["items"]],
                         ["parsed", "parse_failed", "parse_failed", "fetch_failed"])
        self.assertIn("목록 항목과 일치하지", receipt["items"][0]["error"])
        self.assertTrue((self.root / "run" / "detail-5.html").exists())
        self.assertEqual(read_gosi_batch(self.private, "run"), {})
        # 파싱에 실패한 목록·상세 원본도 바뀌거나 지워지면 verify가 실패해야 한다.
        for name in ("list-2.html", "detail-5.html"):
            path = self.root / "run" / name
            raw = path.read_bytes()
            for change, reason in ((lambda: path.write_bytes(b"x"), "원본 해시"), (path.unlink, "안전하게 읽을")):
                change()
                code, output = self.run_cli("verify", "--name", "run", redirect=contextlib.redirect_stderr)
                self.assertEqual(code, 1, name)
                self.assertIn(reason, output)
                path.write_bytes(raw)
                path.chmod(0o600)
        self.assertEqual(self.run_cli("verify", "--name", "run")[0], 0)

    def test_failed_raw_now_parsed_needs_recapture(self):
        first, old = parse_gosi_listing(listing("5", total=2), page=1), ValueError()
        # c·d는 앞 페이지와 번호가 겹치거나 페이지 수가 달라 지금도 실패인 목록이라 통과한다.
        cases = (("a", "6", 2, "parse_gosi_listing", [first, old]), ("b", "6", 2, "parse_gosi_detail", old),
                 ("c", "5", 2, "", None), ("d", "6", 3, "", None))
        for name, second, total, target, failure in cases:
            self.listing.side_effect = [listing("5", total=2), listing(second, page=2, total=total)]
            with patch.object(gosi_batch, target, side_effect=failure) if target else contextlib.nullcontext():
                capture_gosi_batch(name, self.root)
            if target:
                self.assertRaisesRegex(ValueError, "현재 파서는 읽습니다", read_gosi_batch, self.private, name)
            else:
                self.assertEqual(list(read_gosi_batch(self.private, name)), ["5"])

    def test_cli_reports_capture_and_verify(self):
        self.listing.return_value = listing("7")
        run = self.run_cli
        code, output = run("capture", "--name", "a")
        self.assertEqual((code, json.loads(output)["parsed"]), (0, 1))
        code, output = run("verify", "--name", "a")
        self.assertEqual((code, json.loads(output)), (0, {"batch_id": "a", "parsed": 1, "attachments": 1}))
        code, output = run("verify", "--name", "b", redirect=contextlib.redirect_stderr)
        self.assertEqual(code, 1)
        self.assertIn("수집 기록 확인 실패", output)


if __name__ == "__main__":
    unittest.main()
