import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from processing.collection.gits_incidents import (
    GITS_SECTION, NO_BOUNDARY, RESPONSE_MAX_BYTES, collect_incidents, fetch_incidents, main, parse_incidents,
    read_incidents,
)
from processing.collection.official_web import SourceHTTPError

# 합성 값. 실제 인증 키와 실제 API 응답이 아니다. 구조는 명세의 응답결과 예시(소문자 태그)를 따른다.
KEY = "example/-_+=123"
ENCODED_KEY = "example%2F-_%2B%3D123"
_MODULE = "processing.collection.gits_incidents"


def item_xml(regseq="900000000001", place1="합성고속도로", place2="(합성방향) 가IC → 나IC", extra="", desc=None):
    desc = f"[합성] {place1} {place2}  1,2차로 통제,  낙하물\n" if desc is None else desc
    return ("<itemlist><routeid>\n</routeid><linkid>1000000001</linkid><spotid>\n</spotid>"
            f"<regseq>{regseq}</regseq><confirmdate>2026-11-28 10:35:00</confirmdate>"
            "<startdate>2026-11-28 10:35:00</startdate><estenddate>2026-11-28 11:05:00</estenddate>"
            "<enddate>\n</enddate><restricttype>1,2차로</restricttype>"
            f"<incidesc>{desc}</incidesc>"
            f"<inciplace1>{place1}</inciplace1><inciplace2>{place2}</inciplace2>"
            f"<coord_x>127.27</coord_x><coord_y>37.01</coord_y>{extra}</itemlist>")


def incidents_xml(*items, code="0", message="정상적으로 처리되었습니다.", count=None, common=" ",
                  root="serviceresult", body=None):
    items = items if items or body is not None else (item_xml(),)
    count = str(len(items)) if count is None else count
    body = f"<msgbody>{''.join(items)}</msgbody>" if body is None else body
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            f"<{root}><commsgheader>{common}</commsgheader><msgheader><headercd>{code}</headercd>"
            f"<headermsg>{message}</headermsg><itemcount>{count}</itemcount></msgheader>{body}</{root}>").encode()


