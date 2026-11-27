import hashlib
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from processing.collection.d03 import prepare
from processing.collection.d03_sources import capture_assets
from processing.collection.official_web import road_detail_url
from processing.collection.road_batch import ROAD_SECTION, capture_road_batch
from processing.tests.test_road_batch import road_detail, road_page


class RoadD03Test(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(TemporaryDirectory())).resolve() / "private"
        self.root.mkdir(mode=0o700)
        self.directory = self.root / ROAD_SECTION / "trial"
        with (patch("processing.collection.road_batch.sleep"),
              patch("processing.collection.road_batch.fetch_road_listing", return_value=road_page(1, 1, "9", "8")),
              patch("processing.collection.road_batch.fetch_road_detail",
                    side_effect=[road_detail("9"), road_detail("1")])):
            capture_road_batch("ongoing", "trial", self.root / ROAD_SECTION)
        self.receipt = json.loads((self.directory / "batch.json").read_bytes())

    def rewrite(self, name, content):
        path = self.directory / name
        path.unlink()
        path.write_bytes(content)
        os.chmod(path, 0o600)

    def test_parsed_detail_returns_relative_raw_reference(self):
        self.assertEqual(capture_assets(self.root, "road", "trial", {"9"}), {"9": {
            "raw_asset_path": f"{ROAD_SECTION}/trial/detail-9.html",
            "raw_sha256": hashlib.sha256(road_detail("9")).hexdigest(),
            "official_url": road_detail_url("ongoing", "9"),
            "collected_at": self.receipt["items"][0]["fetched_at"],
            "collection_method": "official-web-road-works",
        }})

    def test_rejects_unparsed_unknown_or_portal_selection(self):
        for keys in ({"8"}, {"7"}, {"portal"}, {"9", "portal"}):
            with self.subTest(keys=keys), self.assertRaises(ValueError):
                capture_assets(self.root, "road", "trial", keys)

    def test_rejects_changed_raw_parsed_record_or_receipt(self):
        original = (self.directory / "detail-9.html").read_bytes()
        self.rewrite("detail-9.html", original.replace("양성면".encode(), "보개면".encode()))
        with self.assertRaises(ValueError):
            capture_assets(self.root, "road", "trial", {"9"})
        self.rewrite("detail-9.html", original)

        parsed = json.loads((self.directory / "parsed-9.json").read_bytes())
        parsed["record"]["fields"]["region"] = "다른 지역"
        self.rewrite("parsed-9.json", json.dumps(parsed, ensure_ascii=False).encode())
        with self.assertRaises(ValueError):
            capture_assets(self.root, "road", "trial", {"9"})

        for change in ({"state": "planned"}, {"schema_version": "other"}, {"batch_id": "other"},
                       {"parsed": 2}, {"status": "complete"}):
            receipt = dict(self.receipt, **change)
            self.rewrite("batch.json", json.dumps(receipt, ensure_ascii=False).encode())
            with self.subTest(change=change), self.assertRaises(ValueError):
                capture_assets(self.root, "road", "trial", {"9"})

    def test_rejects_changed_item_reference_or_time(self):
        for change in ({"file": "detail-8.html"}, {"parsed_file": "parsed-8.json"}, {"sha256": "A" * 64},
                       {"fetched_at": "2026-11-27 08:00:00"}, {"source_url": road_detail_url("planned", "9")}):
            receipt = json.loads(json.dumps(self.receipt))
            receipt["items"][0].update(change)
            self.rewrite("batch.json", json.dumps(receipt, ensure_ascii=False).encode())
            with self.subTest(change=change), self.assertRaises(ValueError):
                capture_assets(self.root, "road", "trial", {"9"})

    def test_reports_other_parser_version_separately(self):
        parsed = json.loads((self.directory / "parsed-9.json").read_bytes())
        self.rewrite("parsed-9.json", json.dumps(dict(parsed, parser_version="road-works-parser-v0")).encode())
        with self.assertRaisesRegex(ValueError, "파서 버전"):
            capture_assets(self.root, "road", "trial", {"9"})

    def test_rejects_readable_parsed_record(self):
        os.chmod(self.directory / "parsed-9.json", 0o644)
        with self.assertRaises(ValueError):
            capture_assets(self.root, "road", "trial", {"9"})

    def test_rejects_symlinked_raw(self):
        raw = self.directory / "detail-9.html"
        copy = self.root / "copy.html"
        copy.write_bytes(raw.read_bytes())
        os.chmod(copy, 0o600)
        raw.unlink()
        raw.symlink_to(copy)
        with self.assertRaises(ValueError):
            capture_assets(self.root, "road", "trial", {"9"})

    def test_prepare_outputs_pending_d03_document(self):
        review = self.root / "road-review.json"
        review.write_text(json.dumps({
            "archive_kind": "road",
            "archive_name": "trial",
            "data_kind": "synthetic",
            "documents": [{
                "asset": "9",
                "official_url": road_detail_url("ongoing", "9"),
                "document_id": "40000000-0000-4000-8000-000000000009",
                "document_version_id": "50000000-0000-4000-8000-000000000009",
                "version_no": 1,
                "publisher": "안성시",
                "title": "사람이 검토한 공사명",
                "published_date": None,
                "official_number": None,
                "collected_at": None,
                "cleaned_text": "사업위치와 공사기간을 검토한 본문",
                "redaction_log": [],
            }],
        }, ensure_ascii=False), encoding="utf-8")
        self.assertEqual(prepare(review, "road-result", self.root), {"preparation_id": "road-result", "documents": 1})
        output = json.loads((self.root / "collection-d03" / "road-result" / "source-import.json").read_bytes())
        document = output["documents"][0]
        self.assertEqual(document["raw_asset_path"], f"{ROAD_SECTION}/trial/detail-9.html")
        self.assertEqual(document["collection_method"], "official-web-road-works")
        self.assertEqual((document["use_review"], document["check_result"]), ("pending", "unchecked"))
        self.assertEqual(document["collected_at"], self.receipt["items"][0]["fetched_at"].replace("+00:00", "Z"))


if __name__ == "__main__":
    unittest.main()
