import hashlib
import json
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from processing.collection import batch, portal
from processing.collection.d03 import prepare
from processing.collection.d03_sources import capture_assets


def page(number, total, *names):
    rows = [{"fstvlNm": name, "rdnmadr": "경기도 " + name.split()[0] + " 합성로 1"}
            for name in names]
    return json.dumps({"response": {
        "header": {"resultCode": "00"},
        "body": {"pageNo": number, "numOfRows": 2, "totalCount": total, "items": rows},
    }}, ensure_ascii=False).encode()


class PortalCollectionTest(unittest.TestCase):
    def setUp(self):
        self.private = Path(self.enterContext(TemporaryDirectory())).resolve() / "private"
        self.root = self.private / "collection-portal"
        self.capture = self.root / "run"
        self.key = "synthetic+portal/key="
        self.pages = [page(1, 3, "안성시 합성 축제", "수원시 비교 축제"), page(2, 3, "안성시 두 번째 축제")]
        self.fetch = self.enterContext(patch.object(portal, "fetch_portal_page", side_effect=self.pages))
        self.enterContext(patch.object(portal, "PAGE_SIZE", 2))
        self.enterContext(patch.object(portal, "sleep"))

    def collect(self):
        return portal.collect_portal("culture", "run", self.root, self.key)

    def test_snapshot_keeps_raw_bytes_and_reproduces_csv(self):
        self.assertEqual(self.collect(), {"snapshot_id": "run", "status": "complete", "pages": 2, "rows": 3})
        csv, receipt = portal.read_portal_snapshot(self.private, "run")
        self.assertEqual(receipt["projection"]["anseong_rows"], 2)
        self.assertIn("수원시 비교 축제".encode(), csv)
        for i, (entry, raw) in enumerate(zip(receipt["responses"], self.pages), 1):
            self.assertEqual((self.capture / f"page-{i}.json").read_bytes(), raw)
            self.assertEqual(entry["sha256"], hashlib.sha256(raw).hexdigest())
        self.assertNotIn(self.key.encode(), (self.capture / "portal.json").read_bytes())
        with self.assertRaisesRegex(ValueError, "이미 사용"):
            self.collect()
        self.assertEqual(self.fetch.call_count, 2)

    def test_changed_total_keeps_failed_page_and_blocks_csv_use(self):
        inconsistent = page(2, 4, "안성시 셋째", "안성시 넷째")
        self.fetch.side_effect = [self.pages[0], inconsistent]
        self.assertEqual(self.collect()["status"], "failed")
        self.assertEqual((self.capture / "page-2.json").read_bytes(), inconsistent)
        self.assertFalse((self.capture / "portal.csv").exists())
        with self.assertRaisesRegex(ValueError, "완료된"):
            portal.read_portal_snapshot(self.private, "run")

    def test_repeated_rows_do_not_produce_snapshot(self):
        first = page(1, 4, "안성시 첫째", "안성시 둘째")
        second = first.replace(b'"pageNo": 1', b'"pageNo": 2')
        reversed_rows = json.loads(second)
        items = reversed_rows["response"]["body"]["items"]
        items[:] = [dict(reversed(row.items())) for row in items]
        self.fetch.side_effect = [first, json.dumps(reversed_rows).encode()]
        self.assertEqual(self.collect()["status"], "failed")
        self.assertIn("반복", (self.capture / "portal.json").read_text())
        self.assertFalse((self.capture / "portal.csv").exists())

    def test_raw_bundle_must_match_projection_and_receipt(self):
        self.collect()
        for filename, bad in (
            ("portal.csv", b"substituted"),
            ("page-1.json", page(1, 3, "안성시 변경", "수원시 비교 축제")),
        ):
            with self.subTest(filename=filename):
                asset = self.capture / filename
                initial = asset.read_bytes()
                asset.write_bytes(bad)
                with self.assertRaises(ValueError):
                    portal.read_portal_snapshot(self.private, "run")
                asset.write_bytes(initial)
        receipt_file = self.capture / "portal.json"
        receipt = json.loads(receipt_file.read_bytes())
        receipt["responses"][0]["fetched_at"] = "2026-02-30T12:00:00Z"
        receipt_file.write_text(json.dumps(receipt))
        with self.assertRaisesRegex(ValueError, "수신 시각"):
            portal.read_portal_snapshot(self.private, "run")

    def test_batch_accepts_snapshot_for_same_category_and_keeps_provenance(self):
        self.collect()
        root = self.private / "collection-batches"
        day = date(2026, 11, 27)
        with patch.object(batch, "fetch_listing", return_value=b'{"curPage":1,"totalCnt":0,"list":[]}') as listing:
            with self.assertRaisesRegex(ValueError, "분야"):
                batch.capture_batch("living", None, "mismatch", root, portal_snapshot="run")
            listing.assert_not_called()
            self.assertFalse(root.exists())
            summary = batch.capture_batch("culture", None, "comparison", root, begin=day, end=day,
                                          portal_snapshot="run")
        self.assertEqual(summary["status"], "complete")
        receipt = json.loads((root / "comparison" / "batch.json").read_bytes())
        self.assertEqual(receipt["portal"]["api_snapshot"], "run")
        self.assertEqual(len(receipt["portal"]["records"]), 2)
        with self.assertRaisesRegex(ValueError, "API 응답 페이지"):
            capture_assets(self.private, "batch", "comparison", {"portal"})

    def test_d03_prepares_reviewed_document_from_raw_api_page(self):
        self.collect()
        review = self.private / "review.json"
        url = portal.page_source("culture", 2, 2)
        review.write_text(json.dumps({
            "archive_kind": "portal", "archive_name": "run", "data_kind": "synthetic",
            "documents": [{
                "asset": "2", "official_url": url, "publisher": "합성 기관",
                "document_id": "40000000-0000-4000-8000-000000000001",
                "document_version_id": "50000000-0000-4000-8000-000000000001",
                "version_no": 1, "title": "검토한 제목", "official_number": None, "published_date": None,
                "collected_at": None, "cleaned_text": "검토한 원문 일부", "redaction_log": [],
            }],
        }))
        self.assertEqual(prepare(review, "prepared", self.private)["documents"], 1)
        result = self.private / "collection-d03" / "prepared" / "source-import.json"
        doc, = json.loads(result.read_bytes())["documents"]
        self.assertEqual(doc["raw_asset_path"], "collection-portal/run/page-2.json")
        self.assertEqual(doc["raw_sha256"], hashlib.sha256(self.pages[1]).hexdigest())
        self.assertEqual(doc["official_url"], url)
        self.assertEqual(doc["collection_method"], "data-go-kr-api")
        self.assertEqual((doc["use_review"], doc["check_result"]), ("pending", "unchecked"))
        with self.assertRaisesRegex(ValueError, "응답 페이지"):
            capture_assets(self.private, "portal", "run", {"portal"})
        # 한 응답 페이지의 여러 행을 각각 문서로 등록할 수 있다.
        shared = json.loads(review.read_text())
        shared["documents"].append({**shared["documents"][0], "document_id": "40000000-0000-4000-8000-000000000002",
                                    "document_version_id": "50000000-0000-4000-8000-000000000002"})
        review.write_text(json.dumps(shared))
        self.assertEqual(prepare(review, "shared-page", self.private)["documents"], 2)