class GitsParseTest(unittest.TestCase):
    def test_example_shape_keeps_text_verbatim_and_blank_values_as_null(self):
        record = parse_incidents(incidents_xml())
        self.assertEqual((record["result_code"], record["result_message"], record["item_count"]),
                         ("0", "정상적으로 처리되었습니다.", "1"))
        item = record["items"][0]
        self.assertEqual(item["fields"]["incidesc"], "[합성] 합성고속도로 (합성방향) 가IC → 나IC  1,2차로 통제,  낙하물\n")
        self.assertEqual((item["fields"]["startdate"], item["fields"]["estenddate"], item["fields"]["coord_x"]),
                         ("2026-11-28 10:35:00", "2026-11-28 11:05:00", "127.27"))
        self.assertEqual((item["fields"]["routeid"], item["fields"]["enddate"]), (None, None))
        self.assertEqual(item["unknown"], {"routeid": "empty", "spotid": "empty", "enddate": "empty"})
        self.assertEqual(item["undocumented"], {})

    def test_anseong_relevance_uses_place_text_only(self):
        cases = (("경부고속도로", "(서울방향) 안성IC → 합성IC", "location_text", ["inciplace2"]),
                 ("안성대로", "(합성방향) 가 → 나", "location_text", ["inciplace1"]),
                 ("경부고속도로", "(안성방향) 합성IC → 합성JC", "needs_review", []),
                 ("합성로", "(안성 방면) 가 → 나", "needs_review", []),
                 ("합성로", "(안성\u3000방향) 가 → 나", "needs_review", []),
                 ("합성로", "(안성\n방향) 가 → 나", "needs_review", []),
                 ("합성로", "(안성·평택방향) 가 → 나", "needs_review", []),
                 ("합성로", "(평택·안성 방면) 가 → 나", "needs_review", []),
                 ("합성로", "안성IC (평택방향) 가 → 나", "location_text", ["inciplace2"]),
                 # 좌표가 안성시청 부근이어도 공식 경계가 없어 판정하지 않는다.
                 ("합성로", "(합성방향) 가 → 나", "needs_review", []))
        for place1, place2, status, fields in cases:
            relevance = parse_incidents(incidents_xml(item_xml(place1=place1, place2=place2)))["items"][0]["anseong_relevance"]
            with self.subTest(place2=place2):
                self.assertEqual((relevance["status"], relevance["matched_fields"]), (status, fields))
                self.assertEqual(relevance.get("reason"), None if fields else NO_BOUNDARY)
        # 돌발 내용에만 안성이 있으면 위치로 보지 않는다.
        relevance = parse_incidents(incidents_xml(item_xml(desc="안성시 합성읍 우회")))["items"][0]["anseong_relevance"]
        self.assertEqual(relevance["status"], "needs_review")

    def test_no_result_code_is_an_empty_snapshot(self):
        record = parse_incidents(incidents_xml(code="4", message="결과가 존재하지 않습니다.", count="0", body=""))
        self.assertEqual((record["result_code"], record["items"]), ("4", []))
        no_count = incidents_xml(code="4", count="0", body="").replace(b"<itemcount>0</itemcount>", b"")
        self.assertEqual(parse_incidents(no_count)["item_count"], None)
        for raw in (incidents_xml(item_xml(), code="4"), incidents_xml(code="4", count="3", body="<msgbody/>"),
                    incidents_xml(code="4", count="", body=""), incidents_xml(code="4", count="00", body="")):
            with self.subTest(raw=raw), self.assertRaisesRegex(ValueError, "결과 없음"):
                parse_incidents(raw)

    def test_undocumented_leaf_is_kept_verbatim(self):
        item = parse_incidents(incidents_xml(item_xml(extra="<newfield> 원문 </newfield>")))["items"][0]
        self.assertEqual(item["undocumented"], {"newfield": " 원문 "})

    def test_format_changes_and_service_errors_are_rejected(self):
        cases = {
            "결과 코드가 정상이 아닙니다\\(6: 등록되지 않은 키 입니다.\\)": incidents_xml(code="6", message="등록되지 않은 키 입니다."),
            "최상위 요소가 예시와 다릅니다\\(ServiceResult\\)": incidents_xml(root="ServiceResult"),
            "itemcount": incidents_xml(item_xml(), count="2"),
            "itemcount\\)가": incidents_xml(item_xml(), count="x"),
            "commsgheader": incidents_xml(common="<returnreasoncode>30</returnreasoncode>"),
            "regseq": incidents_xml(item_xml(regseq=" ")),
            "반복": incidents_xml(item_xml(extra="<regseq>2</regseq>")),
            "하위 구조": incidents_xml(item_xml(extra="<coord><x>1</x></coord>")),
            "하위 요소 밖의 글자": incidents_xml(body="<msgbody>글자<itemlist><regseq>1</regseq></itemlist></msgbody>"),
            "예시와 다른 요소가 있습니다\\(item\\)": incidents_xml(body="<msgbody><item/></msgbody>"),
            "itemlist 요소에 예시에 없는 속성": incidents_xml(item_xml().replace("<itemlist>", '<itemlist status="cancelled">')),
            "regseq 요소에 예시에 없는 속성": incidents_xml(item_xml().replace("<regseq>", '<regseq deleted="Y">')),
            "headercd 요소에 예시에 없는 속성": incidents_xml().replace(b"<headercd>", b'<headercd real="6">'),
            "DOCTYPE": b'<!DOCTYPE x [<!ENTITY a "b">]><serviceresult/>',
            "UTF-8이 아닙니다": '<?xml version="1.0" encoding="EUC-KR"?><serviceresult/>'.encode(),
            "UTF-8 XML": "<serviceresult>합성</serviceresult>".encode("euc-kr"),
            "XML 형식": b"<serviceresult><msgheader></serviceresult>",
            "msgheader가 없습니다": b"<serviceresult><msgbody/></serviceresult>",
            "허용 크기": b" " * (RESPONSE_MAX_BYTES + 1),
        }
        for message, raw in cases.items():
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                parse_incidents(raw)


class GitsTransportTest(unittest.TestCase):
    def setUp(self):
        self.connect = self.enterContext(patch("processing.collection.official_web.HTTPSConnection"))
        self.connection = self.connect.return_value
        self.response = self.connection.getresponse.return_value.__enter__.return_value
        self.response.status = 200
        self.headers = {}
        self.response.getheader.side_effect = self.headers.get

    def reply(self, raw):
        self.response.read.return_value = raw
        self.headers["Content-Length"] = str(len(raw))

    def test_request_uses_fixed_host_path_and_only_the_key(self):
        self.reply(incidents_xml())
        self.assertEqual(fetch_incidents(KEY), incidents_xml())
        self.connect.assert_called_once_with("openapigits.gg.go.kr", timeout=15)
        method, target = self.connection.request.call_args.args
        parts = urlsplit(target)
        self.assertEqual((method, parts.path, parse_qs(parts.query)), ("GET", "/api/rest/getIncidentInfo",
                                                                       {"serviceKey": [KEY]}))
        self.assertIn(f"serviceKey={ENCODED_KEY}", target)
        self.assertEqual(self.connection.request.call_args.kwargs["headers"]["User-Agent"],
                         "yeogi-it/official-source-capture")
        self.response.read.assert_called_once_with(RESPONSE_MAX_BYTES + 1)

    def test_invalid_key_does_not_connect(self):
        for key in ("", "short", "key&x=evil", "키값은한글12345", None):
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "GITS 인증 키"):
                fetch_incidents(key)
        self.connect.assert_not_called()

    def test_http_errors_use_gits_label(self):
        self.response.status = 302
        with self.assertRaises(SourceHTTPError) as caught:
            fetch_incidents(KEY)
        self.assertEqual(str(caught.exception), "GITS 돌발 API HTTP 응답 오류(302).")

    def test_key_echo_is_rejected_with_gits_message(self):
        for echoed in (KEY, ENCODED_KEY, "example&#47;-_&#43;&#61;123", "exam<!-- 나눔 -->ple/-_+=123"):
            self.reply(incidents_xml(message=echoed))
            with self.subTest(echoed=echoed), self.assertRaises(ValueError) as caught:
                fetch_incidents(KEY)
            self.assertEqual(str(caught.exception), "GITS 돌발 API 응답에 인증 키가 포함되어 수집을 중단했습니다.")
        self.reply(incidents_xml().decode().encode("utf-16"))
        with self.assertRaisesRegex(ValueError, "GITS 돌발 API 응답에 NUL 바이트"):
            fetch_incidents(KEY)


