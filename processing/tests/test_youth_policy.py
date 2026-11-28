import hashlib
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from processing.collection import youth_batch
from processing.collection.youth_batch import capture_youth_batch, read_youth_batch
from processing.collection.youth_policy import (
    PARSER_VERSION, YOUTH_LISTING_PATH, city_notice_search_url, fetch_youth_detail, fetch_youth_listing,
    parse_youth_detail, parse_youth_listing, youth_detail_url,
)

_IMG = "/common/imgView.do?attachId=" + "a" * 64 + "&fileSn=" + "b" * 32 + "&mode=ratioView"


def card(policy_id, category_id="2", *, label="신청기간", period="2026-03-30 ~ 2026-05-29",
         method="온라인 신청: 복지로(http://www.bokjiro.go.kr)", extra=""):
    return f"""<li><a href="/youth/policy/view.do?mId=0201040000&idx={policy_id}&categoryId={category_id}">
      <div class="thumb"><span>복지&middot;건강 </span><figure><img src="{_IMG}&width=250" alt=""></figure></div>
      <div class="cont"><span class="tit">합성 청년 월세 지원 {policy_id}</span>
        <span class="info"><strong>{label}</strong><!-- <span>2023. 01 ~ 2023. 12</span> --><span>{period}</span></span>
        <span class="info"><strong>신청방법</strong><span>{method}</span></span>{extra}
      </div></a></li>"""


def listing(*cards, page=1, total=1, category_id="", action=YOUTH_LISTING_PATH):
    return f"""<html><body><form name="searchForm" action="/search/front/Search.jsp"></form>
    <form id="list" name="list" action="{action}" method="post">
      <input id="page" name="page" type="hidden" value="{page}"/>
      <input id="categoryId" name="categoryId" type="hidden" value="{category_id}"/>
      <div class="bod_head clFix"><p class="page_num">현재 페이지 <span class="bold red">{page}</span> / 전체 페이지 {total}</p>
        <fieldset class="bod_search"><legend class="blind">청년정책 검색</legend>
        <input id="searchTxt" name="searchTxt" type="text" value=""/></fieldset></div>
      <!--  --><div class="bod_photo youth-photo"><ul class="clFix">{"".join(cards)}</ul></div>
      <div class="bod_page"><span>1</span><a href="#" onclick="goPage(2); return false;">2</a></div>
    </form></body></html>""".encode()


VIEWER = f"""<div class="photo_viewer mB20"><div class="bigViewer"><figure>
  <img src="{_IMG}&width=500&heigth=500" alt="합성" /></figure></div>
  <div class="thumb_list"><div class="control" id="thumb_list_control">
  <button type="button" class="prev">이전보기</button><button type="button" class="next">다음보기</button></div>
  <div class="swiper-container"><ul class="swiper-wrapper"><li class="swiper-slide">
  <!-- fn_view_original(원본 이미지 경로 출력) -->
  <button type="button" data-origin='{_IMG}' onclick="fn_view_original(this);"><img src="{_IMG}" alt="합성" /></button>
  </li></ul></div></div>
  <script src="/common/js/swiper/swiper.js"></script><script src="/portal/js/unit/cardNews/view.js"></script>
  <script>
    init_thumbnail_view('.photo_viewer');
  </script></div>"""
INFO = ('<li class="view_write"><span>작성자</span> :[합성과]합성과</li>'
        '<li class="view_date"><span>등록일</span> : 2026-03-18</li><li class="view_hit"><span>조회</span> : 10</li>'
        '<li class="view_hit"><span>신청방법</span> : 온라인 신청: 복지로(http://www.bokjiro.go.kr)</li>')
BODY = "□ 사업개요<br />ㅇ 지원대상: 합성 청년<br />ㅇ 지급규모: 月 20만원"


