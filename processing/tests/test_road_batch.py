import contextlib
import hashlib
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from processing.collection.official_web import SourceHTTPError, road_detail_url
from processing.collection.road_batch import capture_road_batch, main
from processing.tests.test_road_works import _EMPTY_ROW, _detail, _listing, _row


def road_page(page, total, *ids, state="ongoing"):
    rows = "".join(_row(item) for item in ids) or _EMPTY_ROW
    return _listing(rows, state=state, current=page, total=total).encode()


def road_detail(project_id, state="ongoing"):
    return _detail(project_id, state=state).encode()


class RoadBatchTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(TemporaryDirectory())).resolve() / "roads"
        self.enterContext(patch("processing.collection.road_batch.sleep"))
        self.listing = self.enterContext(patch("processing.collection.road_batch.fetch_road_listing"))
        self.detail = self.enterContext(patch("processing.collection.road_batch.fetch_road_detail"))

    def capture(self, state="ongoing", **limits):
        summary = capture_road_batch(state, "run", self.root, **limits)
        directory = self.root / "run"
        receipt = json.loads((directory / "batch.json").read_text(encoding="utf-8"))
        return summary, receipt, directory

    def test_complete_listing_preserves_pages_details_and_parsed_records(self):
        first = road_page(1, 2, "9", "7")
        self.listing.side_effect = [first, road_page(2, 2, "8")]
        self.detail.side_effect = lambda state, project_id, **_options: road_detail(project_id, state)
        summary, receipt, directory = self.capture()
        self.assertEqual(summary, {"batch_id": "run", "status": "complete", "discovery_status": "complete",
                                   "selected": 3, "parsed": 3})
        self.assertEqual(receipt["schema_version"], "citizen-road-works-batch-v1")
        self.assertEqual(receipt["state"], "ongoing")
        self.assertEqual([call.args for call in self.listing.call_args_list], [("ongoing", 1), ("ongoing", 2)])
        self.assertEqual([item["web_id"] for item in receipt["items"]], ["9", "7", "8"])
        self.assertEqual((directory / "list-1.html").read_bytes(), first)
        self.assertEqual(receipt["pages"][0]["sha256"], hashlib.sha256(first).hexdigest())
        self.assertEqual(receipt["pages"][0]["source_url"],
                         "https://www.anseong.go.kr/depart/roadConstruction/list.do"
                         "?searchGubun=1&state=1&mId=0901020100&page=1")
        item = receipt["items"][0]
        self.assertEqual(item["source_url"], road_detail_url("ongoing", "9"))
        self.assertEqual((directory / "detail-9.html").read_bytes(), road_detail("9"))
        self.assertEqual(item["sha256"], hashlib.sha256(road_detail("9")).hexdigest())
        parsed = json.loads((directory / item["parsed_file"]).read_text(encoding="utf-8"))
        self.assertEqual(parsed["sha256"], item["sha256"])
        self.assertEqual(parsed["parser_version"], "road-works-parser-v1")
        self.assertEqual(parsed["record"]["external_id"], "9")
        self.assertEqual(parsed["record"]["listing_state"], "ongoing")

    def test_detail_failures_keep_raw_and_continue(self):
        self.listing.return_value = road_page(1, 1, "1", "2", "3")
        self.detail.side_effect = [road_detail("99"), ValueError("합성 수신 실패"), road_detail("3")]
        summary, receipt, directory = self.capture()
        self.assertEqual((summary["status"], summary["parsed"]), ("partial", 1))
        self.assertEqual([item["status"] for item in receipt["items"]], ["parse_failed", "fetch_failed", "parsed"])
        self.assertEqual((directory / "detail-1.html").read_bytes(), road_detail("99"))
        self.assertFalse((directory / "detail-2.html").exists())
        self.assertNotIn("parsed_file", receipt["items"][0])

    def test_rate_limit_stops_remaining_requests(self):
        self.listing.return_value = road_page(1, 1, "1", "2")
        self.detail.side_effect = SourceHTTPError(429)
        summary, receipt, _ = self.capture()
        self.assertEqual(summary["status"], "partial")
        self.assertEqual(receipt["stop_http_status"], 429)
        self.assertEqual([item["status"] for item in receipt["items"]], ["fetch_failed", "not_attempted"])
        self.assertEqual(self.detail.call_count, 1)

    def test_listing_stop_status_skips_details(self):
        self.listing.side_effect = [road_page(1, 2, "1"), SourceHTTPError(503)]
        summary, receipt, directory = self.capture()
        self.assertEqual((summary["status"], summary["discovery_status"]), ("partial", "failed"))
        self.assertEqual(receipt["stop_http_status"], 503)
        self.assertEqual(receipt["pages"][1]["status"], "fetch_failed")
        self.assertEqual(receipt["items"][0]["status"], "not_attempted")
        self.assertFalse((directory / "list-2.html").exists())
        self.detail.assert_not_called()

    def test_changed_page_count_or_repeated_id_stops_discovery(self):
        for second, message in ((road_page(2, 3, "2"), "달라졌습니다"), (road_page(2, 2, "1"), "같은 공사 번호")):
            with self.subTest(message=message):
                self.listing.side_effect = [road_page(1, 2, "1"), second]
                self.detail.return_value = road_detail("1")
                summary = capture_road_batch("ongoing", "run-" + str(len(message)), self.root)
                receipt = json.loads((self.root / summary["batch_id"] / "batch.json").read_text())
                self.assertEqual(summary["discovery_status"], "failed")
                self.assertEqual(receipt["pages"][1]["status"], "parse_failed")
                self.assertIn(message, receipt["pages"][1]["error"])
                self.assertEqual([item["web_id"] for item in receipt["items"]], ["1"])

    def test_page_and_item_caps_report_partial(self):
        self.listing.return_value = road_page(1, 3, "1")
        self.detail.return_value = road_detail("1")
        summary, _, _ = self.capture(max_pages=1)
        self.assertEqual((summary["status"], summary["discovery_status"]), ("partial", "page_limit"))

        self.listing.return_value = road_page(1, 1, "1", "2")
        summary = capture_road_batch("ongoing", "capped", self.root, max_items=1)
        self.assertEqual((summary["status"], summary["discovery_status"], summary["selected"]),
                         ("partial", "item_limit", 1))

    def test_later_start_page_reaches_end_but_stays_partial(self):
        self.listing.side_effect = [road_page(13, 14, "5", state="completed"), road_page(14, 14, "4", state="completed")]
        self.detail.side_effect = lambda state, project_id, **_options: road_detail(project_id, state)
        summary, receipt, _ = self.capture("completed", start_page=13, max_pages=2)
        self.assertEqual([call.args for call in self.listing.call_args_list], [("completed", 13), ("completed", 14)])
        self.assertEqual((summary["status"], summary["discovery_status"], summary["parsed"]),
                         ("partial", "end_reached", 2))
        self.assertEqual(receipt["start_page"], 13)

    def test_later_start_page_records_item_limit_or_missing_page(self):
        self.listing.return_value = road_page(5, 14, "5", "4", state="completed")
        self.detail.side_effect = lambda state, project_id, **_options: road_detail(project_id, state)
        summary = capture_road_batch("completed", "limited", self.root, start_page=5, max_items=1)
        self.assertEqual((summary["status"], summary["discovery_status"], summary["selected"]),
                         ("partial", "item_limit", 1))

        self.listing.return_value = road_page(14, 14, "1", state="completed")
        summary = capture_road_batch("completed", "beyond", self.root, start_page=15)
        receipt = json.loads((self.root / "beyond" / "batch.json").read_text())
        self.assertEqual((summary["status"], summary["discovery_status"], summary["selected"]),
                         ("partial", "failed", 0))
        self.assertEqual(receipt["pages"][0]["status"], "parse_failed")

    def test_empty_planned_listing_is_complete(self):
        self.listing.return_value = road_page(1, 1, state="planned")
        summary, receipt, _ = self.capture("planned")
        self.assertEqual((summary["status"], summary["selected"]), ("complete", 0))
        self.assertEqual(receipt["items"], [])
        self.detail.assert_not_called()

    def test_invalid_arguments_are_rejected_before_requests(self):
        for state, name, limits in (
            ("closed", "run", {}), ("ongoing", "../run", {}), ("ongoing", "run", {"max_pages": 21}),
            ("ongoing", "run", {"max_items": 0}), ("ongoing", "run", {"max_pages": True}),
            ("ongoing", "run", {"start_page": 0}), ("ongoing", "run", {"start_page": 10001}),
        ):
            with self.subTest(state=state, name=name, limits=limits), self.assertRaises(ValueError):
                capture_road_batch(state, name, self.root, **limits)
        self.listing.assert_not_called()

    def test_existing_name_is_not_overwritten(self):
        self.listing.return_value = road_page(1, 1, state="planned")
        self.capture("planned")
        with self.assertRaises(ValueError):
            capture_road_batch("planned", "run", self.root)

    def test_cli_exit_codes_follow_batch_status(self):
        self.listing.return_value = road_page(1, 1, "1")
        self.detail.return_value = road_detail("1")
        cases = (
            (["road_batch", "ongoing", "--name", "done"], 0),
            (["road_batch", "ongoing", "--name", "capped", "--max-pages", "1", "--max-items", "1"], 0),
            (["road_batch", "ongoing", "--name", "bad name"], 1),
            (["road_batch", "closed", "--name", "argument"], 1),
            (["road_batch", "ongoing", "--name", "pages", "--max-pages", "x"], 1),
        )
        for args, code in cases:
            with (self.subTest(args=args), patch("processing.collection.road_batch.ROAD_ROOT", self.root),
                  patch("sys.argv", args), contextlib.redirect_stdout(io.StringIO()),
                  contextlib.redirect_stderr(io.StringIO())):
                try:
                    result = main()
                except SystemExit as error:
                    result = error.code
                self.assertEqual(result, code)
        self.detail.side_effect = ValueError("합성 실패")
        with (patch("processing.collection.road_batch.ROAD_ROOT", self.root),
              patch("sys.argv", ["road_batch", "ongoing", "--name", "failed"]),
              contextlib.redirect_stdout(io.StringIO()) as output):
            self.assertEqual(main(), 2)
        self.assertEqual(json.loads(output.getvalue())["status"], "partial")


if __name__ == "__main__":
    unittest.main()