class GitsCollectTest(unittest.TestCase):
    def setUp(self):
        self.private = Path(self.enterContext(TemporaryDirectory())).resolve()
        self.root = self.private / GITS_SECTION
        self.fetch = self.enterContext(patch(_MODULE + ".fetch_incidents"))

    def collect(self, raw):
        self.fetch.return_value = raw
        summary = collect_incidents("run", self.root, KEY)
        directory = self.root / "run"
        return summary, json.loads((directory / "capture.json").read_bytes()), directory

    def test_parsed_snapshot_keeps_raw_record_and_reads_back_without_key(self):
        raw = incidents_xml(item_xml("1", place2="(서울방향) 안성IC → 합성IC"), item_xml("2"))
        summary, receipt, directory = self.collect(raw)
        self.assertEqual(summary, {"capture_id": "run", "status": "parsed", "items": 2, "location_text": 1})
        self.fetch.assert_called_once_with(KEY)
        self.assertEqual((directory / "incidents.xml").read_bytes(), raw)
        self.assertEqual(receipt["response"]["sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(receipt["source_url"], "https://openapigits.gg.go.kr/api/rest/getIncidentInfo")
        stored, read_receipt = read_incidents(self.private, "run")
        self.assertEqual(read_receipt, receipt)
        self.assertEqual([item["fields"]["regseq"] for item in stored["record"]["items"]], ["1", "2"])
        for path in directory.iterdir():
            self.assertNotIn(KEY.encode(), path.read_bytes())
            self.assertNotIn(b"serviceKey", path.read_bytes())
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_parse_failure_keeps_raw_and_reason(self):
        raw = incidents_xml(code="8", message="요청 제한을 초과하였습니다.")
        summary, receipt, directory = self.collect(raw)
        self.assertEqual(summary["status"], "parse_failed")
        self.assertIn("8: 요청 제한을 초과하였습니다.", receipt["error"])
        self.assertEqual((directory / "incidents.xml").read_bytes(), raw)
        self.assertFalse((directory / "incidents.json").exists())
        with self.assertRaisesRegex(ValueError, "파싱이 완료된"):
            read_incidents(self.private, "run")

    def test_fetch_failure_records_reason_without_raw(self):
        self.fetch.side_effect = ValueError("GITS 돌발 API 응답에 인증 키가 포함되어 수집을 중단했습니다.")
        summary = collect_incidents("run", self.root, KEY)
        self.assertEqual(summary["status"], "fetch_failed")
        self.assertEqual(sorted(path.name for path in (self.root / "run").iterdir()), ["capture.json"])

    def test_missing_key_stops_before_request(self):
        with self.assertRaisesRegex(ValueError, "GITS_SERVICE_KEY"):
            collect_incidents("run", self.root, "")
        self.fetch.assert_not_called()

    def test_read_rejects_tampered_raw_record_and_old_parser(self):
        _, _, directory = self.collect(incidents_xml())
        parsed = directory / "incidents.json"
        stored = json.loads(parsed.read_bytes())
        for change, message in ((lambda data: data["record"]["items"][0]["fields"].update(incidesc="변경"), "파싱 결과"),
                                (lambda data: data.update(parser_version="gits-incident-parser-v0"), "다른 파서 버전")):
            data = json.loads(json.dumps(stored))
            change(data)
            parsed.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                read_incidents(self.private, "run")
        raw = directory / "incidents.xml"
        raw.write_bytes(raw.read_bytes() + b" ")
        with self.assertRaisesRegex(ValueError, "원본 해시"):
            read_incidents(self.private, "run")

    def test_main_exit_codes(self):
        with (patch(_MODULE + ".GITS_ROOT", self.root), patch.dict(os.environ, {"GITS_SERVICE_KEY": KEY}),
              contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as error):
            self.fetch.return_value = incidents_xml()
            with patch("sys.argv", ["gits_incidents", "--name", "ok"]):
                self.assertEqual(main(), 0)
            self.fetch.return_value = b"<oops/>"
            with patch("sys.argv", ["gits_incidents", "--name", "bad"]):
                self.assertEqual(main(), 2)
            with patch.dict(os.environ, {"GITS_SERVICE_KEY": ""}), patch("sys.argv", ["gits_incidents", "--name", "x"]):
                self.assertEqual(main(), 1)
        self.assertIn("GITS_SERVICE_KEY", error.getvalue())
        self.assertNotIn(KEY, error.getvalue())


if __name__ == "__main__":
    unittest.main()
