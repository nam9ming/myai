import contextlib
import io
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from processing.collection import media
from processing.collection.d03 import prepare
from processing.collection.libraries import parse_board_media
from processing.collection.official_web import board_detail_url
from processing.tests.test_board_notices import CITY_VIEW
from processing.tests.test_collection_media import ATTACH_ID, FILE_SN, PNG, TIMESTAMP, notice


def city_notice(notice_id="203043", view=CITY_VIEW):
    form = f'<form id="viewForm" action="{view}"></form>'.encode() if view else b""
    return form + notice().replace(b'value="17"', f'value="{notice_id}"'.encode())


class BoardMediaTest(unittest.TestCase):
    def setUp(self):
        self.private = Path(self.enterContext(TemporaryDirectory())).resolve() / "private"
        self.file = self.private.parent / "local-download"
        self.fetch = self.enterContext(patch.object(media, "fetch_board_detail", return_value=city_notice()))
        self.library_fetch = self.enterContext(patch.object(media, "fetch_detail"))

    def inspect(self, name="city"):
        return media.inspect_notice(self.private, "203043", name, board="city")

    def test_city_notice_lists_media_with_board_url(self):
        self.assertEqual(self.inspect(), {"notice_id": "city", "status": "parsed", "media": 2})
        self.assertEqual(self.fetch.call_args.args, ("city", "203043"))
        self.library_fetch.assert_not_called()
        receipt = json.loads((self.private / media.NOTICE_SECTION / "city" / "notice.json").read_bytes())
        self.assertEqual((receipt["board"], receipt["source_url"]), ("city", board_detail_url("city", "203043")))
        self.assertEqual(receipt["media"][0]["source_url"],
                         f"https://www.anseong.go.kr/common/imgView.do?attachId={ATTACH_ID}&fileSn={FILE_SN}&mode=origin")

    def test_city_media_file_reaches_d03_with_parent_notice_url(self):
        self.inspect()
        self.file.write_bytes(PNG)
        media.store_media(self.private, "city", 1, self.file, "city-image", TIMESTAMP)
        review = self.private / "review.json"
        review.write_text(json.dumps({
            "archive_kind": "media", "archive_name": "city-image", "data_kind": "synthetic",
            "documents": [{
                "asset": "1", "official_url": board_detail_url("city", "203043"),
                "document_id": "40000000-0000-4000-8000-000000000031",
                "document_version_id": "50000000-0000-4000-8000-000000000031",
                "version_no": 1, "publisher": "안성시", "title": "검토한 포스터", "published_date": None,
                "official_number": None, "collected_at": None, "cleaned_text": "포스터에서 읽은 문구", "redaction_log": [],
            }],
        }, ensure_ascii=False), encoding="utf-8")
        prepare(review, "city-media", self.private)
        document = json.loads((self.private / "collection-d03" / "city-media" / "source-import.json").read_bytes())
        document = document["documents"][0]
        self.assertEqual(document["official_url"], board_detail_url("city", "203043"))
        self.assertEqual(document["raw_asset_path"], f"{media.MEDIA_SECTION}/city-image/media.png")

    def test_rejects_changed_or_removed_board(self):
        self.inspect()
        path = self.private / media.NOTICE_SECTION / "city" / "notice.json"
        original = json.loads(path.read_bytes())
        swapped = {key: value for key, value in original.items() if key != "board"}
        swapped["source_url"] = "https://www.anseong.go.kr/library/bbs/view.do?bIdx=203043&mId=0401010000&ptIdx=16"
        self.file.write_bytes(PNG)
        for name, receipt in (("removed", {key: value for key, value in original.items() if key != "board"}),
                              ("library", dict(original, board="library")), ("other", dict(original, board="x")),
                              ("list", dict(original, board=["city"])), ("swapped", swapped),
                              ("edited", dict(original, media=original["media"][:1]))):
            path.unlink()
            path.write_text(json.dumps(receipt, ensure_ascii=False), encoding="utf-8")
            os.chmod(path, 0o600)
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "수집 기록|게시판"):
                media.store_media(self.private, "city", 1, self.file, f"bad-{name}", TIMESTAMP)

    def test_library_receipt_claiming_city_board_is_rejected(self):
        self.library_fetch.return_value = notice()
        media.inspect_notice(self.private, "17", "library")
        path = self.private / media.NOTICE_SECTION / "library" / "notice.json"
        receipt = json.loads(path.read_bytes())
        self.assertNotIn("board", receipt)
        path.unlink()
        path.write_text(json.dumps(dict(receipt, board="city", web_id="17",
                                        source_url=board_detail_url("city", "17"))), encoding="utf-8")
        os.chmod(path, 0o600)
        self.file.write_bytes(PNG)
        with self.assertRaisesRegex(ValueError, "시청 공지"):
            media.store_media(self.private, "library", 1, self.file, "claimed", TIMESTAMP)

    def test_failed_city_notice_keeps_board_and_cannot_supply_media(self):
        self.fetch.return_value = city_notice(view=None)
        self.assertEqual(self.inspect("failed")["status"], "parse_failed")
        receipt = json.loads((self.private / media.NOTICE_SECTION / "failed" / "notice.json").read_bytes())
        self.assertEqual((receipt["board"], receipt["media"]), ("city", []))
        self.assertIn("게시판", receipt["error"])
        self.file.write_bytes(PNG)
        with self.assertRaisesRegex(ValueError, "시청 공지 수집 기록"):
            media.store_media(self.private, "failed", 1, self.file, "invalid", TIMESTAMP)

    def test_rejects_unknown_board_before_request(self):
        with self.assertRaisesRegex(ValueError, "지원하지 않는 공식 게시판"):
            media.inspect_notice(self.private, "203043", "x", board="other")
        self.fetch.assert_not_called()
        self.library_fetch.assert_not_called()

    def test_board_media_parser_names_board_and_checks_id(self):
        self.assertEqual(len(parse_board_media(city_notice().decode(), board="city", notice_id="203043")), 2)
        with self.assertRaisesRegex(ValueError, "^시청 공지 "):
            parse_board_media(city_notice("1").decode(), board="city", notice_id="203043")
        with self.assertRaisesRegex(ValueError, "18자리"):
            parse_board_media("\x00", board="city", notice_id="1" * 19)

    def test_cli_defaults_to_library(self):
        self.library_fetch.return_value = notice()
        with (patch.object(media, "PRIVATE_ROOT", self.private),
              patch("sys.argv", ["media", "inspect", "--web-id", "17", "--name", "default"]),
              contextlib.redirect_stdout(io.StringIO())):
            self.assertEqual(media.main(), 0)
        self.fetch.assert_not_called()
        receipt = json.loads((self.private / media.NOTICE_SECTION / "default" / "notice.json").read_bytes())
        self.assertNotIn("board", receipt)

    def test_cli_accepts_board_option(self):
        args = ["media", "inspect", "--board", "city", "--web-id", "203043", "--name", "cli"]
        with (patch.object(media, "PRIVATE_ROOT", self.private), patch("sys.argv", args),
              contextlib.redirect_stdout(io.StringIO()) as output):
            self.assertEqual(media.main(), 0)
        self.assertEqual(json.loads(output.getvalue())["status"], "parsed")


if __name__ == "__main__":
    unittest.main()
