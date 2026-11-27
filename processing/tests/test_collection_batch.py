import contextlib
from datetime import date
import hashlib
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from processing.collection.batch import capture_batch, main
from processing.collection.official_web import SourceHTTPError


def event_page(page, total, *ids):
    return json.dumps({"curPage": page, "totalCnt": total, "list": [{"idx": item} for item in ids]}).encode()


def event_detail(web_id):
    return json.dumps({"idx": web_id, "title": "합성 축제"}).encode()


def library_page(page, total, *ids):
    rows = "".join(
        f"""<tr><td><a onclick="goTo.view('list','{item}','16','0401010000'); return false;">공지</a></td></tr>"""
        for item in ids
    )
    return (f'<form id="list"><p class="page_num">현재 페이지 <span>{page}</span> / 전체 페이지 {total}</p>'
            f'<table class="bod_list"><tbody>{rows}</tbody></table></form>').encode()


class CollectionBatchTest(unittest.TestCase):
    def setUp(self):
        folder = Path(self.enterContext(TemporaryDirectory())).resolve()
        self.root = folder / "batches"
        self.portal = folder / "portal.csv"
        self.data = "축제명,소재지도로명주소\n합성 축제,경기도 안성시 합성로 1\n".encode("cp949")
        self.portal.write_bytes(self.data)
        self.begin = self.end = date(2026, 11, 1)
        self.enterContext(patch("processing.collection.batch.sleep"))
        self.listing = self.enterContext(patch("processing.collection.batch.fetch_listing"))
        self.detail = self.enterContext(patch("processing.collection.batch.fetch_detail"))

    def capture(self, **limits):
        summary = capture_batch("culture", self.portal, "run", self.root,
                                begin=self.begin, end=self.end, **limits)
        directory = self.root / "run"
        receipt = json.loads((directory / "batch.json").read_text(encoding="utf-8"))
        return summary, receipt, directory

    def test_complete_list_reuses_portal_and_preserves_page_and_details(self):
        page_one = event_page(1, 3, 9, 7)
        self.listing.side_effect = [page_one, event_page(2, 3, 8)]
        self.detail.side_effect = lambda _category, web_id, **_options: event_detail(web_id)
        summary, receipt, directory = self.capture()
        self.assertEqual(summary, {"batch_id": "run", "status": "complete", "discovery_status": "complete",
                                   "selected": 3, "parsed": 3})
        self.assertEqual([entry["web_id"] for entry in receipt["items"]], ["9", "7", "8"])
        self.assertEqual([call.args[1] for call in self.listing.call_args_list], [1, 2])
        self.assertEqual(len(receipt["portal"]["records"]), 1)
        self.assertEqual((directory / "portal.csv").read_bytes(), self.data)
        self.assertEqual((directory / "list-1.json").read_bytes(), page_one)
        self.assertEqual(receipt["pages"][0]["sha256"], hashlib.sha256(page_one).hexdigest())
        self.assertEqual((directory / "detail-9.json").read_bytes(), event_detail("9"))
        self.assertEqual(json.loads((directory / "parsed-9.json").read_text())["relationship"]["state"], "unresolved")

    def test_invalid_listing_page_is_saved_without_fetching_its_ids(self):
        bad = event_page(2, 3, 9, 8)
        self.listing.side_effect = [event_page(1, 3, 9), bad]
        self.detail.return_value = event_detail(9)
        summary, receipt, directory = self.capture()
        self.assertEqual(summary["discovery_status"], "failed")
        self.assertEqual(summary["parsed"], 1)
        self.assertEqual(receipt["pages"][-1]["status"], "parse_failed")
        self.assertEqual((directory / "list-2.json").read_bytes(), bad)
        self.assertEqual([call.args[1] for call in self.detail.call_args_list], ["9"])

    def test_detail_failure_preserves_bad_raw_and_keeps_collecting(self):
        self.listing.return_value = event_page(1, 3, 1, 2, 3)
        self.detail.side_effect = [b"malformed", ValueError("합성 수신 실패"), event_detail(3)]
        summary, receipt, directory = self.capture()
        self.assertEqual((summary["status"], summary["parsed"]), ("partial", 1))
        self.assertEqual([item["status"] for item in receipt["items"]], ["parse_failed", "fetch_failed", "parsed"])
        self.assertEqual((directory / "detail-1.json").read_bytes(), b"malformed")
        self.assertFalse((directory / "detail-2.json").exists())

    def test_rate_limit_stops_remaining_requests(self):
        self.listing.return_value = event_page(1, 2, 1, 2)
        self.detail.side_effect = SourceHTTPError(429)
        summary, receipt, _ = self.capture()
        self.assertEqual(summary["status"], "partial")
        self.assertEqual(receipt["stop_http_status"], 429)
        self.assertEqual([item["status"] for item in receipt["items"]], ["fetch_failed", "not_attempted"])
        self.assertEqual(self.detail.call_count, 1)

    def test_listing_http_stop_preserves_page_without_fetching_details(self):
        self.listing.side_effect = [event_page(1, 2, 1), SourceHTTPError(503)]
        summary, receipt, directory = self.capture()
        self.assertEqual((summary["status"], summary["discovery_status"]), ("partial", "failed"))
        self.assertEqual(receipt["stop_http_status"], 503)
        self.assertEqual(receipt["pages"][1]["status"], "fetch_failed")
        self.assertEqual(receipt["items"][0]["status"], "not_attempted")
        self.assertTrue((directory / "list-1.json").is_file())
        self.assertFalse((directory / "list-2.json").exists())
        self.detail.assert_not_called()

    def test_changed_reported_count_is_rejected(self):
        self.listing.side_effect = [event_page(1, 3, 1), event_page(2, 2, 2)]
        self.detail.return_value = event_detail(1)
        summary, receipt, _ = self.capture()
        self.assertEqual(summary["discovery_status"], "failed")
        self.assertIn("달라졌습니다", receipt["pages"][-1]["error"])
        self.assertEqual(self.detail.call_count, 1)

    def test_page_cap_is_reported_even_when_every_selected_detail_parses(self):
        self.listing.return_value = event_page(1, 3, 1)
        self.detail.return_value = event_detail(1)
        summary, _, _ = self.capture(max_pages=1)
        self.assertEqual((summary["status"], summary["discovery_status"]), ("partial", "page_limit"))
        self.assertEqual(self.listing.call_count, 1)

    def test_empty_event_period_is_complete(self):
        self.listing.return_value = event_page(1, 0)
        summary, _, _ = self.capture()
        self.assertEqual((summary["status"], summary["selected"]), ("complete", 0))
        self.detail.assert_not_called()

    def test_library_item_cap_reports_partial_with_a_private_receipt(self):
        self.portal.write_text("도서관명,시도명,시군구명\n합성 도서관,경기도,안성시\n", encoding="utf-8")
        self.listing.return_value = library_page(1, 1, 1, 2)
        self.detail.return_value = (
            '<input name="bIdx" value="1"><div class="bod_view"><h4>합성 도서관</h4>'
            '<div class="view_cont"><p>합성 설명</p></div></div>'
        ).encode()
        args = ["batch", "living", "--portal-csv", str(self.portal), "--name", "library", "--max-items", "1"]
        with (patch("processing.collection.batch.BATCH_ROOT", self.root), patch("sys.argv", args),
              contextlib.redirect_stdout(io.StringIO()) as output):
            self.assertEqual(main(), 2)
        self.assertEqual(json.loads(output.getvalue())["discovery_status"], "item_limit")
        directory = self.root / "library"
        self.assertTrue((directory / "list-1.html").is_file())
        parsed = json.loads((directory / "parsed-1.json").read_text(encoding="utf-8"))
        self.assertEqual(parsed["relationship"]["state"], "candidate")
        self.assertEqual(self.detail.call_count, 1)
