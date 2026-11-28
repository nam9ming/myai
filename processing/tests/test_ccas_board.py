import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from processing.collection import media
from processing.collection.board_batch import BOARD_SECTION, capture_board_batch
from processing.collection.libraries import board_parser_version, parse_board_media, parse_board_notice
from processing.collection.library_listing import parse_board_listing
from processing.collection.official_web import (
    BOARDS, board_detail_url, board_listing_path, fetch_board_detail, fetch_board_listing,
)
from processing.tests.test_board_notices import CITY_VIEW, _listing, _notice
from processing.tests.test_edu_board import ATTACH, ATTACHMENT, FILE_SN, _edu_row

# 2026-11-28 실제 목록·상세에서 확인한 문화도시 안성 공지사항의 메뉴·게시판 번호와 폼 주소
MENU, PT_IDX = "0501000000", "1363"
VIEW = f"/ccas/bbs/view.do?ptIdx={PT_IDX}&amp;mId={MENU}"
LIST = f"/ccas/bbs/list.do?ptIdx={PT_IDX}&amp;mId={MENU}"
# 실제 이미지형 본문(199589·202684)의 그림 표기. onerror 속성은 공유 본문 허용 목록 밖이다.
POSTER = ('<p><img src="/common/imgView.do?attachId=' + "a" * 64 + "&amp;fileSn=" + "b" * 32
          + '&amp;mode=origin" onerror="this.src=\'/common/img/error/error_img.png\'" alt="포스터"></p>')


def _row(notice_id, number="26"):
    return _edu_row(notice_id, number, board=PT_IDX, menu=MENU)


def _ccas_listing(rows, *, action=LIST, **pages):
    form = f'<form id="list" name="list" action="{action}" method="post">'
    return _listing(rows, **pages).replace('<form id="list">', form, 1).encode()


def _ccas_notice(notice_id="202581", body="<p>합성 일정 변경 본문</p>", view=VIEW, attachment="", context=""):
    script = f'<script>var yh = {{"mId": "{MENU}", "contextPath": "{context}"}};</script>'
    page = _notice(notice_id, body, view=view).replace("합성 시청 공지", "합성 문화도시 공지")
    return script + page.replace("</div></div>", "</div>" + attachment + "</div>", 1)


class CcasRegistryTest(unittest.TestCase):
    def test_board_uses_its_own_path_menu_and_board_number(self):
        info = BOARDS["ccas"]
        self.assertEqual((info.label, info.source, info.title_class, info.context_path, info.check_list_form),
                         ("문화도시 안성 공지", "ccas_notice", None, "", True))
        self.assertEqual(board_listing_path("ccas"), "/ccas/bbs/list.do?ptIdx=1363&mId=0501000000")
        self.assertEqual(board_detail_url("ccas", "202581"),
                         "https://www.anseong.go.kr/ccas/bbs/view.do?bIdx=202581&mId=0501000000&ptIdx=1363")
        self.assertEqual(board_parser_version("ccas"), "ccas-notice-parser-v1")
        # 축제포털 공지 목록에는 전체 페이지 표시가 없어 공유 게시판으로 등록하지 않았다.
        self.assertNotIn("festival", BOARDS)

    @patch("processing.collection.official_web.HTTPSConnection")
    def test_requests_use_the_ccas_path(self, connect):
        response = connect.return_value.getresponse.return_value.__enter__.return_value
        response.status, response.getheader.return_value, response.read.return_value = 200, None, b"ok"
        fetch_board_listing("ccas", 2, limit=64)
        fetch_board_detail("ccas", "202581", limit=64)
        listing, detail = connect.return_value.request.call_args_list
        self.assertEqual((listing.args, listing.kwargs["body"]),
                         (("POST", "/ccas/bbs/list.do?ptIdx=1363&mId=0501000000"), b"page=2"))
        self.assertEqual(detail.args, ("GET", "/ccas/bbs/view.do?bIdx=202581&mId=0501000000&ptIdx=1363"))


class CcasListingTest(unittest.TestCase):
    def test_listing_needs_ccas_links_and_list_form(self):
        rows = _row("202684") + _row("202581", "25")
        self.assertEqual(parse_board_listing(_ccas_listing(rows), board="ccas", page=1), (3, ["202684", "202581"], []))
        with self.assertRaisesRegex(ValueError, "^문화도시 안성 공지 목록 HTML 구조"):
            parse_board_listing(_ccas_listing(_edu_row("5", board="16", menu=MENU)), board="ccas", page=1)
        for action in ("/festival/bbs/list.do?ptIdx=16&amp;mId=0401000000", CITY_VIEW.replace("view", "list"), ""):
            with self.subTest(action=action), self.assertRaisesRegex(ValueError, "^문화도시 안성 공지 목록의 게시판이 요청과"):
                parse_board_listing(_ccas_listing(rows, action=action), board="ccas", page=1)
        with self.assertRaises(ValueError):
            parse_board_listing(_ccas_listing(rows), board="city", page=1)


