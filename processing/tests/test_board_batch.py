import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from processing.collection.board_batch import BOARD_SECTION, capture_board_batch, main
from processing.collection.d03 import prepare
from processing.collection.d03_sources import capture_assets
from processing.collection.official_web import SourceHTTPError, board_detail_url
from processing.tests.test_board_notices import _listing, _notice, _row


def board_page(page, total, numbered, pinned=()):
    rows = "".join(_row(item, pinned=True) for item in pinned)
    rows += "".join(_row(item, number=str(100 - index)) for index, item in enumerate(numbered))
    return _listing(rows, current=page, total=total).encode()


def board_detail(notice_id, body="<p>합성 본문</p>"):
    return _notice(notice_id, body).encode()


class BoardBatchTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(TemporaryDirectory())).resolve() / "private"
        self.root.mkdir(mode=0o700)
        self.enterContext(patch("processing.collection.board_batch.sleep"))
        self.listing = self.enterContext(patch("processing.collection.board_batch.fetch_board_listing"))
        self.detail = self.enterContext(patch("processing.collection.board_batch.fetch_board_detail"))
        self.detail.side_effect = lambda _board, notice_id, **_options: board_detail(notice_id)

    def capture(self, name="run", **limits):
        summary = capture_board_batch("city", name, self.root / BOARD_SECTION, **limits)
        directory = self.root / BOARD_SECTION / name
        return summary, json.loads((directory / "batch.json").read_text(encoding="utf-8")), directory

    def test_pinned_notices_are_captured_once_before_numbered_rows(self):
        first = board_page(1, 2, ["9", "8"], pinned=["3"])
        self.listing.side_effect = [first, board_page(2, 2, ["7"], pinned=["3"])]
        summary, receipt, directory = self.capture()
        self.assertEqual(summary, {"batch_id": "run", "status": "complete", "discovery_status": "complete",
                                   "selected": 4, "parsed": 4})
        self.assertEqual(receipt["schema_version"], "citizen-board-batch-v1")
        self.assertEqual(receipt["board"], "city")
        self.assertEqual([item["web_id"] for item in receipt["items"]], ["3", "9", "8", "7"])
        self.assertEqual([call.args for call in self.listing.call_args_list], [("city", 1), ("city", 2)])
        self.assertEqual((receipt["pages"][0]["web_ids"], receipt["pages"][0]["pinned_ids"]), (["9", "8"], ["3"]))
        self.assertEqual(receipt["pages"][0]["method"], "POST")
        self.assertEqual((directory / "list-1.html").read_bytes(), first)
        item = receipt["items"][0]
        self.assertEqual(item["source_url"], board_detail_url("city", "3"))
        self.assertEqual(item["sha256"], hashlib.sha256(board_detail("3")).hexdigest())
        parsed = json.loads((directory / item["parsed_file"]).read_text(encoding="utf-8"))
        self.assertEqual((parsed["schema_version"], parsed["parser_version"]),
                         ("citizen-board-notice-v1", "board-notice-parser-v2"))
        self.assertEqual(parsed["record"]["source"], "city_notice")

    def test_pinned_notice_listed_again_as_numbered_row_is_captured_once(self):
        self.listing.return_value = board_page(1, 1, ["3", "9"], pinned=["3"])
        summary, receipt, _ = self.capture()
        self.assertEqual([item["web_id"] for item in receipt["items"]], ["3", "9"])
        self.assertEqual(summary["selected"], 2)

    def test_changed_pinned_rows_or_repeated_numbers_stop_discovery(self):
        for name, second, message in (
            ("pins", board_page(2, 2, ["7"], pinned=["4"]), "고정 글"),
            ("repeat", board_page(2, 2, ["9"], pinned=["3"]), "같은 게시물 번호"),
        ):
            with self.subTest(name=name):
                self.listing.side_effect = [board_page(1, 2, ["9"], pinned=["3"]), second]
                summary, receipt, _ = self.capture(name)
                self.assertEqual((summary["status"], summary["discovery_status"]), ("partial", "failed"))
                self.assertEqual(receipt["pages"][1]["status"], "parse_failed")
                self.assertIn(message, receipt["pages"][1]["error"])
                self.assertEqual([item["web_id"] for item in receipt["items"]], ["3", "9"])

    def test_image_only_notice_keeps_raw_as_parse_failure(self):
        self.listing.return_value = board_page(1, 1, ["9", "8"])
        image_only = board_detail("9", '<p><img src="/x.png" alt=""></p>')
        self.detail.side_effect = [image_only, board_detail("8")]
        summary, receipt, directory = self.capture()
        self.assertEqual((summary["status"], summary["parsed"]), ("partial", 1))
        self.assertEqual(receipt["items"][0]["status"], "parse_failed")
        self.assertIn("이미지", receipt["items"][0]["error"])
        self.assertEqual((directory / "detail-9.html").read_bytes(), image_only)

    def test_rate_limit_and_later_start_page(self):
        self.listing.return_value = board_page(1, 1, ["9", "8"])
        self.detail.side_effect = SourceHTTPError(429)
        summary, receipt, _ = self.capture()
        self.assertEqual(receipt["stop_http_status"], 429)
        self.assertEqual([item["status"] for item in receipt["items"]], ["fetch_failed", "not_attempted"])

        self.detail.side_effect = lambda _board, notice_id, **_options: board_detail(notice_id)
        self.listing.return_value = board_page(143, 143, ["2"], pinned=["3"])
        summary, receipt, _ = self.capture("tail", start_page=143, max_pages=1)
        self.assertEqual((summary["status"], summary["discovery_status"]), ("partial", "end_reached"))
        self.assertEqual(receipt["start_page"], 143)
        self.assertEqual([item["web_id"] for item in receipt["items"]], ["3", "2"])

    def test_pinned_rows_count_toward_item_limit_and_must_appear_on_first_page(self):
        self.listing.return_value = board_page(1, 2, ["9"], pinned=["3", "4"])
        summary, receipt, _ = self.capture("limited", max_items=1)
        self.assertEqual((summary["discovery_status"], [item["web_id"] for item in receipt["items"]]),
                         ("item_limit", ["3"]))

        self.listing.side_effect = [board_page(1, 2, ["9"]), board_page(2, 2, ["8"], pinned=["3"])]
        summary, receipt, _ = self.capture("late-pin")
        self.assertEqual(summary["discovery_status"], "failed")
        self.assertIn("고정 글", receipt["pages"][1]["error"])

    def test_invalid_arguments_are_rejected_before_requests(self):
        for board, name, limits in (("library", "run", {}), ("city", "../run", {}), ("city", "run", {"max_items": 81}),
                                    ("city", "run", {"start_page": 0})):
            with self.subTest(board=board, limits=limits), self.assertRaises(ValueError):
                capture_board_batch(board, name, self.root / BOARD_SECTION, **limits)
        self.listing.assert_not_called()

    def test_cli_exit_codes(self):
        self.listing.return_value = board_page(1, 1, ["9"])
        self.listing.side_effect = None
        for args, code in ((["board_batch", "city", "--name", "done"], 0),
                           (["board_batch", "library", "--name", "other"], 1),
                           (["board_batch", "city", "--name", "bad name"], 1)):
            with (self.subTest(args=args), patch("processing.collection.board_batch.BOARD_ROOT", self.root / BOARD_SECTION),
                  patch("sys.argv", args), contextlib.redirect_stdout(io.StringIO()),
                  contextlib.redirect_stderr(io.StringIO())):
                try:
                    result = main()
                except SystemExit as error:
                    result = error.code
                self.assertEqual(result, code)
        self.listing.return_value = board_page(1, 2, ["9"])
        with (patch("processing.collection.board_batch.BOARD_ROOT", self.root / BOARD_SECTION),
              patch("sys.argv", ["board_batch", "city", "--name", "pages", "--max-pages", "1"]),
              contextlib.redirect_stdout(io.StringIO()) as output):
            self.assertEqual(main(), 2)
        self.assertEqual(json.loads(output.getvalue())["discovery_status"], "page_limit")


