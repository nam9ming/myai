import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from processing.collection import media
from processing.collection.board_batch import BOARD_SECTION, capture_board_batch
from processing.collection.d03_sources import capture_assets
from processing.collection.libraries import (
    BOARD_PARSER_VERSIONS, board_parser_version, parse_board_media, parse_board_notice,
)
from processing.collection.library_listing import parse_board_listing
from processing.collection.official_web import (
    BOARDS, board_detail_url, board_listing_path, fetch_board_detail, fetch_board_listing,
)
from processing.tests.test_board_notices import CITY_VIEW, _listing, _notice, _row
from processing.tests.test_edu_board import ATTACH, ATTACHMENT, FILE_SN

# 2026-11-27 공식 읍면동 메뉴에서 확인한 경로 이름과 읍면동 이름
TOWNS = {
    "gongdo": "공도읍", "bogae": "보개면", "geumgwang": "금광면", "seoun": "서운면", "miyang": "미양면",
    "daedeok": "대덕면", "yangseong": "양성면", "wongok": "원곡면", "iljuk": "일죽면", "juksan": "죽산면",
    "samjuk": "삼죽면", "gosam": "고삼면", "anseong1": "안성1동", "anseong2": "안성2동", "anseong3": "안성3동",
}
MENU = "0500000000"


def _view(slug="yangseong"):
    return f"/csc/{slug}/bbs/view.do?ptIdx=16&amp;mId={MENU}"


def _town_listing(rows, slug="yangseong", *, action=None, **pages):
    action = f"/csc/{slug}/bbs/list.do?ptIdx=16&amp;mId={MENU}" if action is None else action
    form = f'<form id="list" name="list" action="{action}" method="post">' if action else '<form id="list">'
    return _listing(rows, **pages).replace('<form id="list">', form, 1).encode()


def _town_rows():
    return _row("201926", pinned=True, menu=MENU) + _row("203049", number="394", menu=MENU)


def _town_notice(notice_id="203049", slug="yangseong", body="<p>합성 본문</p>", attachment="", context=""):
    script = f'<script>var yh = {{"mId": "{MENU}", "contextPath": "{context}"}};</script>'
    page = _notice(notice_id, body, view=_view(slug)).replace("합성 시청 공지", "합성 읍면동 공지")
    return script + page.replace("</div></div>", "</div>" + attachment + "</div>", 1)


class TownRegistryTest(unittest.TestCase):
    def test_all_fifteen_towns_are_registered_with_fixed_paths(self):
        towns = {key: info for key, info in BOARDS.items() if key.startswith("town-")}
        self.assertEqual(list(towns), [f"town-{slug}" for slug in TOWNS])
        for slug, name in TOWNS.items():
            key = f"town-{slug}"
            info = BOARDS[key]
            with self.subTest(key=key):
                self.assertEqual((info.label, info.source, info.menu, info.pt_idx, info.title_class, info.context_path),
                                 (f"{name} 공지", f"town_{slug}_notice", MENU, "16", None, ""))
                self.assertEqual(board_listing_path(key), f"/csc/{slug}/bbs/list.do?ptIdx=16&mId={MENU}")
                self.assertEqual(board_parser_version(key), f"{key}-notice-parser-v1")
        self.assertEqual(board_detail_url("town-yangseong", "201926"),
                         "https://www.anseong.go.kr/csc/yangseong/bbs/view.do?bIdx=201926&mId=0500000000&ptIdx=16")

    def test_every_board_has_a_parser_version(self):
        self.assertEqual(set(BOARD_PARSER_VERSIONS), set(BOARDS))
        self.assertEqual(len(set(BOARD_PARSER_VERSIONS.values())), len(BOARDS), "게시판마다 버전을 따로 올린다.")

    @patch("processing.collection.official_web.HTTPSConnection")
    def test_requests_use_the_town_path(self, connect):
        response = connect.return_value.getresponse.return_value.__enter__.return_value
        response.status, response.getheader.return_value, response.read.return_value = 200, None, b"ok"
        fetch_board_listing("town-anseong3", 2, limit=64)
        fetch_board_detail("town-anseong3", "203049", limit=64)
        listing, detail = connect.return_value.request.call_args_list
        self.assertEqual((listing.args, listing.kwargs["body"]),
                         (("POST", f"/csc/anseong3/bbs/list.do?ptIdx=16&mId={MENU}"), b"page=2"))
        self.assertEqual(detail.args, ("GET", f"/csc/anseong3/bbs/view.do?bIdx=203049&mId={MENU}&ptIdx=16"))


