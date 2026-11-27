import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from processing.collection import media
from processing.collection.board_batch import BOARD_SECTION, capture_board_batch
from processing.collection.d03_sources import capture_assets
from processing.collection.libraries import parse_board_media, parse_board_notice, parse_library_media
from processing.collection.library_listing import parse_board_listing
from processing.collection.official_web import (
    BOARDS, board_detail_url, board_listing_path, fetch_board_detail, fetch_board_listing,
)
from processing.tests.test_board_notices import CITY_VIEW, _listing, _notice
from processing.tests.test_collection_media import hwpx

EDU_VIEW = "/edu/portal/bbs/view.do?ptIdx=300&amp;mId=0901040000"


ATTACH = "c" * 64
FILE_SN = "d" * 32
ATTACHMENT = (f'<dl class="view_file"><dt>첨부 파일</dt><dd><ul><li><a href="#" '
              f'onclick="fn_egov_downFile(\'{ATTACH}\',\'{FILE_SN}\'); return false;">안내.hwpx [1 KByte]</a>'
              '</li></ul></dd></dl>')


def _edu_notice(notice_id="3838", title_markup='<div class="bod_view_title">합성 배움 공지</div>', view=EDU_VIEW,
                context="/edu", body="<p>합성 본문</p>", attachment=""):
    script = f'<script>var yh = {{"mId": "0901040000", "contextPath": "{context}"}};</script>' if context is not None else ""
    page = _notice(notice_id, body, view=view).replace("<h4>합성 시청 공지</h4>", title_markup)
    return script + page.replace("</div></div>", "</div>" + attachment + "</div>", 1)


def _edu_row(notice_id, number="1", board="300", menu="0901040000"):
    link = f"""<a href="#" onclick="goTo.view('list','{notice_id}','{board}','{menu}'); return false;">공지</a>"""
    return f'<tr><td class="list_num">{number}</td><td class="list_tit">{link}</td></tr>'


