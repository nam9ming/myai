import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from processing.collection.d03 import prepare
from processing.collection.d03_sources import capture_assets
from processing.collection.official_web import SourceHTTPError
from processing.collection.welfare_api import detail_source_url, list_source_url, service_page_url
from processing.collection.welfare_batch import WELFARE_SECTION, collect_welfare, main
from processing.tests.test_welfare_api import ENCODED_KEY, KEY, detail_xml, list_xml

_BATCH = "processing.collection.welfare_batch"


def detail_for(serv_id, _key):
    return detail_xml(serv_id)


class WelfareBatchTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(TemporaryDirectory())).resolve() / WELFARE_SECTION
        self.enterContext(patch(_BATCH + ".sleep"))
        self.enterContext(patch(_BATCH + ".PAGE_SIZE", 2))
        self.listing = self.enterContext(patch(_BATCH + ".fetch_list"))
        self.detail = self.enterContext(patch(_BATCH + ".fetch_detail", side_effect=detail_for))

    def collect(self, **limits):
        summary = collect_welfare("run", self.root, KEY, **limits)
        directory = self.root / "run"
        return summary, json.loads((directory / "batch.json").read_bytes()), directory

    def test_complete_collection_keeps_raw_pages_details_and_records_without_key(self):
        pages = [list_xml(1, 3, "WLF00000915", "WLF00000001", page_size=2), list_xml(2, 3, "WLF00000002", page_size=2)]
        self.listing.side_effect = pages
        summary, receipt, directory = self.collect()
        self.assertEqual(summary, {"batch_id": "run", "status": "complete", "discovery_status": "complete",
                                   "selected": 3, "parsed": 3})
        self.assertEqual([call.args for call in self.listing.call_args_list], [(1, 2, KEY), (2, 2, KEY)])
        self.assertEqual((directory / "list-2.xml").read_bytes(), pages[1])
        self.assertEqual(receipt["pages"][0]["source_url"], list_source_url(1, 2))
        self.assertEqual(receipt["pages"][0]["serv_ids"], ["WLF00000915", "WLF00000001"])
        self.assertEqual(receipt["pages"][1]["sha256"], hashlib.sha256(pages[1]).hexdigest())
        item = receipt["items"][2]
        self.assertEqual((item["servId"], item["list_page"], item["status"], item["source_url"]),
                         ("WLF00000002", 2, "parsed", detail_source_url("WLF00000002")))
        parsed = json.loads((directory / "parsed-WLF00000915.json").read_bytes())
        self.assertEqual(parsed["list_sha256"], hashlib.sha256(pages[0]).hexdigest())
        self.assertEqual(parsed["record"]["list"]["fields"]["sprtCycNm"], "월")
        self.assertEqual(parsed["record"]["detail"]["fields"]["enfcEndYmd"], "99991231")
        self.assertEqual((receipt["region"], receipt["page_size"]), ({"ctpvNm": "경기도", "sggNm": "안성시"}, 2))
        for path in directory.iterdir():
            content = path.read_bytes()
            self.assertNotIn(KEY.encode(), content)
            self.assertNotIn(ENCODED_KEY.encode(), content)
            self.assertNotIn(b"serviceKey", content)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_detail_failures_keep_raw_reason_and_continue(self):
        self.listing.return_value = list_xml(1, 2, "WLF00000001", "WLF00000002", page_size=2)
        self.detail.side_effect = [detail_xml("WLF00000009"), detail_xml("WLF00000002")]
        summary, receipt, directory = self.collect()
        self.assertEqual((summary["status"], summary["parsed"]), ("partial", 1))
        failed = receipt["items"][0]
        self.assertEqual(failed["status"], "parse_failed")
        self.assertIn("서비스 ID", failed["error"])
        self.assertEqual((directory / "detail-WLF00000001.xml").read_bytes(), detail_xml("WLF00000009"))
        self.assertFalse((directory / "parsed-WLF00000001.json").exists())

    def test_rate_limit_stops_remaining_requests(self):
        self.listing.return_value = list_xml(1, 2, "WLF00000001", "WLF00000002", page_size=2)
        self.detail.side_effect = SourceHTTPError(429)
        _, receipt, _ = self.collect()
        self.assertEqual([item["status"] for item in receipt["items"]], ["fetch_failed", "not_attempted"])
        self.assertEqual((receipt["stop_http_status"], self.detail.call_count), (429, 1))
        self.assertIn("429", receipt["stop_reason"])

    def test_service_error_in_http_200_stops_remaining_requests(self):
        gateway = (b"<OpenAPI_ServiceResponse><cmmMsgHeader><returnAuthMsg>LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR"
                   b"</returnAuthMsg><returnReasonCode>22</returnReasonCode></cmmMsgHeader></OpenAPI_ServiceResponse>")
        ids = ("WLF00000001", "WLF00000002", "WLF00000003")
        for index, error in enumerate((gateway, detail_xml("WLF00000002", code="22"))):
            self.listing.side_effect = [list_xml(1, 3, *ids[:2], page_size=2), list_xml(2, 3, ids[2], page_size=2)]
            self.detail.reset_mock()
            self.detail.side_effect = [detail_xml("WLF00000001"), error, detail_xml("WLF00000003")]
            with self.subTest(index=index):
                summary = collect_welfare(f"service-{index}", self.root, KEY)
                directory = self.root / f"service-{index}"
                receipt = json.loads((directory / "batch.json").read_bytes())
                self.assertEqual([item["status"] for item in receipt["items"]],
                                 ["parsed", "parse_failed", "not_attempted"])
                self.assertEqual((self.detail.call_count, summary["status"], receipt["stop_http_status"]),
                                 (2, "partial", None))
                self.assertEqual(receipt["stop_reason"], receipt["items"][1]["error"])
                self.assertEqual((directory / "detail-WLF00000002.xml").read_bytes(), error)

    def test_listing_service_error_skips_details_of_earlier_pages(self):
        self.listing.side_effect = [list_xml(1, 3, "WLF00000001", "WLF00000002", page_size=2),
                                    list_xml(2, 3, "WLF00000003", page_size=2, code="22")]
        summary, receipt, _ = self.collect()
        self.detail.assert_not_called()
        self.assertEqual([item["status"] for item in receipt["items"]], ["not_attempted", "not_attempted"])
        self.assertEqual((summary["discovery_status"], receipt["pages"][1]["status"]), ("failed", "parse_failed"))
        self.assertIn("22", receipt["stop_reason"])

    def test_listing_errors_keep_raw_and_reason(self):
        cases = (
            [list_xml(1, 1, code="30")],
            [list_xml(1, 3, "WLF00000001", "WLF00000002", page_size=2), list_xml(2, 4, "WLF00000003", "WLF00000004",
                                                                                 page_size=2)],
            [list_xml(1, 3, "WLF00000001", "WLF00000002", page_size=2), list_xml(2, 3, "WLF00000002", page_size=2)],
            [b'<!DOCTYPE x [<!ENTITY a "b">]><response>&a;</response>'],
        )
        for index, pages in enumerate(cases):
            self.listing.reset_mock()
            self.listing.side_effect = pages
            with self.subTest(index=index):
                summary = collect_welfare(f"run-{index}", self.root, KEY)
                directory = self.root / f"run-{index}"
                receipt = json.loads((directory / "batch.json").read_bytes())
                last = receipt["pages"][-1]
                self.assertEqual((summary["status"], summary["discovery_status"], last["status"]),
                                 ("partial", "failed", "parse_failed"))
                self.assertEqual((directory / f"list-{last['page']}.xml").read_bytes(), pages[-1])
                self.assertEqual(summary["selected"], 0 if len(pages) == 1 else 2)

    def test_listing_stop_status_skips_details(self):
        self.listing.side_effect = SourceHTTPError(401)
        summary, receipt, directory = self.collect()
        self.assertEqual((summary["selected"], receipt["stop_http_status"], receipt["pages"][0]["status"]),
                         (0, 401, "fetch_failed"))
        self.assertFalse((directory / "list-1.xml").exists())
        self.detail.assert_not_called()

    def test_page_and_item_caps_report_partial(self):
        self.listing.side_effect = [list_xml(1, 4, "WLF00000001", "WLF00000002", page_size=2)]
        summary, _, _ = self.collect(max_pages=1)
        self.assertEqual((summary["status"], summary["discovery_status"], summary["selected"]),
                         ("partial", "page_limit", 2))
        self.listing.side_effect = [list_xml(1, 4, "WLF00000001", "WLF00000002", page_size=2)]
        summary = collect_welfare("capped", self.root, KEY, max_items=1)
        self.assertEqual((summary["discovery_status"], summary["selected"]), ("item_limit", 1))

    def test_empty_result_is_complete(self):
        self.listing.return_value = list_xml(1, 0, page_size=2)
        summary, receipt, _ = self.collect()
        self.assertEqual((summary["status"], receipt["items"]), ("complete", []))

    def test_invalid_settings_are_rejected_before_requests(self):
        for key, limits in (("", {}), ("key&x=1", {}), (KEY, {"max_pages": 0}), (KEY, {"max_items": 501}),
                            (KEY, {"max_pages": True})):
            with self.subTest(key=key, limits=limits), self.assertRaises(ValueError):
                collect_welfare("bad", self.root, key, **limits)
        self.assertFalse((self.root / "bad").exists())
        self.listing.assert_not_called()

    def test_existing_name_is_not_overwritten(self):
        self.listing.return_value = list_xml(1, 0, page_size=2)
        self.collect()
        with self.assertRaises(ValueError):
            collect_welfare("run", self.root, KEY)

    def test_cli_reads_key_from_environment_and_maps_exit_codes(self):
        self.listing.return_value = list_xml(1, 0, page_size=2)
        with (patch(_BATCH + ".WELFARE_ROOT", self.root), patch.dict(os.environ, {"DATA_GO_KR_SERVICE_KEY": KEY}),
              patch("sys.argv", ["welfare_batch", "--name", "cli"]), contextlib.redirect_stdout(io.StringIO()) as out):
            self.assertEqual(main(), 0)
        self.assertEqual(json.loads(out.getvalue())["status"], "complete")
        self.listing.side_effect = SourceHTTPError(503)
        with (patch(_BATCH + ".WELFARE_ROOT", self.root), patch.dict(os.environ, {"DATA_GO_KR_SERVICE_KEY": KEY}),
              patch("sys.argv", ["welfare_batch", "--name", "cli-failed"]), contextlib.redirect_stdout(io.StringIO())):
            self.assertEqual(main(), 2)
        with (patch(_BATCH + ".WELFARE_ROOT", self.root), patch.dict(os.environ, {}, clear=True),
              patch("sys.argv", ["welfare_batch", "--name", "no-key"]),
              contextlib.redirect_stderr(io.StringIO()) as error):
            self.assertEqual(main(), 1)
        self.assertIn("DATA_GO_KR_SERVICE_KEY", error.getvalue())
        self.assertFalse((self.root / "no-key").exists())