class TownListingTest(unittest.TestCase):
    def test_listing_separates_pins_and_requires_its_own_list_form(self):
        self.assertEqual(parse_board_listing(_town_listing(_town_rows()), board="town-yangseong", page=1),
                         (3, ["203049"], ["201926"]))
        # 읍면동 목록 링크 인자는 모두 같으므로 form#list의 경로가 유일한 게시판 표식이다.
        for raw in (_town_listing(_town_rows(), "gongdo"), _town_listing(_town_rows(), action=""),
                    _town_listing(_town_rows(), action=CITY_VIEW.replace("view", "list")),
                    _town_listing(_town_rows()).replace(b'action="', b'action="/x" action="', 1)):
            with self.subTest(raw=raw[:90]), self.assertRaisesRegex(ValueError, "^양성면 공지 목록의 게시판이 요청과"):
                parse_board_listing(raw, board="town-yangseong", page=1)

    def test_city_and_town_links_are_not_interchangeable(self):
        with self.assertRaisesRegex(ValueError, "^양성면 공지 목록 HTML 구조"):
            parse_board_listing(_town_listing(_row("5")), board="town-yangseong", page=1)
        with self.assertRaises(ValueError):
            parse_board_listing(_town_listing(_town_rows()), board="city", page=1)
        # 시청 목록은 기존처럼 form#list의 action을 대조하지 않는다.
        self.assertEqual(parse_board_listing(_listing(_row("5")).encode(), board="city", page=1), (3, ["5"], []))


class TownNoticeTest(unittest.TestCase):
    def test_notice_reads_h4_title_and_checks_its_view_form(self):
        record = parse_board_notice(_town_notice(), board="town-yangseong", notice_id="203049")
        self.assertEqual(record, {
            "source": "town_yangseong_notice",
            "external_id": "203049",
            "title": "합성 읍면동 공지",
            "official_url": board_detail_url("town-yangseong", "203049"),
            "fields": {"description": "합성 본문", "published_date": "2026-11-27"},
        })
        for page, board in ((_town_notice(slug="gongdo"), "town-yangseong"), (_notice("203049"), "town-yangseong"),
                            (_town_notice(), "city"), (_notice("203049", view=None), "town-gongdo")):
            with self.subTest(board=board, page=page[-40:]), self.assertRaisesRegex(ValueError, "게시판이 요청과"):
                parse_board_notice(page, board=board, notice_id="203049")

    def test_same_notice_on_city_and_town_parses_to_the_same_content(self):
        town = parse_board_notice(_town_notice("203001", "gongdo"), board="town-gongdo", notice_id="203001")
        city = parse_board_notice(_notice("203001").replace("합성 시청 공지", "합성 읍면동 공지"),
                                  board="city", notice_id="203001")
        self.assertEqual({**town, "source": None, "official_url": None}, {**city, "source": None, "official_url": None})
        self.assertNotEqual(town["official_url"], city["official_url"])

    def test_attachment_uses_root_context_path(self):
        page = _town_notice(attachment=ATTACHMENT)
        self.assertEqual(parse_board_media(page, board="town-yangseong", notice_id="203049")[0]["source_url"],
                         f"https://www.anseong.go.kr/cmm/fms/FileDown.do?atchFileId={ATTACH}&fileSn={FILE_SN}")
        with self.assertRaisesRegex(ValueError, "경로"):
            parse_board_media(_town_notice(attachment=ATTACHMENT, context="/csc"), board="town-yangseong",
                              notice_id="203049")
        hidden = _town_notice(body='<p style="display:none">숨김</p>')
        with self.assertRaisesRegex(ValueError, "^양성면 공지 .*숨김"):
            parse_board_notice(hidden, board="town-yangseong", notice_id="203049")


class TownPipelineTest(unittest.TestCase):
    def setUp(self):
        self.private = Path(self.enterContext(TemporaryDirectory())).resolve() / "private"
        self.private.mkdir(mode=0o700)

    def test_batch_media_and_d03_round_trip(self):
        with (patch("processing.collection.board_batch.sleep"),
              patch("processing.collection.board_batch.fetch_board_listing",
                    return_value=_town_listing(_town_rows(), "miyang", total=1)),
              patch("processing.collection.board_batch.fetch_board_detail",
                    side_effect=lambda _name, notice_id, limit: _town_notice(notice_id, "miyang").encode())):
            summary = capture_board_batch("town-miyang", "miyang", self.private / BOARD_SECTION)
        self.assertEqual((summary["status"], summary["parsed"]), ("complete", 2))
        parsed = json.loads((self.private / BOARD_SECTION / "miyang" / "parsed-203049.json").read_bytes())
        self.assertEqual(parsed["parser_version"], "town-miyang-notice-parser-v1")
        assets = capture_assets(self.private, "board", "miyang", {"201926", "203049"})
        self.assertEqual(assets["203049"]["official_url"], board_detail_url("town-miyang", "203049"))
        with patch.object(media, "fetch_board_detail",
                          return_value=_town_notice(slug="miyang", attachment=ATTACHMENT).encode()):
            media.inspect_notice(self.private, "203049", "notice", board="town-miyang")
        self.assertEqual(media._notice(self.private, "notice")["board"], "town-miyang")


if __name__ == "__main__":
    unittest.main()
