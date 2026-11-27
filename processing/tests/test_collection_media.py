import hashlib
from io import BytesIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from processing.collection import media
from processing.collection.d03 import prepare
from processing.collection.official_web import SourceHTTPError, detail_url


ATTACH_ID = "a" * 64
FILE_SN = "b" * 32
TIMESTAMP = "2026-11-20T04:00:00Z"
PNG = b"\x89PNG\r\n\x1a\n" + b"synthetic"
PARENT = detail_url("living", "17")


def notice():
    return f"""<input name="bIdx" value="17">
    <div class="bod_view">
      <h4>합성 공지</h4>
      <div class="view_cont"><img src="/common/imgView.do?attachId={ATTACH_ID}&amp;fileSn={FILE_SN}&amp;mode=origin"></div>
      <dl class="view_file"><dt>첨부 파일</dt><dd><ul><li>
        <a href="#" onclick="fn_egov_downFile('{ATTACH_ID}','{FILE_SN}'); return false;">합성안내.hwpx [1 KByte]</a>
      </li></ul></dd></dl>
    </div>""".encode()


def hwpx(mime: bytes) -> bytes:
    stream = BytesIO()
    with ZipFile(stream, "w") as package:
        package.writestr("mimetype", mime)
    return stream.getvalue()


class MediaCollectionTest(unittest.TestCase):
    def setUp(self):
        self.private = Path(self.enterContext(TemporaryDirectory())).resolve() / "private"
        self.notice_dir = self.private / media.NOTICE_SECTION / "notice"
        self.media_dir = self.private / media.MEDIA_SECTION / "provided"
        self.file = self.private.parent / "local-download"
        self.fetch = self.enterContext(patch.object(media, "fetch_detail", return_value=notice()))

    def inspect(self):
        return media.inspect_notice(self.private, "17", "notice")

    def store(self, asset, content):
        self.file.write_bytes(content)
        return media.store_media(self.private, "notice", asset, self.file, "provided", TIMESTAMP)

    def test_no_body_notice_yields_image_and_attachment_manifest(self):
        self.assertEqual(self.inspect(), {"notice_id": "notice", "status": "parsed", "media": 2})
        receipt = json.loads((self.notice_dir / "notice.json").read_bytes())
        self.assertEqual(receipt["source_url"], PARENT)
        self.assertEqual(receipt["sha256"], hashlib.sha256(notice()).hexdigest())
        self.assertEqual((self.notice_dir / "notice.html").read_bytes(), notice())
        self.assertEqual([entry["kind"] for entry in receipt["media"]], ["image", "attachment"])
        self.assertEqual(receipt["media"][1]["format"], "hwpx")

    def test_failed_notice_is_recorded_and_cannot_supply_media(self):
        for raw, status, has_html in ((b"wrong page", "parse_failed", True),
                                      (SourceHTTPError(403), "fetch_failed", False)):
            with self.subTest(status=status):
                if isinstance(raw, Exception):
                    self.fetch.side_effect = raw
                else:
                    self.fetch.return_value = raw
                result = media.inspect_notice(self.private, "17", status)
                directory = self.private / media.NOTICE_SECTION / status
                self.assertEqual(result["status"], status)
                self.assertEqual((directory / "notice.html").exists(), has_html)
                self.assertTrue((directory / "notice.json").exists())
                self.file.write_bytes(PNG)
                with self.assertRaisesRegex(ValueError, "공지 수집 기록"):
                    media.store_media(self.private, status, 1, self.file, "invalid", TIMESTAMP)

    def test_store_image_checks_link_and_keeps_exact_bytes(self):
        self.inspect()
        self.assertEqual(self.store(1, PNG)["format"], "png")
        bound = media.read_media_assets(self.private, "provided", {"1"})["1"]
        self.assertEqual((self.private / bound["raw_asset_path"]).read_bytes(), PNG)
        self.assertEqual(bound["raw_sha256"], hashlib.sha256(PNG).hexdigest())
        self.assertEqual((bound["official_url"], bound["collected_at"]), (PARENT, TIMESTAMP))
        self.assertEqual(bound["collection_method"], "official-web-media-manual")
        self.assertEqual(self.fetch.call_count, 1)
        with self.assertRaisesRegex(ValueError, "이미 사용"):
            self.store(1, PNG + b"replacement")
        self.assertEqual((self.media_dir / "media.png").read_bytes(), PNG)

    def test_wrong_selection_and_non_hwpx_zip_do_not_create_an_archive(self):
        self.inspect()
        for asset, raw in ((3, PNG), (2, PNG), (2, b""), (2, hwpx(b"application/zip")), (2, b"PK\x03\x04broken")):
            with self.subTest(asset=asset, raw_length=len(raw)), self.assertRaises(ValueError):
                self.store(asset, raw)
        self.assertFalse(self.media_dir.exists())

    def test_source_and_link_integrity_are_rechecked(self):
        self.inspect()
        self.store(1, PNG)
        receipt = self.media_dir / "media.json"
        original = receipt.read_bytes()
        metadata = json.loads(original)
        metadata["linked_source_url"] += "-different"
        receipt.write_text(json.dumps(metadata))
        with self.assertRaisesRegex(ValueError, "연결 기록"):
            media.read_media_assets(self.private, "provided", {"1"})
        receipt.write_bytes(original)
        with self.assertRaisesRegex(ValueError, "매체가 보관"):
            media.read_media_assets(self.private, "provided", {"2"})
        (self.media_dir / "media.png").write_bytes(PNG + b"changed")
        with self.assertRaisesRegex(ValueError, "원본 또는 형식"):
            media.read_media_assets(self.private, "provided", {"1"})

    def test_parent_html_and_candidate_list_are_rechecked(self):
        self.inspect()
        self.store(1, PNG)
        notice_receipt = self.notice_dir / "notice.json"
        original = notice_receipt.read_bytes()
        metadata = json.loads(original)
        metadata["media"].reverse()
        notice_receipt.write_text(json.dumps(metadata))
        with self.assertRaisesRegex(ValueError, "매체 목록"):
            media.read_media_assets(self.private, "provided", {"1"})
        notice_receipt.write_bytes(original)
        (self.notice_dir / "notice.html").write_bytes(notice() + b"changed")
        with self.assertRaisesRegex(ValueError, "공지 원본"):
            media.read_media_assets(self.private, "provided", {"1"})

    def test_download_timestamp_uses_the_d03_year_range(self):
        self.inspect()
        self.file.write_bytes(PNG)
        too_early = "0999-01-01T00:00:00Z"
        with self.assertRaisesRegex(ValueError, "1000년"):
            media.store_media(self.private, "notice", 1, self.file, "provided", too_early)
        self.assertFalse(self.media_dir.exists())
        self.store(1, PNG)
        receipt = self.media_dir / "media.json"
        metadata = json.loads(receipt.read_bytes())
        metadata["operator_downloaded_at"] = too_early
        receipt.write_text(json.dumps(metadata))
        with self.assertRaisesRegex(ValueError, "1000년"):
            media.read_media_assets(self.private, "provided", {"1"})

    def test_reviewed_hwpx_is_prepared_as_source_only_with_original_hash(self):
        self.inspect()
        raw = hwpx(b"application/hwp+zip")
        self.store(2, raw)
        review_path = self.private / "review.json"
        review_path.write_text(json.dumps({
            "archive_kind": "media", "archive_name": "provided", "data_kind": "synthetic",
            "documents": [{
                "asset": "2", "official_url": PARENT, "publisher": "합성 기관", "title": "검토한 첨부 제목",
                "document_id": "40000000-0000-4000-8000-000000000001",
                "document_version_id": "50000000-0000-4000-8000-000000000001",
                "version_no": 1, "official_number": None, "published_date": None, "collected_at": None,
                "cleaned_text": "사람이 확인한 합성 본문", "redaction_log": [],
            }],
        }))
        self.assertEqual(prepare(review_path, "result", self.private)["documents"], 1)
        result = json.loads((self.private / "collection-d03/result/source-import.json").read_bytes())
        doc, = result["documents"]
        self.assertEqual(result["events"], [])
        self.assertEqual(doc["raw_asset_path"], "collection-media/provided/media.hwpx")
        self.assertEqual(doc["raw_sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual((doc["collected_at"], doc["use_review"], doc["check_result"]), (TIMESTAMP, "pending", "unchecked"))