class CcasNoticeTest(unittest.TestCase):
    def test_notice_reads_h4_title_and_checks_its_view_form(self):
        self.assertEqual(parse_board_notice(_ccas_notice(), board="ccas", notice_id="202581"), {
            "source": "ccas_notice",
            "external_id": "202581",
            "title": "합성 문화도시 공지",
            "official_url": board_detail_url("ccas", "202581"),
            "fields": {"description": "합성 일정 변경 본문", "published_date": "2026-11-27"},
        })
        for page, board in ((_ccas_notice(view=CITY_VIEW), "ccas"), (_ccas_notice(view=None), "ccas"),
                            (_ccas_notice(), "city")):
            with self.subTest(board=board, page=page[:60]), self.assertRaisesRegex(ValueError, "게시판이 요청과"):
                parse_board_notice(page, board=board, notice_id="202581")

    def test_attachment_uses_root_context_path(self):
        page = _ccas_notice(attachment=ATTACHMENT)
        self.assertEqual(parse_board_media(page, board="ccas", notice_id="202581")[0]["source_url"],
                         f"https://www.anseong.go.kr/cmm/fms/FileDown.do?atchFileId={ATTACH}&fileSn={FILE_SN}")
        with self.assertRaisesRegex(ValueError, "경로"):
            parse_board_media(_ccas_notice(attachment=ATTACHMENT, context="/ccas"), board="ccas", notice_id="202581")

    def test_poster_image_with_onerror_fails_closed(self):
        for parse in (parse_board_notice, parse_board_media):
            with self.subTest(parse=parse.__name__), self.assertRaisesRegex(ValueError, "^문화도시 안성 공지 .*숨김·미확인"):
                parse(_ccas_notice(body="<p>본문</p>" + POSTER), board="ccas", notice_id="202581")


class CcasPipelineTest(unittest.TestCase):
    def setUp(self):
        self.private = Path(self.enterContext(TemporaryDirectory())).resolve() / "private"
        self.private.mkdir(mode=0o700)

    def capture(self, details):
        with (patch("processing.collection.board_batch.sleep"),
              patch("processing.collection.board_batch.fetch_board_listing",
                    return_value=_ccas_listing(_row("202684") + _row("202581", "25"), total=1)),
              patch("processing.collection.board_batch.fetch_board_detail",
                    side_effect=lambda _board, notice_id, limit: details[notice_id].encode())):
            return capture_board_batch("ccas", "ccas", self.private / BOARD_SECTION)

    def test_poster_notice_stays_parse_failed_with_its_original(self):
        summary = self.capture({"202684": _ccas_notice("202684", body=POSTER), "202581": _ccas_notice()})
        self.assertEqual((summary["status"], summary["selected"], summary["parsed"]), ("partial", 2, 1))
        directory = self.private / BOARD_SECTION / "ccas"
        items = {item["web_id"]: item for item in json.loads((directory / "batch.json").read_bytes())["items"]}
        self.assertEqual(items["202684"]["status"], "parse_failed")
        self.assertIn("숨김·미확인", items["202684"]["error"])
        self.assertTrue((directory / "detail-202684.html").exists())
        parsed = json.loads((directory / "parsed-202581.json").read_bytes())
        self.assertEqual((parsed["parser_version"], parsed["record"]["source"]),
                         ("ccas-notice-parser-v1", "ccas_notice"))

    def test_media_inspect_needs_the_id_on_a_ccas_listing(self):
        self.capture({"202684": _ccas_notice("202684"), "202581": _ccas_notice()})
        page = _ccas_notice(attachment=ATTACHMENT).encode()
        with patch.object(media, "fetch_board_detail", return_value=page) as fetch:
            for web_id, batch, error in (("202581", None, "--batch"), ("200586", "ccas", "목록 원본에 없는 공지 번호")):
                with self.subTest(web_id=web_id), self.assertRaisesRegex(ValueError, f"^문화도시 안성 공지.*{error}"):
                    media.inspect_notice(self.private, web_id, "rejected", board="ccas", batch=batch)
            fetch.assert_not_called()
            media.inspect_notice(self.private, "202581", "notice", board="ccas", batch="ccas")
        notice = media._notice(self.private, "notice")
        self.assertEqual((notice["board"], notice["listing_batch"]), ("ccas", "ccas"))


if __name__ == "__main__":
    unittest.main()
