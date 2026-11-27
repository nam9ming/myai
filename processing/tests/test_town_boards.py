import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from processing.collection import media
from processing.collection.board_batch import BOARD_SECTION, capture_board_batch
from processing.collection.capture import capture
from processing.collection.d03 import _board_notice, prepare
from processing.collection.d03_sources import capture_assets
from processing.collection.libraries import (
    BOARD_PARSER_VERSIONS, board_parser_version, parse_board_media, parse_board_notice,
)
from processing.collection.library_listing import parse_board_listing
from processing.collection.official_web import (
    BOARDS, board_detail_url, board_listing_path, detail_url, fetch_board_detail, fetch_board_listing,
)
from processing.tests.test_board_notices import CITY_VIEW, _listing, _notice, _row
from processing.tests.test_collection_media import PNG, hwpx, notice as _library_notice
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
        # 읍면동도 시청과 같은 본문 허용 목록(태그·속성·스타일·스크립트 주소)과 브라우저 기준 태그 경계를 적용한다.
        for body, error in (('<p style="display:none">숨김</p>', "숨김"),
                            ('<p style="color:red" style="display:none">숨김</p>', "숨김"),
                            ('<p style="opacity:0.1">숨김</p>', "숨김"),
                            ('<progress>숨김</progress>', "미확인"),
                            ('<p inert>숨김</p>', "미확인"),
                            ('<script src="/csc/yangseong/x.js"></script><p>본문</p>', "미확인"),
                            ('<p>보임</p><!--->숨김-->', "주석"),
                            ('<p\xa0hidden>숨김</p>', "해석이 갈리는")):
            for parse in (parse_board_notice, parse_board_media):
                with self.subTest(body=body, parse=parse.__name__), \
                        self.assertRaisesRegex(ValueError, f"^양성면 공지 .*{error}"):
                    parse(_town_notice(body=body), board="town-yangseong", notice_id="203049")


def _city_notice(notice_id):
    return _notice(notice_id).replace("</div></div>", "</div>" + ATTACHMENT + "</div>", 1)


def _capture(private, board, name, listing, detail):
    with (patch("processing.collection.board_batch.sleep"),
          patch("processing.collection.board_batch.fetch_board_listing", return_value=listing),
          patch("processing.collection.board_batch.fetch_board_detail",
                side_effect=lambda _board, notice_id, limit: detail(notice_id).encode())):
        return capture_board_batch(board, name, private / BOARD_SECTION)


class TownPipelineTest(unittest.TestCase):
    def setUp(self):
        self.private = Path(self.enterContext(TemporaryDirectory())).resolve() / "private"
        self.private.mkdir(mode=0o700)
        listing = _town_listing(_town_rows(), "miyang", total=1)
        summary = _capture(self.private, "town-miyang", "miyang", listing, lambda notice_id: _town_notice(notice_id, "miyang"))
        self.assertEqual((summary["status"], summary["parsed"]), ("complete", 2))
        self.fetch = self.enterContext(patch.object(
            media, "fetch_board_detail", return_value=_town_notice(slug="miyang", attachment=ATTACHMENT).encode()))

    def test_batch_media_and_d03_round_trip(self):
        parsed = json.loads((self.private / BOARD_SECTION / "miyang" / "parsed-203049.json").read_bytes())
        self.assertEqual(parsed["parser_version"], "town-miyang-notice-parser-v1")
        assets = capture_assets(self.private, "board", "miyang", {"201926", "203049"})
        self.assertEqual(assets["203049"]["official_url"], board_detail_url("town-miyang", "203049"))
        media.inspect_notice(self.private, "203049", "notice", board="town-miyang", batch="miyang")
        notice = media._notice(self.private, "notice")
        self.assertEqual((notice["board"], notice["listing_batch"]), ("town-miyang", "miyang"))

    def test_media_inspect_needs_the_id_on_that_boards_listing(self):
        # 상세 주소는 어느 읍면동 경로로도 열리므로 같은 게시판 묶음의 목록 원본만 소속 근거로 쓴다.
        _capture(self.private, "town-gongdo", "gongdo", _town_listing(_town_rows(), "gongdo", total=1),
                 lambda notice_id: _town_notice(notice_id, "gongdo"))
        for web_id, batch, error in (("203049", None, "--batch"), ("202988", "miyang", "목록 원본에 없는 공지 번호"),
                                     ("203049", "gongdo", "묶음 수집 기록"), ("203049", "absent", "안전하게")):
            with self.subTest(web_id=web_id, batch=batch), self.assertRaisesRegex(ValueError, error):
                media.inspect_notice(self.private, web_id, "rejected", board="town-miyang", batch=batch)
        self.fetch.assert_not_called()
        self.assertFalse((self.private / media.NOTICE_SECTION / "rejected").exists())
        with self.assertRaisesRegex(ValueError, "지원하지 않는"):
            media.inspect_notice(self.private, "17", "library", batch="miyang")

        listing = self.private / BOARD_SECTION / "miyang" / "list-1.html"
        original = listing.read_bytes()
        listing.unlink()
        listing.write_bytes(original + b" ")
        os.chmod(listing, 0o600)
        with self.assertRaisesRegex(ValueError, "목록 원본 해시"):
            media.inspect_notice(self.private, "203049", "tampered", board="town-miyang", batch="miyang")

    def test_stored_notice_rechecks_its_listing_batch(self):
        media.inspect_notice(self.private, "203049", "notice", board="town-miyang", batch="miyang")
        path = self.private / media.NOTICE_SECTION / "notice" / "notice.json"
        receipt = json.loads(path.read_bytes())
        for change in ({"listing_batch": None}, {"listing_batch": "other"}):
            path.unlink()
            path.write_text(json.dumps(dict(receipt, **change), ensure_ascii=False), encoding="utf-8")
            os.chmod(path, 0o600)
            with self.subTest(change=change), self.assertRaises(ValueError):
                media._notice(self.private, "notice")
        path.unlink()
        path.write_text(json.dumps({key: value for key, value in receipt.items() if key != "listing_batch"},
                                   ensure_ascii=False), encoding="utf-8")
        os.chmod(path, 0o600)
        with self.assertRaisesRegex(ValueError, "--batch"):
            media._notice(self.private, "notice")