class EduBoardTest(unittest.TestCase):
    def test_edu_board_uses_its_own_path_menu_and_board_number(self):
        self.assertEqual(BOARDS["edu"].label, "안성배움e 공지")
        self.assertEqual(board_listing_path("edu"), "/edu/portal/bbs/list.do?ptIdx=300&mId=0901040000")
        self.assertEqual(board_detail_url("edu", "3838"),
                         "https://www.anseong.go.kr/edu/portal/bbs/view.do?bIdx=3838&mId=0901040000&ptIdx=300")
        self.assertEqual(board_detail_url("city", "1"),
                         "https://www.anseong.go.kr/portal/bbs/view.do?bIdx=1&mId=0501010000&ptIdx=16")

    def test_listing_links_must_match_board_number(self):
        rows = _edu_row("4225", "330") + _edu_row("4224", "329")
        self.assertEqual(parse_board_listing(_listing(rows).encode(), board="edu", page=1), (3, ["4225", "4224"], []))
        for row in (_edu_row("5", board="16"), _edu_row("5", menu="0501010000")):
            with self.subTest(row=row), self.assertRaisesRegex(ValueError, "^안성배움e 공지 목록"):
                parse_board_listing(_listing(row).encode(), board="edu", page=1)
        with self.assertRaises(ValueError):
            parse_board_listing(_listing(_edu_row("5")).encode(), board="city", page=1)

    def test_detail_and_media_check_edu_view_form(self):
        record = parse_board_notice(_edu_notice(), board="edu", notice_id="3838")
        self.assertEqual((record["source"], record["title"], record["official_url"]),
                         ("edu_notice", "합성 배움 공지", board_detail_url("edu", "3838")))
        self.assertEqual(parse_board_media(_edu_notice(), board="edu", notice_id="3838"), [])
        with self.assertRaisesRegex(ValueError, "게시판"):
            parse_board_notice(_edu_notice(view=CITY_VIEW), board="edu", notice_id="3838")
        with self.assertRaisesRegex(ValueError, "게시판"):
            parse_board_notice(_notice("3838", view=EDU_VIEW), board="city", notice_id="3838")

    def test_edu_title_comes_only_from_its_title_block(self):
        for markup, message in (
            ("<h4>합성 배움 공지</h4>", "제목 영역의 형식"),
            ('<div class="bod_view_title"></div>', "제목이 없습니다"),
            ('<div class="bod_view_title">가</div><div class="bod_view_title">나</div>', "필드가 중복"),
            ('<div class="bod_view_title">가</div><h4>나</h4>', "제목 영역의 형식"),
            ('<div><div class="bod_view_title">가</div></div>', "제목이 없습니다"),
        ):
            with self.subTest(markup=markup), self.assertRaisesRegex(ValueError, "^안성배움e 공지 .*" + message):
                parse_board_notice(_edu_notice(title_markup=markup), board="edu", notice_id="3838")
        inner = parse_board_notice(_edu_notice(body="<h4>소제목</h4><p>본문</p>"), board="edu", notice_id="3838")
        self.assertEqual(inner["fields"]["description"], "소제목\n본문")
        for page in (_notice("3838"), _notice("3838", view="/library/bbs/view.do?ptIdx=16&amp;mId=0401010000")):
            with self.subTest(page=page[:40]), self.assertRaisesRegex(ValueError, "게시판이 요청과 일치하지 않습니다"):
                parse_board_notice(page, board="edu", notice_id="3838")
        with self.assertRaisesRegex(ValueError, "게시판"):
            parse_board_notice(_edu_notice(view=None), board="edu", notice_id="3838")

    def test_edu_attachment_uses_declared_context_path(self):
        page = _edu_notice(attachment=ATTACHMENT)
        self.assertEqual(parse_board_media(page, board="edu", notice_id="3838")[0]["source_url"],
                         f"https://www.anseong.go.kr/edu/cmm/fms/FileDown.do?atchFileId={ATTACH}&fileSn={FILE_SN}")
        repeated = page.replace("</script>", '</script><script>var yh = {"contextPath": "/edu"};</script>', 1)
        for variant in (_edu_notice(attachment=ATTACHMENT, context=None), repeated,
                        _edu_notice(attachment=ATTACHMENT, context=""), _edu_notice(attachment=ATTACHMENT, context="/portal")):
            with self.subTest(variant=variant[:60]), self.assertRaisesRegex(ValueError, "경로"):
                parse_board_media(variant, board="edu", notice_id="3838")
        library = _notice("17", view=None)
        self.assertEqual(parse_library_media('<script>var yh = {"contextPath": ""};</script>' + library,
                                             notice_id="17"), [])
        with self.assertRaisesRegex(ValueError, "경로"):
            parse_library_media('<script>var yh = {"contextPath": "/edu"};</script>' + library, notice_id="17")
        duplicate = page.replace('class="bod_view_title"', 'class="o" class="bod_view_title"')
        with self.assertRaisesRegex(ValueError, "속성이 중복"):
            parse_board_media(duplicate, board="edu", notice_id="3838")

    def test_context_path_is_read_only_from_page_scripts(self):
        fake = '{"contextPath": "/portal"}'
        body_only = _edu_notice(attachment=ATTACHMENT, context=None, body=f"<p>예시 {fake}</p>")
        with self.assertRaisesRegex(ValueError, "경로"):
            parse_board_media(body_only, board="edu", notice_id="3838")
        noisy = _edu_notice(attachment=ATTACHMENT, body=f"<p>예시 {fake}</p>") + f"<!-- {fake} -->"
        self.assertEqual(len(parse_board_media(noisy, board="edu", notice_id="3838")), 1)
        city = f'<script>var yh = {{"contextPath": ""}};</script><!-- {fake} -->' + _notice("3838", f"<p>{fake}</p>")
        self.assertEqual(parse_board_media(city, board="city", notice_id="3838"), [])
        inner = _edu_notice(attachment=ATTACHMENT).replace("<p>합성 본문</p>", f"<p>본문</p><script>var y = {fake};</script>")
        self.assertEqual(len(parse_board_media(inner, board="edu", notice_id="3838")), 1)

    def test_context_path_requires_the_page_configuration_object(self):
        no_config = _edu_notice(attachment=ATTACHMENT, context=None)
        for script in ('<script>// {"contextPath": "/edu"}\n</script>',
                       '<script>var note = \'{"contextPath": "/edu"}\';</script>',
                       '<script>var yh = {"contextPath": "/edu"}; // 설정</script>',
                       '<script>var yh = {"contextPath": "/edu", "contextPath": "/edu"};</script>',
                       '<script>var yh = {"contextPath": 1};</script>'):
            with self.subTest(script=script), self.assertRaisesRegex(ValueError, "경로"):
                parse_board_media(script + no_config, board="edu", notice_id="3838")
        mixed = '<script>// {"contextPath": "/portal"}\n</script>' + _edu_notice(attachment=ATTACHMENT)
        self.assertEqual(len(parse_board_media(mixed, board="edu", notice_id="3838")), 1)
        city = '<script>// {"contextPath": "/edu"}\n</script>' + _notice("3838")
        self.assertEqual(parse_board_media(city, board="city", notice_id="3838"), [])

    @patch("processing.collection.official_web.HTTPSConnection")
    def test_edu_requests_use_edu_paths(self, connect):
        response = connect.return_value.getresponse.return_value.__enter__.return_value
        response.status, response.getheader.return_value, response.read.return_value = 200, None, b"ok"
        fetch_board_listing("edu", 2, limit=64)
        fetch_board_detail("edu", "3838", limit=64)
        listing, detail = connect.return_value.request.call_args_list
        self.assertEqual((listing.args, listing.kwargs["body"]),
                         (("POST", "/edu/portal/bbs/list.do?ptIdx=300&mId=0901040000"), b"page=2"))
        self.assertEqual(detail.args, ("GET", "/edu/portal/bbs/view.do?bIdx=3838&mId=0901040000&ptIdx=300"))


