import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import stat
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from processing.collection.capture import capture, main


class CollectionCaptureTest(unittest.TestCase):
    def setUp(self):
        work = self.enterContext(TemporaryDirectory())
        self.root = Path(work).resolve() / "private" / "collection"
        self.portal = Path(work) / "selected.csv"
        self.portal_raw = "도서관명,시도명,시군구명\r\n합성도서관,경기도,안성시\r\n".encode("euc-kr")
        self.portal.write_bytes(self.portal_raw)
        self.html = (
            '<input name="bIdx" value="77"><div class="bod_view"><h4>합성도서관 운영 안내</h4>'
            '<div class="view_cont"><p>시설 점검</p><img src="/mock.png"></div></div>'
        ).encode("utf-8")

    def test_capture_keeps_originals_and_comparison(self):
        with patch("processing.collection.capture.fetch_detail", return_value=self.html) as fetch:
            summary = capture("living", self.portal, "77", "trial-77", self.root)
        fetch.assert_called_once_with("living", "77", limit=8 * 1024 * 1024)
        self.assertEqual(summary, {"capture_id": "trial-77", "status": "parsed"})
        directory = self.root / "trial-77"
        self.assertEqual(stat.S_IMODE(directory.stat().st_mode), 0o700)
        self.assertEqual((directory / "portal.csv").read_bytes(), self.portal_raw)
        self.assertEqual((directory / "web.html").read_bytes(), self.html)
        self.assertTrue(all(stat.S_IMODE(p.stat().st_mode) == 0o600 for p in directory.iterdir()))
        self.assertEqual(set(p.name for p in directory.iterdir()), {"portal.csv", "web.html", "capture.json"})
        record = json.loads((directory / "capture.json").read_text(encoding="utf-8"))
        self.assertEqual(record["portal"]["sha256"], hashlib.sha256(self.portal_raw).hexdigest())
        self.assertTrue(record["portal"]["catalog_url"].endswith("/15013109/standard.do"))
        self.assertEqual(record["web"]["sha256"], hashlib.sha256(self.html).hexdigest())
        self.assertTrue(record["web"]["source_url"].endswith("bIdx=77&mId=0401010000&ptIdx=16"))
        self.assertTrue(record["web_fetched_at"].endswith("+00:00"))
        self.assertEqual(record["comparison"]["web"]["record"]["review_flags"], ["inline_image"])
        self.assertEqual(record["comparison"]["relationship"]["portal_indexes"], [0])

    def test_unrecognized_post_format_remains_private_for_review(self):
        raw = b"<html>A format that the library parser cannot read</html>"
        with (
            patch("processing.collection.capture.fetch_detail", return_value=raw),
            patch("processing.collection.capture.CAPTURE_ROOT", self.root),
            patch("sys.argv", ["capture", "living", "--web-id", "77", "--name", "unread",
                               "--portal-csv", str(self.portal)]),
            contextlib.redirect_stdout(io.StringIO()) as output,
        ):
            self.assertEqual(main(), 2)
        self.assertEqual(json.loads(output.getvalue()), {"capture_id": "unread", "status": "parse_failed"})
        directory = self.root / "unread"
        self.assertEqual((directory / "web.html").read_bytes(), raw)
        record = json.loads((directory / "capture.json").read_text(encoding="utf-8"))
        self.assertIsNone(record["comparison"])
        self.assertIn("본문 영역", record["parse_error"])
        self.assertNotIn("A format", record["parse_error"])

    def test_invalid_name_symlink_and_existing_directory_fail_before_request(self):
        occupied = self.root / "occupied"
        occupied.mkdir(parents=True)
        (occupied / "original.txt").write_bytes(b"saved")
        (self.root / "shortcut").symlink_to(occupied)
        with patch("processing.collection.capture.fetch_detail") as fetch:
            for name, root in (
                ("../escape", self.root), ("occupied", self.root), ("shortcut", self.root),
                ("escape", self.root / "shortcut"),
            ):
                with self.subTest(name=name, root=root), self.assertRaises(ValueError):
                    capture("living", self.portal, "77", name, root)
        fetch.assert_not_called()
        self.assertEqual((occupied / "original.txt").read_bytes(), b"saved")

    def test_request_failure_does_not_create_a_capture(self):
        with (
            patch("processing.collection.capture.fetch_detail", side_effect=ValueError("수신 실패")),
            self.assertRaisesRegex(ValueError, "수신 실패"),
        ):
            capture("living", self.portal, "77", "failed", self.root)
        self.assertFalse((self.root / "failed").exists())

    def test_other_writer_keeps_existing_bytes_after_name_race(self):
        target = self.root / "same-id"

        def fetch(*_args, **_kwargs):
            self.root.mkdir(parents=True, mode=0o700)
            target.mkdir()
            (target / "portal.csv").write_bytes(b"other process")
            return self.html

        with (
            patch("processing.collection.capture.fetch_detail", side_effect=fetch),
            self.assertRaisesRegex(ValueError, "이미 사용 중"),
        ):
            capture("living", self.portal, "77", "same-id", self.root)
        self.assertEqual((target / "portal.csv").read_bytes(), b"other process")
        self.assertFalse((target / "capture.json").exists())

    def test_switching_root_to_symlink_during_fetch_cannot_write_outside(self):
        outside = self.portal.parent / "other-dir"
        outside.mkdir(mode=0o700)

        def fetch(*_args, **_kwargs):
            self.root.parent.mkdir()
            self.root.symlink_to(outside)
            return self.html

        with (
            patch("processing.collection.capture.fetch_detail", side_effect=fetch),
            self.assertRaisesRegex(ValueError, "심볼릭 링크"),
        ):
            capture("living", self.portal, "77", "escaped", self.root)
        self.assertEqual(list(outside.iterdir()), [])

    def test_public_root_is_never_used_to_store_raw_bytes(self):
        self.root.mkdir(parents=True)
        self.root.chmod(0o755)
        with (
            patch("processing.collection.capture.fetch_detail", return_value=self.html),
            self.assertRaisesRegex(ValueError, "실행 사용자만 접근"),
        ):
            capture("living", self.portal, "77", "public", self.root)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_fifo_input_is_rejected_without_waiting_or_fetching(self):
        fifo = self.portal.parent / "not-a-file.csv"
        os.mkfifo(fifo)
        with (
            patch("processing.collection.capture.fetch_detail") as fetch,
            self.assertRaisesRegex(ValueError, "일반 파일"),
        ):
            capture("living", fifo, "77", "fifo", self.root)
        fetch.assert_not_called()