class TownDuplicateTest(unittest.TestCase):
    """시청·도서관·읍면동 공지는 번호 공간을 공유하므로 D03에는 같은 공지를 한 게시판의 원본으로만 준비한다."""

    def setUp(self):
        self.private = Path(self.enterContext(TemporaryDirectory())).resolve() / "private"
        self.private.mkdir(mode=0o700)
        city_rows = _row("201926", pinned=True) + _row("203001")
        for name in ("city", "city-later"):
            _capture(self.private, "city", name, _listing(city_rows, total=1).encode(), _city_notice)
        _capture(self.private, "town-gongdo", "gongdo",
                 _town_listing(_row("201926", pinned=True, menu=MENU) + _row("203001", menu=MENU), "gongdo", total=1),
                 lambda notice_id: _town_notice(notice_id, "gongdo", attachment=ATTACHMENT))
        self.d03 = self.private / "collection-d03"

    def prepare(self, name, kind, archive, asset, board, notice_id, document, version=1, url=None):
        review = self.private.parent / f"{name}.json"
        review.write_text(json.dumps({
            "archive_kind": kind, "archive_name": archive, "data_kind": "synthetic",
            "documents": [{
                "asset": asset, "official_url": url or board_detail_url(board, notice_id),
                "document_id": f"40000000-0000-4000-8000-{document:012d}",
                "document_version_id": f"50000000-0000-4000-8000-{document * 10 + version:012d}",
                "version_no": version, "publisher": "안성시", "title": "검토한 공지", "published_date": None,
                "official_number": None, "collected_at": None, "cleaned_text": "검토한 본문", "redaction_log": [],
            }],
        }, ensure_ascii=False), encoding="utf-8")
        return prepare(review, name, self.private)

    def test_notice_id_keys_share_one_space_for_city_and_towns(self):
        self.assertEqual(_board_notice(board_detail_url("city", "201926")), ("16", "201926"))
        self.assertEqual(_board_notice(board_detail_url("town-anseong3", "201926")), ("16", "201926"))
        self.assertEqual(_board_notice(board_detail_url("edu", "201926")), ("300", "201926"))
        self.assertEqual(_board_notice(detail_url("living", "201926")), ("16", "201926"))

    def test_same_notice_from_another_board_is_rejected(self):
        self.prepare("city-body", "board", "city", "201926", "city", "201926", 1)
        for document in (2, 1):
            with self.subTest(document=document), self.assertRaisesRegex(ValueError, "다른 게시판 주소"):
                self.prepare("town-body", "board", "gongdo", "201926", "town-gongdo", "201926", document)
        self.assertFalse((self.d03 / "town-body").exists())
        # 먼저 준비한 게시판이 기준이 되므로 읍면동을 먼저 준비한 공지는 시청 원본을 거부한다.
        self.prepare("town-first", "board", "gongdo", "203001", "town-gongdo", "203001", 3)
        with self.assertRaisesRegex(ValueError, "^공지 번호 203001의 문서가 D03 준비본 town-first에 다른 게시판 주소"):
            self.prepare("city-second", "board", "city", "203001", "city", "203001", 4)

    def test_same_board_allows_only_one_body_document(self):
        self.prepare("city-body", "board", "city", "201926", "city", "201926", 1)
        with self.assertRaisesRegex(ValueError, "다른 문서 ID"):
            self.prepare("city-again", "board", "city-later", "201926", "city", "201926", 2)
        # 같은 문서의 새 버전은 기존 Java 등록 규칙(기존 문서 ID·다음 버전 번호)을 따른다.
        self.assertEqual(self.prepare("city-v2", "board", "city-later", "201926", "city", "201926", 1, 2)["documents"], 1)

    def test_media_must_come_from_the_registered_board(self):
        self.prepare("city-body", "board", "city", "201926", "city", "201926", 1)
        package = self.private.parent / "notice.hwpx"
        package.write_bytes(hwpx(b"application/hwp+zip"))
        with patch.object(media, "fetch_board_detail",
                          side_effect=lambda board, notice_id, limit: (
                              _city_notice(notice_id) if board == "city"
                              else _town_notice(notice_id, "gongdo", attachment=ATTACHMENT)).encode()):
            media.inspect_notice(self.private, "201926", "city-notice", board="city")
            media.inspect_notice(self.private, "201926", "town-notice", board="town-gongdo", batch="gongdo")
        for notice in ("city-notice", "town-notice"):
            media.store_media(self.private, notice, 1, package, notice + "-file", "2026-11-27T08:00:00Z")
        self.prepare("city-media", "media", "city-notice-file", "1", "city", "201926", 5)
        with self.assertRaisesRegex(ValueError, "다른 게시판 주소"):
            self.prepare("town-media", "media", "town-notice-file", "1", "town-gongdo", "201926", 6)

    def test_library_shares_the_city_notice_space(self):
        # 2026-11-27 시청 1페이지 묶음의 202960은 도서관 상세에도 같은 제목·본문으로 있었다.
        self.prepare("city-body", "board", "city", "201926", "city", "201926", 1)
        image = self.private.parent / "notice.png"
        image.write_bytes(PNG)
        with patch.object(media, "fetch_detail", side_effect=lambda category, notice_id, limit:
                          _library_notice().replace(b'value="17"', f'value="{notice_id}"'.encode())):
            for notice_id in ("201926", "203001"):
                media.inspect_notice(self.private, notice_id, f"library-{notice_id}")
                media.store_media(self.private, f"library-{notice_id}", 1, image, f"library-{notice_id}-file",
                                  "2026-11-27T08:00:00Z")
        with self.assertRaisesRegex(ValueError, "^공지 번호 201926의 문서가 D03 준비본 city-body에 다른 게시판 주소"):
            self.prepare_library_media("201926", 5)
        self.prepare_library_media("203001", 6)
        with self.assertRaisesRegex(ValueError, "^공지 번호 203001의 문서가 D03 준비본 library-203001-media에 다른"):
            self.prepare("city-second", "board", "city", "203001", "city", "203001", 7)

    def test_library_body_allows_only_one_document_id(self):
        # 도서관 본문은 수집할 때마다 원본 해시가 달라, 별개 단건 묶음 두 개로 같은 공지가 두 문서가 될 수 있었다.
        portal = self.private.parent / "library.csv"
        portal.write_bytes("도서관명,시도명,시군구명\n합성 도서관,경기도,안성시\n".encode("cp949"))
        detail = ('<input name="bIdx" value="203001"><div class="bod_view"><h4>합성 도서관 안내</h4>'
                  '<div class="view_cont"><p>시설 점검</p></div></div>').encode()
        with patch("processing.collection.capture.fetch_detail", return_value=detail):
            for name in ("library-1", "library-2"):
                self.assertEqual(capture("living", portal, "203001", name, self.private / "collection")["status"],
                                 "parsed")
        url = detail_url("living", "203001")
        self.prepare("library-body", "single", "library-1", "203001", None, "203001", 2, url=url)
        with self.assertRaisesRegex(ValueError, "^공지 번호 203001의 본문이 D03 준비본 library-body에 다른 문서 ID"):
            self.prepare("library-again", "single", "library-2", "203001", None, "203001", 3, url=url)
        self.assertFalse((self.d03 / "library-again").exists())
        self.assertEqual(self.prepare("library-v2", "single", "library-2", "203001", None, "203001", 2, 2, url=url),
                         {"preparation_id": "library-v2", "documents": 1})

    def prepare_library_media(self, notice_id, document):
        return self.prepare(f"library-{notice_id}-media", "media", f"library-{notice_id}-file", "1", None, notice_id,
                            document, url=detail_url("living", notice_id))

    def test_unreadable_earlier_preparation_fails_closed(self):
        self.prepare("city-body", "board", "city", "201926", "city", "201926", 1)
        unfinished = self.d03 / "unfinished"
        unfinished.mkdir(mode=0o700)  # 완료 파일이 없는 준비본은 등록할 수 없으므로 건너뛴다.
        self.prepare("town-other", "board", "gongdo", "203001", "town-gongdo", "203001", 2)
        broken = self.d03 / "broken"
        broken.mkdir(mode=0o700)
        (broken / "source-import.json").write_text('{"documents": "x"}', encoding="utf-8")
        os.chmod(broken / "source-import.json", 0o600)
        with self.assertRaisesRegex(ValueError, "기존 D03 준비본"):
            self.prepare("city-later-body", "board", "city-later", "203001", "city", "203001", 3)


if __name__ == "__main__":
    unittest.main()