class WelfareTransportBatchTest(unittest.TestCase):
    """HTTP 계층까지 대체해 인증 키를 되돌려준 응답이 디스크에 남지 않는지 확인한다."""

    def test_key_echo_is_not_written(self):
        root = Path(self.enterContext(TemporaryDirectory())).resolve() / WELFARE_SECTION
        self.enterContext(patch(_BATCH + ".sleep"))
        connect = self.enterContext(patch("processing.collection.official_web.HTTPSConnection"))
        response = connect.return_value.getresponse.return_value.__enter__.return_value
        response.status = 200
        response.getheader.return_value = None
        # UTF-16·UTF-32 본문은 UTF-8로 풀면 글자 사이에 NUL이 끼어 키 비교를 빠져나갈 수 있었다.
        # EBCDIC(cp500) 본문은 NUL이 없지만 UTF-8로 읽히지 않아 키 비교를 빠져나갈 수 있었다.
        for name, codec, echoed in (("echo", "utf-8", ENCODED_KEY), ("utf16", "utf-16-le", ENCODED_KEY),
                                    ("utf32", "utf-32-le", KEY), ("cp500", "cp500", KEY)):
            response.read.return_value = f"<response><resultMessage>{echoed}</resultMessage></response>".encode(codec)
            with self.subTest(codec=codec):
                summary = collect_welfare(name, root, KEY)
                directory = root / name
                self.assertEqual(sorted(path.name for path in directory.iterdir()), ["batch.json"])
                receipt = (directory / "batch.json").read_bytes()
                self.assertIn("인증 키".encode(), receipt)
                self.assertNotIn(KEY.encode(), receipt)
                self.assertNotIn(ENCODED_KEY.encode(), receipt)
                self.assertNotIn(echoed.encode(codec), receipt)
                self.assertEqual(summary["status"], "partial")


