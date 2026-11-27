from datetime import date
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from processing.collection.batch import capture_batch
from processing.collection.capture import capture
from processing.collection.d03_sources import capture_assets


def _json(raw):
    return json.dumps(raw, ensure_ascii=False).encode("utf-8")


class D03SourcesTest(unittest.TestCase):
    def setUp(self):
        folder = Path(self.enterContext(TemporaryDirectory())).resolve()
        self.root = folder / "private"
        self.csv = folder / "selected.csv"
        self.html = (
            '<input name="bIdx" value="77"><div class="bod_view"><h4>합성 도서관 안내</h4>'
            '<div class="view_cont"><p>시설 점검</p></div></div>'
        ).encode("utf-8")

    def _single(self, content=None):
        self.csv.write_bytes("도서관명,시도명,시군구명\n합성 도서관,경기도,안성시\n".encode("cp949"))
        with patch("processing.collection.capture.fetch_detail",
                   return_value=self.html if content is None else content):
            capture("living", self.csv, "77", "one", self.root / "collection")
        return self.root / "collection" / "one"

    def _batch(self):
        self.csv.write_text("축제명,소재지도로명주소\n합성 축제,경기도 안성시 시험로\n", encoding="utf-8")
        listing = _json({"curPage": 1, "totalCnt": 2, "list": [{"idx": 71}, {"idx": 72}]})
        detail = _json({"idx": 71, "title": "합성 축제"})
        with (
            patch("processing.collection.batch.sleep"),
            patch("processing.collection.batch.fetch_listing", return_value=listing),
            patch("processing.collection.batch.fetch_detail", side_effect=[detail, b"malformed"]),
        ):
            day = date(2026, 11, 1)
            capture_batch("culture", self.csv, "trial", self.root / "collection-batches", begin=day, end=day)
        return self.root / "collection-batches" / "trial"

    def test_single_revalidates_originals_and_returns_relative_references(self):
        path = self._single()
        receipt = json.loads((path / "capture.json").read_bytes())
        report = capture_assets(self.root, "single", "one", {"portal", "77"})
        self.assertEqual(report, {
            "portal": {
                "raw_asset_path": "collection/one/portal.csv",
                "raw_sha256": hashlib.sha256(self.csv.read_bytes()).hexdigest(),
                "official_url": "https://www.data.go.kr/data/15013109/standard.do",
                "collected_at": None,
            },
            "77": {
                "raw_asset_path": "collection/one/web.html",
                "raw_sha256": hashlib.sha256(self.html).hexdigest(),
                "official_url": "https://www.anseong.go.kr/library/bbs/view.do?bIdx=77&mId=0401010000&ptIdx=16",
                "collected_at": receipt["web_fetched_at"],
            },
        })

    def test_partial_batch_allows_its_parsed_detail_only(self):
        path = self._batch()
        receipt = json.loads((path / "batch.json").read_bytes())
        self.assertEqual(receipt["status"], "partial")
        report = capture_assets(self.root, "batch", "trial", {"71"})
        self.assertEqual(report["71"]["raw_asset_path"], "collection-batches/trial/detail-71.json")
        self.assertEqual(report["71"]["collected_at"], receipt["items"][0]["fetched_at"])
        for key in ("72", "73"):
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "파싱이 완료"):
                capture_assets(self.root, "batch", "trial", {key})

    def test_rejects_failed_single_and_mismatched_archive_selections(self):
        self._single(b"<html>not a known bulletin</html>")
        with self.assertRaisesRegex(ValueError, "정상 파싱"):
            capture_assets(self.root, "single", "one", {"77"})
        for kind, name, keys in (
            ("unknown", "one", {"portal"}),
            ("single", "../one", {"77"}),
            ("single", "one", {"1" * 19}),
            ("single", "one", {"/outside/file"}),
            ("single", "one", set()),
        ):
            with self.subTest(kind=kind, name=name, keys=keys), self.assertRaises(ValueError):
                capture_assets(self.root, kind, name, keys)

    def test_compares_raw_hash_and_identity_separately(self):
        path = self._single()
        raw = self.html.replace(b'value="77"', b'value="78"')
        (path / "web.html").write_bytes(raw)
        with self.assertRaisesRegex(ValueError, "원본 해시"):
            capture_assets(self.root, "single", "one", {"77"})
        manifest = path / "capture.json"
        receipt = json.loads(manifest.read_bytes())
        digest = hashlib.sha256(raw).hexdigest()
        receipt["web"]["sha256"] = receipt["comparison"]["web"]["sha256"] = digest
        manifest.write_bytes(_json(receipt))
        with self.assertRaisesRegex(ValueError, "번호"):
            capture_assets(self.root, "single", "one", {"77"})

    def test_rejects_wrong_route_bad_timestamp_and_traversal(self):
        manifest = self._single() / "capture.json"
        for new_web, new_time, error in (
            ({"source_url": "https://example.invalid/77"}, None, "원문 주소"),
            ({"file": "../web.html"}, None, "파일 이름"),
            ({}, "2026-11-01T00:00:00+09:00", "UTC"),
            ({}, "2026-02-30T00:00:00Z", "UTC"),
        ):
            with self.subTest(new_web=new_web, new_time=new_time):
                original = manifest.read_bytes()
                receipt = json.loads(original)
                receipt["web"].update(new_web)
                if new_time is not None:
                    receipt["web_fetched_at"] = new_time
                manifest.write_bytes(_json(receipt))
                with self.assertRaisesRegex(ValueError, error):
                    capture_assets(self.root, "single", "one", {"77"})
                manifest.write_bytes(original)

    def test_rejects_symlink_even_if_target_bytes_match(self):
        path = self._single()
        raw = path / "portal.csv"
        raw.unlink()
        raw.symlink_to(self.csv)
        with self.assertRaisesRegex(ValueError, "안전하게 읽을 수"):
            capture_assets(self.root, "single", "one", {"portal"})
        alias = self.root / "alias"
        alias.symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "심볼릭 링크"):
            capture_assets(alias, "single", "one", {"77"})

    def test_rejects_duplicate_batch_ids_and_unknown_receipt_schema(self):
        manifest = self._batch() / "batch.json"
        receipt = json.loads(manifest.read_bytes())
        receipt["items"].append(receipt["items"][0])
        manifest.write_bytes(_json(receipt))
        with self.assertRaisesRegex(ValueError, "중복 게시물"):
            capture_assets(self.root, "batch", "trial", {"71"})
        receipt["schema_version"] = "citizen-source-batch-v2"
        manifest.write_bytes(_json(receipt))
        with self.assertRaisesRegex(ValueError, "규격"):
            capture_assets(self.root, "batch", "trial", {"71"})

    def test_rejects_rewritten_batch_comparison(self):
        comparison = self._batch() / "parsed-71.json"
        receipt = json.loads(comparison.read_bytes())
        receipt["web"]["record"]["external_id"] = "72"
        comparison.write_bytes(_json(receipt))
        with self.assertRaisesRegex(ValueError, "게시물 번호"):
            capture_assets(self.root, "batch", "trial", {"71"})

    def test_limits_receipt_read(self):
        self._single()
        with (
            patch("processing.collection.d03_sources.CAPTURE_RECEIPT_MAX_BYTES", 128),
            self.assertRaisesRegex(ValueError, "허용 크기"),
        ):
            capture_assets(self.root, "single", "one", {"77"})

    def test_previous_capture_larger_than_java_request_limit_is_readable(self):
        self.csv.write_text(
            "축제명,소재지도로명주소,축제내용\n"
            + ("합성 축제,경기도 안성시 시험로," + "가" * 120_000 + "\n") * 25,
            encoding="utf-8",
        )
        with patch("processing.collection.capture.fetch_detail",
                   return_value=b'{"idx":17,"title":"synthetic"}'):
            capture("culture", self.csv, "17", "large", self.root / "collection")
        manifest = self.root / "collection" / "large" / "capture.json"
        self.assertGreater(manifest.stat().st_size, 8 * 1024 * 1024)
        assets = capture_assets(self.root, "single", "large", {"17"})
        self.assertEqual(assets["17"]["raw_asset_path"], "collection/large/web.json")

    def test_rejects_public_archive_directories_or_files(self):
        path = self._single()
        for entry, perm, original in ((path.parent, 0o755, 0o700), (path, 0o750, 0o700),
                                      (path / "capture.json", 0o644, 0o600),
                                      (path / "web.html", 0o666, 0o600)):
            with self.subTest(entry=entry):
                entry.chmod(perm)
                try:
                    with self.assertRaisesRegex(ValueError, "실행 사용자만 접근"):
                        capture_assets(self.root, "single", "one", {"77"})
                finally:
                    entry.chmod(original)

    def test_writer_preserves_raw_without_completed_receipt_over_limit(self):
        self.csv.write_bytes("도서관명,시도명,시군구명\n합성 도서관,경기도,안성시\n".encode("cp949"))
        with (patch("processing.collection.capture.fetch_detail", return_value=self.html),
              patch("processing.collection.capture.CAPTURE_RECEIPT_MAX_BYTES", 128),
              self.assertRaisesRegex(ValueError, "완료 기록이 64 MiB")):
            capture("living", self.csv, "77", "receipt-limit", self.root / "collection")
        path = self.root / "collection" / "receipt-limit"
        self.assertEqual((path / "web.html").read_bytes(), self.html)
        self.assertFalse((path / "capture.json").exists())

    def test_revalidates_portal_schema_when_updated_hash_matches(self):
        path = self._single()
        raw = b"some,title\nnot,an,official,export\n"
        (path / "portal.csv").write_bytes(raw)
        manifest = path / "capture.json"
        receipt = json.loads(manifest.read_bytes())
        receipt["portal"]["sha256"] = hashlib.sha256(raw).hexdigest()
        manifest.write_bytes(_json(receipt))
        with self.assertRaisesRegex(ValueError, "머리글"):
            capture_assets(self.root, "single", "one", {"portal"})
