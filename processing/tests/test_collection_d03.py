import contextlib
from datetime import date
import hashlib
import io
import json
import os
from pathlib import Path
import stat
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from processing.collection.batch import capture_batch
from processing.collection.capture import capture
from processing.collection.d03 import main, prepare
from processing.extraction.validation import parse_input


class D03PreparationTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(TemporaryDirectory())).resolve() / "private"
        self.root.mkdir(mode=0o700)
        self.portal = self.root / "input.csv"
        self.portal_raw = "축제명,소재지도로명주소\n합성 축제,경기도 안성시 시험로 1\n".encode("cp949")
        self.portal.write_bytes(self.portal_raw)
        self.web_raw = '{"idx":17,"title":"공식 제목에 포함된 합성 미검토 표시"}'.encode()
        with patch("processing.collection.capture.fetch_detail", return_value=self.web_raw):
            capture("culture", self.portal, "17", "archive", self.root / "collection")
        self.review_file = self.root / "input.json"
        self.review = {
            "archive_kind": "single",
            "archive_name": "archive",
            "data_kind": "synthetic",
            "documents": [
                self.document("portal", "https://www.data.go.kr/data/15013104/standard.do", 1,
                              "2026-11-03T03:00:00Z"),
                self.document("17", "https://www.anseong.go.kr/event/program/popup/detail.do?idx=17", 2),
            ],
        }

    @staticmethod
    def document(asset, url, suffix, collected_at=None):
        return {
            "asset": asset,
            "official_url": url,
            "document_id": f"40000000-0000-4000-8000-{suffix:012}",
            "document_version_id": f"50000000-0000-4000-8000-{suffix:012}",
            "version_no": 1,
            "publisher": "합성 기관",
            "title": "사람이 검토한 제목",
            "published_date": None,
            "official_number": None,
            "collected_at": collected_at,
            "cleaned_text": "검토한 원문 일부",
            "redaction_log": [],
        }

    def write_review(self):
        raw = json.dumps(self.review, ensure_ascii=False).encode()
        self.review_file.write_bytes(raw)
        return raw

    def test_single_outputs_two_pending_documents_with_original_relative_paths(self):
        supplied = self.write_review()
        output = self.root / "collection-d03" / "result"
        before = {p.name: p.read_bytes() for p in (self.root / "collection" / "archive").iterdir()}
        self.assertEqual(prepare(self.review_file, "result", self.root),
                         {"preparation_id": "result", "documents": 2})
        response = json.loads((output / "source-import.json").read_bytes())
        self.assertEqual(response["schema_version"], "source-import-v1")
        self.assertEqual((response["events"], response["evidence"]), ([], []))
        self.assertEqual(response["data_kind"], "synthetic")
        first, second = response["documents"]
        self.assertEqual(first["raw_asset_path"], "collection/archive/portal.csv")
        self.assertEqual(second["raw_asset_path"], "collection/archive/web.json")
        logged = json.loads(before["capture.json"])
        self.assertEqual(second["collected_at"], logged["web_fetched_at"].replace("+00:00", "Z"))
        self.assertEqual(first["collected_at"], "2026-11-03T03:00:00Z")
        for doc, raw in ((first, self.portal_raw), (second, self.web_raw)):
            self.assertEqual(doc["raw_sha256"], hashlib.sha256(raw).hexdigest())
            self.assertEqual(doc["published_date"], None)
            self.assertEqual((doc["use_review"], doc["check_result"], doc["checks"]), ("pending", "unchecked", []))
            self.assertNotIn("미검토 표시", json.dumps(doc, ensure_ascii=False))
        self.assertEqual((output / "review.json").read_bytes(), supplied)
        self.assertEqual({p.name: p.read_bytes() for p in (self.root / "collection" / "archive").iterdir()}, before)
        self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o700)
        self.assertTrue(all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in output.iterdir()))

    def test_prepared_text_and_blocks_match_existing_d05_input(self):
        self.review["documents"] = self.review["documents"][1:]
        metadata = self.review["documents"][0]
        metadata["title"] = "제목"
        metadata["cleaned_text"] = "첫째 줄\r\n둘째 줄"
        meta_before = self.write_review()
        prepare(self.review_file, "result", self.root)
        output = self.root / "collection-d03" / "result"
        doc = json.loads((output / "source-import.json").read_bytes())["documents"][0]
        self.assertEqual((doc["title"], doc["cleaned_text"]), ("제목", "첫째 줄\n둘째 줄"))
        self.assertEqual(doc["text_sha256"], hashlib.sha256(doc["cleaned_text"].encode()).hexdigest())
        proto = {"data_kind": "synthetic", "document_version_id": doc["document_version_id"],
                 "title": doc["title"], "published_date": doc["published_date"], "blocks": doc["block_index"]}
        parse_input(json.dumps(proto, ensure_ascii=False).encode())
        self.assertEqual((output / "review.json").read_bytes(), meta_before)

    def test_existing_name_and_incorrect_source_or_time_do_not_overwrite(self):
        self.write_review()
        prepare(self.review_file, "result", self.root)
        output = self.root / "collection-d03" / "result" / "source-import.json"
        original = output.read_bytes()
        item = self.review["documents"][1]
        item["cleaned_text"] = "다른 본문"
        self.write_review()
        with self.assertRaisesRegex(ValueError, "이미 사용"):
            prepare(self.review_file, "result", self.root)
        self.assertEqual(output.read_bytes(), original)
        item["official_url"] = "https://example.invalid/wrong"
        self.write_review()
        with self.assertRaisesRegex(ValueError, "official_url"):
            prepare(self.review_file, "bad-url", self.root)
        item["official_url"] = "https://www.anseong.go.kr/event/program/popup/detail.do?idx=17"
        item["collected_at"] = "2026-11-03T03:00:00Z"
        self.write_review()
        with self.assertRaisesRegex(ValueError, "collected_at"):
            prepare(self.review_file, "bad-time", self.root)
        self.assertEqual([p.name for p in output.parent.parent.iterdir()], ["result"])

    def test_invalid_fields_and_duplicate_ids_fail_before_writing(self):
        first, second = self.review["documents"]
        for key, bad in (("document_id", first["document_id"]), ("asset", "portal"),
                         ("published_date", "2026-02-30"), ("version_no", True), ("cleaned_text", "\x00")):
            with self.subTest(key=key):
                original = second[key]
                second[key] = bad
                self.write_review()
                with self.assertRaisesRegex(ValueError, key):
                    prepare(self.review_file, "invalid", self.root)
                second[key] = original
        self.assertFalse((self.root / "collection-d03").exists())

    def test_partial_batch_parsed_web_item_is_eligible(self):
        page = b'{"curPage":1,"totalCnt":2,"list":[{"idx":17},{"idx":18}]}'
        day = date(2026, 11, 3)
        with (patch("processing.collection.batch.fetch_listing", return_value=page),
              patch("processing.collection.batch.fetch_detail", return_value=self.web_raw),
              patch("processing.collection.batch.sleep")):
            result = capture_batch("culture", self.portal, "batch", self.root / "collection-batches",
                                   begin=day, end=day, max_items=1)
        self.assertEqual(result["status"], "partial")
        self.review.update(archive_kind="batch", archive_name="batch")
        self.review["documents"] = self.review["documents"][1:]
        self.write_review()
        prepare(self.review_file, "batch-result", self.root)
        output = self.root / "collection-d03" / "batch-result"
        doc = json.loads((output / "source-import.json").read_bytes())["documents"][0]
        self.assertEqual(doc["raw_asset_path"], "collection-batches/batch/detail-17.json")

    def test_rejects_request_too_large_for_existing_java_reader(self):
        self.review["documents"] = self.review["documents"][1:]
        self.review["documents"][0]["cleaned_text"] = "가" * 1_400_000
        raw = self.write_review()
        self.assertLess(len(raw), 8 * 1024 * 1024)
        with self.assertRaisesRegex(ValueError, "등록 입력이 8 MiB"):
            prepare(self.review_file, "oversized", self.root)
        self.assertFalse((self.root / "collection-d03").exists())

    def test_cli_stdout_has_only_private_preparation_summary(self):
        self.write_review()
        arguments = ["d03", "--input", os.fspath(self.review_file), "--name", "cli"]
        with (patch("sys.argv", arguments), patch("processing.collection.d03.PRIVATE_ROOT", self.root),
              contextlib.redirect_stdout(io.StringIO()) as stream):
            self.assertEqual(main(), 0)
        self.assertEqual(json.loads(stream.getvalue()), {"preparation_id": "cli", "documents": 2})