def detail(policy_id="881", *, category_id="2", info=INFO, viewer=VIEWER, body=BODY, files="",
           action=YOUTH_LISTING_PATH):
    return f"""<!DOCTYPE html><html><head><script>var yh = {{"contextPath": ""}};</script></head><body>
    <form id="list" name="list" action="{action}" method="post">
      <input id="idx" name="idx" type="hidden" value="{policy_id}"/>
      <input id="page" name="page" type="hidden" value="1"/>
      <input id="categoryId" name="categoryId" type="hidden" value="{category_id}"/>
      <div class="bod_wrap"><div class="bod_view"><h4>[복지&middot;건강] 합성 청년 월세 지원</h4>
        <div class="view_info"><ul>{info}</ul></div>
        <div class="view_cont">{viewer}{body}</div>
        <dl class="view_file"><dt><span>첨부 파일</span></dt><dd><script src="/dwr/engine.js"></script>
          <div id="updateFileList" data-saved-file-container="y"><ul>{files}</ul></div></dd></dl>
      </div><div class="box_page"><a href="#" onclick="document.getElementById('list').submit(); return false;">목록</a></div>
      </div></form></body></html>"""


def listed(policy_id="881", **options):
    return parse_youth_listing(listing(card(policy_id, **options)), page=1)[1][0]