class EduPipelineTest(unittest.TestCase):
    def setUp(self):
        self.private = Path(self.enterContext(TemporaryDirectory())).resolve() / "private"
        self.private.mkdir(mode=0o700)

    def test_batch_and_d03_round_trip(self):
        with (patch("processing.collection.board_batch.sleep"),
              patch("processing.collection.board_batch.fetch_board_listing",
                    return_value=_listing(_edu_row("3838", "330"), total=1).encode()),
              patch("processing.collection.board_batch.fetch_board_detail",
                    return_value=_edu_notice(attachment=ATTACHMENT).encode())):
            summary = capture_board_batch("edu", "edu", self.private / BOARD_SECTION)
        self.assertEqual((summary["status"], summary["parsed"]), ("complete", 1))
        asset = capture_assets(self.private, "board", "edu", {"3838"})["3838"]
        self.assertEqual(asset["official_url"], board_detail_url("edu", "3838"))

    def test_media_inspect_and_store_round_trip(self):
        with patch.object(media, "fetch_board_detail", return_value=_edu_notice(attachment=ATTACHMENT).encode()):
            self.assertEqual(media.inspect_notice(self.private, "3838", "edu", board="edu")["media"], 1)
        receipt = json.loads((self.private / media.NOTICE_SECTION / "edu" / "notice.json").read_bytes())
        self.assertEqual((receipt["board"], receipt["media"][0]["format"]), ("edu", "hwpx"))
        package = self.private.parent / "edu.hwpx"
        package.write_bytes(hwpx(b"application/hwp+zip"))
        os.chmod(package, 0o600)
        media.store_media(self.private, "edu", 1, package, "edu-file", "2026-11-27T08:00:00Z")
        asset = media.read_media_assets(self.private, "edu-file", {"1"})["1"]
        self.assertEqual(asset["official_url"], board_detail_url("edu", "3838"))


class EduVersionTest(unittest.TestCase):
    def test_edu_batch_records_edu_parser_version(self):
        root = Path(self.enterContext(TemporaryDirectory())).resolve() / "private"
        root.mkdir(mode=0o700)
        with (patch("processing.collection.board_batch.sleep"),
              patch("processing.collection.board_batch.fetch_board_listing",
                    return_value=_listing(_edu_row("3838", "330"), total=1).encode()),
              patch("processing.collection.board_batch.fetch_board_detail", return_value=_edu_notice().encode())):
            capture_board_batch("edu", "edu", root / BOARD_SECTION)
        parsed = json.loads((root / BOARD_SECTION / "edu" / "parsed-3838.json").read_bytes())
        self.assertEqual(parsed["parser_version"], "edu-notice-parser-v3")
        for page in (_edu_notice(title_markup='<div class="bod_view_title" hidden>숨김</div>'),
                     _edu_notice().replace('<div class="bod_view">', '<div class="bod_view" hidden>'),
                     _edu_notice(body='<p>본문<img hidden src="/common/imgView.do" alt=""></p>'),
                     _edu_notice(body='<p style="display:none">숨김</p>'),
                     _edu_notice(attachment=ATTACHMENT.replace("<dd>", "<dd hidden>")),
                     _edu_notice(body='<p>앞</p><!--->보임-->'),
                     _edu_notice(body='<iframe>숨김</iframe>')):
            for parse in (parse_board_notice, parse_board_media):
                with self.subTest(parse=parse.__name__, page=page[-70:]), \
                        self.assertRaisesRegex(ValueError, "^안성배움e 공지 .*(숨김|해석이 갈리는)"):
                    parse(page, board="edu", notice_id="3838")


class CityTitleTest(unittest.TestCase):
    def test_city_ignores_edu_title_block(self):
        city = _notice("3838").replace("<h4>합성 시청 공지</h4>",
                                       '<h4>합성 시청 공지</h4><div class="bod_view_title">다른 제목</div>')
        self.assertEqual(parse_board_notice(city, board="city", notice_id="3838")["title"], "합성 시청 공지")


if __name__ == "__main__":
    unittest.main()