class WelfareD03Test(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(TemporaryDirectory())).resolve() / "private"
        self.root.mkdir(mode=0o700)
        self.directory = self.root / WELFARE_SECTION / "trial"
        with (patch(_BATCH + ".sleep"), patch(_BATCH + ".PAGE_SIZE", 2),
              patch(_BATCH + ".fetch_list", side_effect=[
                  list_xml(1, 3, "WLF00000915", "WLF00000001", page_size=2), list_xml(2, 3, "WLF00000002", page_size=2)]),
              patch(_BATCH + ".fetch_detail", side_effect=[detail_xml("WLF00000915"), detail_xml("WLF00000009"),
                                                           detail_xml("WLF00000002")])):
            collect_welfare("trial", self.root / WELFARE_SECTION, KEY)
        self.receipt = json.loads((self.directory / "batch.json").read_bytes())

    def rewrite(self, name, content):
        path = self.directory / name
        path.unlink()
        path.write_bytes(content)
        os.chmod(path, 0o600)

    def test_parsed_detail_returns_relative_raw_reference(self):
        self.assertEqual(capture_assets(self.root, "welfare", "trial", {"WLF00000915"}), {"WLF00000915": {
            "raw_asset_path": f"{WELFARE_SECTION}/trial/detail-WLF00000915.xml",
            "raw_sha256": hashlib.sha256(detail_xml("WLF00000915")).hexdigest(),
            "official_url": service_page_url("WLF00000915"),
            "collected_at": self.receipt["items"][0]["fetched_at"],
            "collection_method": "data-go-kr-welfare-api",
        }})
        self.assertEqual(set(capture_assets(self.root, "welfare", "trial", {"WLF00000915", "WLF00000002"})),
                         {"WLF00000915", "WLF00000002"})

    def test_rejects_unparsed_unknown_or_other_key_forms(self):
        for keys in ({"WLF00000001"}, {"WLF00000003"}, {"portal"}, {"1"}, {"WLF00000915", "portal"}, set()):
            with self.subTest(keys=keys), self.assertRaises(ValueError):
                capture_assets(self.root, "welfare", "trial", keys)
        with self.assertRaises(ValueError):
            capture_assets(self.root, "board", "trial", {"WLF00000915"})

    def test_rejects_changed_detail_or_list_raw(self):
        for name, old, new in (("detail-WLF00000915.xml", "합성 지원대상", "다른 지원대상"),
                               ("list-1.xml", "<sprtCycNm>월</sprtCycNm>", "<sprtCycNm>년</sprtCycNm>")):
            original = (self.directory / name).read_bytes()
            self.rewrite(name, original.replace(old.encode(), new.encode()))
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "해시"):
                capture_assets(self.root, "welfare", "trial", {"WLF00000915"})
            self.rewrite(name, original)
        self.assertIn("WLF00000915", capture_assets(self.root, "welfare", "trial", {"WLF00000915"}))

    def test_rejects_changed_parsed_record_or_parser_version(self):
        path = "parsed-WLF00000915.json"
        parsed = json.loads((self.directory / path).read_bytes())
        changed = json.loads(json.dumps(parsed))
        changed["record"]["detail"]["fields"]["slctCritCn"] = "추정한 선정기준"
        self.rewrite(path, json.dumps(changed, ensure_ascii=False).encode())
        with self.assertRaisesRegex(ValueError, "파싱 결과"):
            capture_assets(self.root, "welfare", "trial", {"WLF00000915"})
        self.rewrite(path, json.dumps(dict(parsed, parser_version="welfare-api-parser-v0")).encode())
        with self.assertRaisesRegex(ValueError, "파서 버전"):
            capture_assets(self.root, "welfare", "trial", {"WLF00000915"})

    def test_rejects_changed_receipt(self):
        original = (self.directory / "batch.json").read_bytes()
        changes = (
            lambda r: r.update(schema_version="other"), lambda r: r.update(batch_id="other"),
            lambda r: r.update(status="complete"), lambda r: r.update(parsed=3),
            lambda r: r.update(region={"ctpvNm": "경기도", "sggNm": "평택시"}), lambda r: r.update(page_size=3),
            lambda r: r["items"][0].update(list_page=2), lambda r: r["items"][0].update(sha256="A" * 64),
            lambda r: r["items"][0].update(fetched_at="2026-11-27 08:00:00"),
            lambda r: r["items"][0].update(source_url=detail_source_url("WLF00000001")),
            lambda r: r["items"][0].update(file="detail-WLF00000001.xml"),
            lambda r: r["pages"][0].update(source_url=list_source_url(1, 100)),
            lambda r: r["pages"][0].update(status="parse_failed"),
            lambda r: r["items"].append(dict(r["items"][0])),
            lambda r: r.update(items=r["items"][:1], selected=True, parsed=True),
        )
        for index, change in enumerate(changes):
            self.rewrite("batch.json", original)
            self.assertIn("WLF00000915", capture_assets(self.root, "welfare", "trial", {"WLF00000915"}))
            receipt = json.loads(original)
            change(receipt)
            self.rewrite("batch.json", json.dumps(receipt, ensure_ascii=False).encode())
            with self.subTest(index=index), self.assertRaises(ValueError):
                capture_assets(self.root, "welfare", "trial", {"WLF00000915"})

    def test_single_item_receipt_needs_integer_counts(self):
        receipt = dict(self.receipt, items=self.receipt["items"][:1], selected=1, parsed=1)
        self.rewrite("batch.json", json.dumps(receipt, ensure_ascii=False).encode())
        self.assertIn("WLF00000915", capture_assets(self.root, "welfare", "trial", {"WLF00000915"}))

    def test_rejects_readable_or_symlinked_raw(self):
        os.chmod(self.directory / "detail-WLF00000915.xml", 0o644)
        with self.assertRaises(ValueError):
            capture_assets(self.root, "welfare", "trial", {"WLF00000915"})
        os.chmod(self.directory / "detail-WLF00000915.xml", 0o600)
        raw = self.directory / "list-1.xml"
        copy = self.root / "copy.xml"
        copy.write_bytes(raw.read_bytes())
        os.chmod(copy, 0o600)
        raw.unlink()
        raw.symlink_to(copy)
        with self.assertRaises(ValueError):
            capture_assets(self.root, "welfare", "trial", {"WLF00000915"})

    def test_prepare_outputs_pending_d03_document(self):
        review = self.root / "welfare-review.json"
        review.write_text(json.dumps({
            "archive_kind": "welfare",
            "archive_name": "trial",
            "data_kind": "synthetic",
            "documents": [{
                "asset": "WLF00000915",
                "official_url": service_page_url("WLF00000915"),
                "document_id": "60000000-0000-4000-8000-000000000915",
                "document_version_id": "70000000-0000-4000-8000-000000000915",
                "version_no": 1,
                "publisher": "합성 기관",
                "title": "사람이 검토한 합성 서비스명",
                "published_date": None,
                "official_number": None,
                "collected_at": None,
                "cleaned_text": "지원대상과 신청방법을 사람이 확인한 합성 본문",
                "redaction_log": [],
            }],
        }, ensure_ascii=False), encoding="utf-8")
        self.assertEqual(prepare(review, "welfare-result", self.root),
                         {"preparation_id": "welfare-result", "documents": 1})
        output = json.loads((self.root / "collection-d03" / "welfare-result" / "source-import.json").read_bytes())
        document = output["documents"][0]
        self.assertEqual(document["raw_asset_path"], f"{WELFARE_SECTION}/trial/detail-WLF00000915.xml")
        self.assertEqual(document["collection_method"], "data-go-kr-welfare-api")
        self.assertEqual((document["use_review"], document["check_result"]), ("pending", "unchecked"))
        self.assertEqual(document["collected_at"], self.receipt["items"][0]["fetched_at"].replace("+00:00", "Z"))


if __name__ == "__main__":
    unittest.main()