class YouthPolicyParserTest(unittest.TestCase):
    def test_listing_keeps_card_text(self):
        total, cards = parse_youth_listing(listing(card("881"), card("877", "4"), page=2, total=12), page=2)
        self.assertEqual(total, 12)
        self.assertEqual(cards[0], {
            "policy_id": "881", "category_id": "2", "category": "복지·건강", "title": "합성 청년 월세 지원 881",
            "application_period": "2026-03-30 ~ 2026-05-29",
            "application_method": "온라인 신청: 복지로(http://www.bokjiro.go.kr)", "page": 2,
        })
        self.assertEqual([item["policy_id"] for item in cards], ["881", "877"])

    def test_listing_rejects_format_or_scope_changes(self):
        for raw, page, message in (
            (listing(card("1"), category_id="3"), 1, "특정 분야"),
            (listing(card("1"), page=1), 2, "페이지 번호"),
            (listing(card("1"), action="/youth/policy/list.do?mId=0201010000"), 1, "구조"),
            (listing(card("1"), card("1")), 1, "같은 정책 번호"),
            (listing(card("1", label="접수기간")), 1, "구조"),
            (listing(card("1", extra="<span>추가 안내</span>")), 1, "구조"),
            # span이 아닌 .info·p가 아닌 .page_num은 IndexError·TypeError가 아니라 형식 오류여야 한다.
            (listing(card("1").replace('<span class="info"><strong>신청기간', '<em class="info"><strong>신청기간')),
             1, "구조"),
            (listing(card("1")).replace(b"<fieldset", b'<span class="page_num"></span><fieldset'), 1, "구조"),
            # tit·info가 함께 붙은 span은 항목으로 세어 IndexError나 앞 항목 빈 값 채우기 없이 거부한다.
            (listing(card("1").replace('<span class="tit">합성 청년 월세 지원 1</span>',
                                       '<span class="tit info"><strong>x</strong></span>')), 1, "구조"),
            (listing(card("1").replace('<span class="tit">합성 청년 월세 지원 1</span>', "").replace(
                '<span>온라인 신청: 복지로(http://www.bokjiro.go.kr)</span></span>',
                '</span><span class="tit info">제목<span>x</span></span>')), 1, "구조"),
            (listing(), 1, "구조"),
            (b"\xff", 1, "구조"),
            # 목록도 공용 토큰 경계로 읽는다. 브라우저는 빈 요소가 아닌 `<span/>`을 닫지 않아 뒤 카드 구조가 어긋난다.
            (listing(card("1", extra='<span class="note"/>')), 1, "구조"),
            (listing(card("1")).replace(b"<!--  -->", b"<!-->"), 1, "목록 페이지에 브라우저와 해석이 갈리는"),
            (listing(card("1")).replace(b"<html>", b"<html><script><!--<script></script>--></script>"), 1,
             "목록 페이지에 브라우저와 해석이 갈리는"),
            # 원문 텍스트 요소는 문자 참조를 풀지 않거나 브라우저 화면에 나오지 않아 카드 표시 문구와 달라진다.
            (listing(card("1").replace("지원 1<", "지원 1<textarea>&lt;B</textarea><")), 1, "구조"),
            (listing(card("1").replace("지원 1<", "지원 1<iframe>숨김</iframe><")), 1, "구조"),
            # 브라우저는 template 안의 짝 없는 `</style>`을 무시해 뒤 목록 폼 전부를 숨긴다.
            (listing(card("1")).replace(b"<body>", b"<body><template></style><style></template></style>"), 1, "구조"),
            # 실제 목록 5쪽에 없던 속성·태그·부모 짝(숨김 속성, 카드 안 style·script, a 안 a, p 안 div)은 거부한다.
            *((listing(card("1").replace(old, new, 1)), 1, "구조") for old, new in (
                ('"info">', '"info" hidden>'), ('"info">', '"info" style="display:none">'),
                ('"info">', '"info" popover>'), ("<li>", "<li hidden>"), ("지원 1<", "지원 1<style>.cont{}</style><"),
                ("지원 1<", '지원 1<script>document.write("<!--")</script><'),
                ('<span class="tit">', '<a href="#"></a><span class="tit">'))),
            (listing(card("1")).replace(b'id="list"', b'id="list" hidden'), 1, "구조"),
            (listing(card("1")).replace(b"</span> /", b"</span><div></div> /"), 1, "구조"),
        ):
            with self.subTest(message=message, page=page), self.assertRaisesRegex(ValueError, message):
                parse_youth_listing(raw, page=page)

    def test_detail_keeps_source_text_and_city_candidate(self):
        record = parse_youth_detail(detail(), policy_id="881", card=listed())
        self.assertEqual(record["title"], "[복지·건강] 합성 청년 월세 지원")
        self.assertEqual(record["official_url"], "https://www.anseong.go.kr/youth/policy/view.do?mId=0201040000&idx=881")
        self.assertEqual(record["fields"], {
            "description": "□ 사업개요\nㅇ 지원대상: 합성 청년\nㅇ 지급규모: 月 20만원", "published_date": "2026-03-18",
            "author": "[합성과]합성과", "application_method": "온라인 신청: 복지로(http://www.bokjiro.go.kr)",
        })
        self.assertEqual(record["listing"]["application_period"], "2026-03-30 ~ 2026-05-29")
        self.assertEqual(record["listing_period_range"], {"start": "2026-03-30", "end": "2026-05-29"})
        self.assertEqual(record["unknown"], {"support_target": "not_extracted", "support_amount": "not_extracted"})
        self.assertEqual(record["city_notice_candidate"],
                         {"search_url": city_notice_search_url("합성 청년 월세 지원 881"), "status": "unverified"})
        self.assertIn("searchTxt=%ED%95%A9%EC%84%B1", record["city_notice_candidate"]["search_url"])
        self.assertEqual(record["images"], ["https://www.anseong.go.kr" + _IMG])
        self.assertEqual((record["category_id"], record["review_flags"]), ("2", ["application_period_unconfirmed"]))

    def test_detail_flags_status_word_or_placeholder_method(self):
        # 실제 874·875(`모집마감`)·877(`.`)처럼 카드 기간이 사업 기간과 같고 신청방법이 방법이 아닌 경우.
        for listed_method, detail_method in (("모집마감", "모집마감"), (".", "."), ("온라인 신청", "접수 종료"),
                                             ("온라인 신청", "조기마감"), ("온라인 신청", "(마감)"),
                                             ("온라인 신청", "신청 (마감)"), ("온라인 신청", "접수 조기마감"),
                                             ("온라인 신청(마감)", "온라인 신청(마감)")):
            with self.subTest(method=detail_method):
                info = INFO.replace("온라인 신청: 복지로(http://www.bokjiro.go.kr)", detail_method)
                record = parse_youth_detail(detail(info=info), policy_id="881", card=listed(
                    period="2026-01-01 ~ 2026-12-31", method=listed_method))
                flags = ["application_method_not_method", "application_period_unconfirmed"]
                if listed_method != detail_method:
                    flags.append("listing_method_differs")
                self.assertEqual(record["review_flags"], flags)
                self.assertEqual(record["listing_period_range"], {"start": "2026-01-01", "end": "2026-12-31"})
                self.assertEqual(record["fields"]["application_method"], detail_method)
        # 방법 문구 안에 상태어가 섞인 값은 방법으로 본다.
        method = "선착순 마감 시까지 방문 접수"
        info = INFO.replace("온라인 신청: 복지로(http://www.bokjiro.go.kr)", method)
        record = parse_youth_detail(detail(info=info), policy_id="881", card=listed(method=method))
        self.assertEqual(record["review_flags"], ["application_period_unconfirmed"])

    def test_detail_flags_differences_without_overwriting(self):
        files = "<li><a href=\"#\" onclick=\"fn_egov_downFile('x','y'); return false;\">안내.pdf</a></li>"
        info = INFO.replace('<li class="view_hit"><span>신청방법</span> : 온라인 신청: 복지로(http://www.bokjiro.go.kr)</li>', "")
        for period, flag in (("2026-05-29 ~ 2026-03-30", "period_inverted"), ("상시", "period_unparsed"),
                             ("", "missing:application_period")):
            with self.subTest(period=period):
                record = parse_youth_detail(detail(category_id="4", info=info, viewer="", files=files),
                                            policy_id="881", card=listed(period=period))
                self.assertEqual(record["review_flags"], sorted([
                    flag, "application_period_unconfirmed", "attachment", "listing_category_differs",
                    "listing_method_differs", "missing:application_method"]))
                self.assertIsNone(record["listing_period_range"])
                self.assertEqual(record["listing"]["application_period"], period or None)
                self.assertIsNone(record["fields"]["application_method"])
                self.assertEqual(record["images"], [])

    def test_detail_rejects_mismatch_or_format_changes(self):
        cases = (
            (detail("882"), "번호가 요청과 일치하지"),
            (detail(action="/youth/policy/list.do?mId=0201010000"), "게시판이 요청과 일치하지"),
            (detail(viewer=VIEWER.replace("다음보기", "신청 안내")), "대표 이미지 영역"),
            (detail(viewer=VIEWER.replace("/portal/js/unit/cardNews/view.js", "/x.js")), "대표 이미지 영역"),
            (detail(viewer=VIEWER + VIEWER), "대표 이미지 영역"),
            # 중복 class는 브라우저가 첫 값을 써 틀이 아니라 본문이 되고, hidden·style은 이미지를 숨길 수 있다.
            (detail(viewer=VIEWER.replace('<div class="photo_viewer', '<div class="x" class="photo_viewer')),
             "대표 이미지 영역"),
            (detail(viewer=VIEWER.replace('mB20"', 'mB20" hidden')), "대표 이미지 영역"),
            (detail(viewer=VIEWER.replace('mB20"', 'mB20" style="display:none"')), "대표 이미지 영역"),
            (detail(viewer=VIEWER.replace("<figure>", "<figure hidden>")), "대표 이미지 영역"),
            (detail(viewer=VIEWER.replace("<figure>", '<figure style="display:none">')), "대표 이미지 영역"),
            # 대표 이미지 틀도 공용 토큰 검사(스크립트 이중 이스케이프)를 거친다.
            (detail(viewer=VIEWER.replace("init_thumbnail_view('.photo_viewer');", "<!--<script></script>-->")),
             "해석이 갈리는"),
            (detail(info=INFO + "<li><span>담당자</span> : 합성</li>"), "알 수 없거나 중복된 항목"),
            (detail(info=INFO + "<li><span>작성자</span> : 합성</li>"), "알 수 없거나 중복된 항목"),
            (detail(body=""), "본문 텍스트가 없습니다"),
            (detail(body='<p style="display:none">숨김</p>'), "숨김"),
            # 실제 상세 24쪽에 없던 속성·부모 짝과 생략한 종료 태그는 공지 허용 목록이 받더라도 거부한다.
            (detail(viewer=VIEWER.replace("<figure>", "<figure popover>")), "대표 이미지 영역"),
            (detail().replace('"bod_view"', '"bod_view" title="x"'), "숨김"),
            (detail(body='<span style="font-size:4px">작게</span>'), "숨김"),
            (detail(body="<ul><li>가<li>나</li></ul>"), "숨김"),
            (detail(body="<ul><li>가</ul>"), "구조"),
            (detail(category_id="x"), "분야 번호"),
            (detail().replace('type="hidden" value="2"/>', 'type="hidden"/>'), "없거나 중복"),
        )
        for text, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                parse_youth_detail(text, policy_id="881", card=listed())
        with self.assertRaisesRegex(ValueError, "목록 카드"):
            parse_youth_detail(detail(), policy_id="881", card=listed("877"))

    def test_requests_use_fixed_paths(self):
        with patch("processing.collection.youth_policy._fetch", return_value=b"ok") as fetch:
            fetch_youth_listing(3, limit=10)
            fetch_youth_detail("881", limit=20)
        self.assertEqual(fetch.call_args_list[0].args, ("POST", YOUTH_LISTING_PATH, b"page=3", 10))
        self.assertEqual(fetch.call_args_list[1].args,
                         ("GET", "/youth/policy/view.do?mId=0201040000&idx=881", None, 20))
        self.assertEqual(fetch.call_args.kwargs, {"source": "안성청년포털"})
        for value in ("0", "1" * 19, "１", 881):
            with self.subTest(value=value), self.assertRaises(ValueError):
                youth_detail_url(value)
        with self.assertRaises(ValueError):
            fetch_youth_listing(0, limit=10)


