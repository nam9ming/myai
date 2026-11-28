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


def card(policy_id, category_id="2", *, label="신청기간", period="2026-03-30 ~ 2026-05-29", extra=""):
    return f"""<li><a href="/youth/policy/view.do?mId=0201040000&idx={policy_id}&categoryId={category_id}">
      <div class="thumb"><span>복지&middot;건강 </span><figure><img src="{_IMG}&width=250" alt=""></figure></div>
      <div class="cont"><span class="tit">합성 청년 월세 지원 {policy_id}</span>
        <span class="info"><strong>{label}</strong><!-- <span>2023. 01 ~ 2023. 12</span> --><span>{period}</span></span>
        <span class="info"><strong>신청방법</strong><span>온라인 신청: 복지로(http://www.bokjiro.go.kr)</span></span>{extra}
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
            (listing(), 1, "구조"),
            (b"\xff", 1, "구조"),
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
        self.assertEqual(record["application_period_range"], {"start": "2026-03-30", "end": "2026-05-29"})
        self.assertEqual(record["unknown"], {"support_target": "description_only", "support_amount": "description_only"})
        self.assertEqual(record["city_notice_candidate"],
                         {"search_url": city_notice_search_url("합성 청년 월세 지원 881"), "status": "unverified"})
        self.assertIn("searchTxt=%ED%95%A9%EC%84%B1", record["city_notice_candidate"]["search_url"])
        self.assertEqual(record["images"], ["https://www.anseong.go.kr" + _IMG])
        self.assertEqual((record["category_id"], record["review_flags"]), ("2", []))

    def test_detail_flags_differences_without_overwriting(self):
        files = "<li><a href=\"#\" onclick=\"fn_egov_downFile('x','y'); return false;\">안내.pdf</a></li>"
        info = INFO.replace('<li class="view_hit"><span>신청방법</span> : 온라인 신청: 복지로(http://www.bokjiro.go.kr)</li>', "")
        for period, flag in (("2026-05-29 ~ 2026-03-30", "period_inverted"), ("상시", "period_unparsed"),
                             ("", "missing:application_period")):
            with self.subTest(period=period):
                record = parse_youth_detail(detail(category_id="4", info=info, viewer="", files=files),
                                            policy_id="881", card=listed(period=period))
                self.assertEqual(record["review_flags"], sorted([
                    flag, "attachment", "listing_category_differs", "listing_method_differs",
                    "missing:application_method"]))
                self.assertIsNone(record["application_period_range"])
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
            (detail(info=INFO + "<li><span>담당자</span> : 합성</li>"), "알 수 없거나 중복된 항목"),
            (detail(info=INFO + "<li><span>작성자</span> : 합성</li>"), "알 수 없거나 중복된 항목"),
            (detail(body=""), "본문 텍스트가 없습니다"),
            (detail(body='<p style="display:none">숨김</p>'), "숨김"),
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