class BoardD03Test(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(TemporaryDirectory())).resolve() / "private"
        self.root.mkdir(mode=0o700)
        self.directory = self.root / BOARD_SECTION / "trial"
        with (patch("processing.collection.board_batch.sleep"),
              patch("processing.collection.board_batch.fetch_board_listing",
                    return_value=board_page(1, 1, ["9", "8"])),
              patch("processing.collection.board_batch.fetch_board_detail",
                    side_effect=[board_detail("9"), board_detail("1")])):
            capture_board_batch("city", "trial", self.root / BOARD_SECTION)
        self.receipt = json.loads((self.directory / "batch.json").read_bytes())

    def rewrite(self, name, content):
        path = self.directory / name
        path.unlink()
        path.write_bytes(content)
        os.chmod(path, 0o600)

    def test_parsed_notice_returns_raw_reference(self):
        self.assertEqual(capture_assets(self.root, "board", "trial", {"9"}), {"9": {
            "raw_asset_path": f"{BOARD_SECTION}/trial/detail-9.html",
            "raw_sha256": hashlib.sha256(board_detail("9")).hexdigest(),
            "official_url": board_detail_url("city", "9"),
            "collected_at": self.receipt["items"][0]["fetched_at"],
            "collection_method": "official-web-board",
        }})

    def test_rejects_unparsed_portal_or_tampered_sources(self):
        for keys in ({"8"}, {"portal"}):
            with self.subTest(keys=keys), self.assertRaises(ValueError):
                capture_assets(self.root, "board", "trial", keys)
        original = (self.directory / "detail-9.html").read_bytes()
        self.rewrite("detail-9.html", original + b" ")
        with self.assertRaises(ValueError):
            capture_assets(self.root, "board", "trial", {"9"})
        self.rewrite("detail-9.html", original)
        self.assertIn("9", capture_assets(self.root, "board", "trial", {"9"}))

        parsed = json.loads((self.directory / "parsed-9.json").read_bytes())
        for older in ("board-notice-parser-v0", "board-notice-parser-v1"):
            self.rewrite("parsed-9.json", json.dumps(dict(parsed, parser_version=older)).encode())
            with self.subTest(older=older), self.assertRaisesRegex(ValueError, "파서 버전.*다시 수집"):
                capture_assets(self.root, "board", "trial", {"9"})
        changed = json.loads(json.dumps(parsed))
        changed["record"]["fields"]["description"] = "다른 본문"
        self.rewrite("parsed-9.json", json.dumps(changed, ensure_ascii=False).encode())
        with self.assertRaisesRegex(ValueError, "파싱 결과가 원본과 다릅니다"):
            capture_assets(self.root, "board", "trial", {"9"})
        self.rewrite("parsed-9.json", json.dumps(parsed, ensure_ascii=False).encode())
        self.assertIn("9", capture_assets(self.root, "board", "trial", {"9"}))

        for change in ({"board": "library"}, {"schema_version": "other"}):
            self.rewrite("batch.json", json.dumps(dict(self.receipt, **change), ensure_ascii=False).encode())
            with self.subTest(change=change), self.assertRaises(ValueError):
                capture_assets(self.root, "board", "trial", {"9"})

    def test_prepare_outputs_pending_document(self):
        review = self.root / "review.json"
        review.write_text(json.dumps({
            "archive_kind": "board", "archive_name": "trial", "data_kind": "synthetic",
            "documents": [{
                "asset": "9", "official_url": board_detail_url("city", "9"),
                "document_id": "40000000-0000-4000-8000-000000000009",
                "document_version_id": "50000000-0000-4000-8000-000000000009",
                "version_no": 1, "publisher": "안성시", "title": "검토한 공지", "published_date": "2026-11-27",
                "official_number": None, "collected_at": None, "cleaned_text": "검토한 본문", "redaction_log": [],
            }],
        }, ensure_ascii=False), encoding="utf-8")
        prepare(review, "board-result", self.root)
        document = json.loads((self.root / "collection-d03" / "board-result" / "source-import.json").read_bytes())
        document = document["documents"][0]
        self.assertEqual(document["raw_asset_path"], f"{BOARD_SECTION}/trial/detail-9.html")
        self.assertEqual((document["collection_method"], document["use_review"]), ("official-web-board", "pending"))


if __name__ == "__main__":
    unittest.main()