class YouthBatchTest(unittest.TestCase):
    def setUp(self):
        self.private = Path(self.enterContext(TemporaryDirectory())).resolve() / "private"
        self.root = self.private / youth_batch.YOUTH_SECTION
        self.sleep = self.enterContext(patch("processing.collection.youth_batch.sleep"))
        self.listing = self.enterContext(patch("processing.collection.youth_batch.fetch_youth_listing"))
        self.detail = self.enterContext(patch("processing.collection.youth_batch.fetch_youth_detail"))
        self.listing.side_effect = lambda page, **_: listing(card(str(10 - page)), page=page, total=2)
        self.detail.side_effect = lambda policy_id, **_: detail(policy_id, body=BODY + policy_id).encode()

    def test_capture_keeps_card_with_detail_and_verifies_archive(self):
        summary = capture_youth_batch("run", self.root)
        self.assertEqual(summary, {"batch_id": "run", "status": "complete", "discovery_status": "complete",
                                   "selected": 2, "parsed": 2})
        self.assertEqual({call.args for call in self.sleep.call_args_list}, {(1.5,)})
        directory = self.root / "run"
        receipt = json.loads((directory / "batch.json").read_text(encoding="utf-8"))
        self.assertEqual((receipt["schema_version"], receipt["pages"][0]["method"]),
                         ("citizen-youth-policy-batch-v1", "POST"))
        stored = json.loads((directory / "parsed-8.json").read_text(encoding="utf-8"))
        self.assertEqual((stored["schema_version"], stored["parser_version"]), ("citizen-youth-policy-v1", PARSER_VERSION))
        self.assertEqual(stored["sha256"], hashlib.sha256((directory / "detail-8.html").read_bytes()).hexdigest())
        self.assertEqual(stored["record"]["listing"]["page"], 2)

        records = read_youth_batch(self.private, "run")
        self.assertEqual(list(records), ["9", "8"])
        self.assertEqual(records["8"]["record"], stored["record"])
        self.assertEqual(records["8"]["raw_asset_path"], "collection-youth-policies/run/detail-8.html")

        parsed = directory / "parsed-8.json"
        changed = json.loads(parsed.read_text(encoding="utf-8"))
        changed["record"]["listing"]["application_period"] = "2026-01-01 ~ 2026-12-31"
        parsed.write_text(json.dumps(changed, ensure_ascii=False), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "파싱 결과가 원본과 다릅니다"):
            read_youth_batch(self.private, "run")
        listing_file = directory / "list-1.html"
        listing_file.write_bytes(listing_file.read_bytes() + b" ")
        with self.assertRaisesRegex(ValueError, "원본 해시"):
            read_youth_batch(self.private, "run")
        os.chmod(directory, 0o755)
        with self.assertRaisesRegex(ValueError, "실행 사용자만"):
            read_youth_batch(self.private, "run")

    def test_failed_detail_keeps_raw_and_partial_archive_still_verifies(self):
        self.detail.side_effect = [detail("1").encode(), ValueError("합성 수신 실패")]
        summary = capture_youth_batch("partial", self.root)
        self.assertEqual((summary["status"], summary["parsed"]), ("partial", 0))
        receipt = json.loads((self.root / "partial" / "batch.json").read_text(encoding="utf-8"))
        self.assertEqual([item["status"] for item in receipt["items"]], ["parse_failed", "fetch_failed"])
        self.assertTrue((self.root / "partial" / "detail-9.html").exists())
        self.assertEqual(read_youth_batch(self.private, "partial"), {})


if __name__ == "__main__":
    unittest.main()
