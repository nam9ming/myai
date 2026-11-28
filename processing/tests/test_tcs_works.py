import contextlib
import csv
import hashlib
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from processing.collection import tcs_works as tcs

# 합성 행. 공개 레퍼런스 예제와 같은 13열 배치이며 실제 신고 자료가 아니다.


def row(number=1, police="합성", road="합성로", control="", name="합성 공사", builder="합성건설", code="9999"):
    seq = f"{number:06d}"
    return [f"{code}-2026-{seq}", code, "2026", seq, police, "20261201", "20261231", "0900", "1800",
            road, control, name, builder]


def csv_bytes(*rows, encoding="utf-8"):
    buffer = io.StringIO(newline="")
    csv.writer(buffer, lineterminator="\r\n").writerows(rows)
    return buffer.getvalue().encode(encoding)


class DecodeTest(unittest.TestCase):
    def test_utf8_bom_and_cp949_are_detected(self):
        raw = csv_bytes(row(road="경기도 안성시 합성로"))
        self.assertEqual(tcs.decode_csv(raw)[1], "utf-8")
        self.assertEqual(tcs.decode_csv(b"\xef\xbb\xbf" + raw), tcs.decode_csv(raw))
        self.assertEqual(tcs.decode_csv(csv_bytes(row(road="경기도 안성시 합성로"), encoding="cp949")),
                         tcs.decode_csv(raw)[:1] + ("cp949",))
        self.assertEqual(tcs.decode_csv(b"a,b\r\n"), ("a,b\r\n", "utf-8"))

    def test_unknown_or_ambiguous_encodings_fail_closed(self):
        # '각각'의 UTF-8 바이트는 CP949로도 다른 글자로 읽힌다.
        cases = {"NUL": "가".encode("utf-16"), "UTF-8 또는 CP949": b"\xff\xfe\x80", "양쪽": "각각".encode()}
        for message, raw in cases.items():
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                tcs.decode_csv(raw)


class ParseTest(unittest.TestCase):
    def test_keeps_columns_verbatim_and_marks_layout_gaps(self):
        records, rejected = tcs.parse_tcs_csv(csv_bytes(row(road=' 합성로 1, "2"개소', control="")).decode())
        self.assertEqual(rejected, [])
        record = records[0]
        self.assertEqual(record["columns"][7:9], ["0900", "1800"])
        self.assertEqual(record["fields"]["constRoad"], ' 합성로 1, "2"개소')
        self.assertIsNone(record["fields"]["trafficControl"])
        self.assertEqual(record["unknown"], {"anouncePol": "not_in_layout", "trafficControl": "empty"})
        self.assertNotIn("0900", record["fields"].values())

    def test_rejects_rows_with_reasons_and_bad_files(self):
        shifted = row(2)
        shifted.insert(5, "")
        wrong_seq = row(3)
        wrong_seq[0] = "9999-2026-000004"
        bad_date = row(5)
        bad_date[5] = "2026-12-01"
        text = csv_bytes(row(1), row(1), shifted, wrong_seq, bad_date, ["seq", "poliCode"]).decode() + "\r\n"
        records, rejected = tcs.parse_tcs_csv(text)
        self.assertEqual(len(records), 1)
        expected = [(2, "같은 일련번호"), (3, "열 수가 14개"), (4, "일련번호(seq)가"), (5, "6번째 열의"), (6, "열 수가 2개")]
        self.assertEqual([r["line"] for r in rejected], [line for line, _ in expected])
        for entry, (_, reason) in zip(rejected, expected):
            self.assertTrue(entry["reason"].startswith(reason), entry["reason"])
        self.assertEqual(rejected[1]["columns"], shifted)
        with self.assertRaisesRegex(ValueError, "따옴표"):
            tcs.parse_tcs_csv('a,"b\r\n')

    def test_anseong_selection_uses_road_and_police_only(self):
        rows = [row(1, road="경기도 안성시 공도읍 합성로"), row(2, police="안성"), row(3, road="무주군 안성면 합성로"),
                row(4, name="안성 방면 합성 공사"), row(5, builder="안성건설"), row(6)]
        matched, review = tcs.select_records(tcs.parse_tcs_csv(csv_bytes(*rows).decode())[0])
        self.assertEqual([m["match"] for m in matched],
                         [{"constRoad": "경기도 안성시 공도읍 합성로"}, {"poliName": "안성"}])
        self.assertEqual([(r["record"]["line"], r["reason"], r["mentions"]) for r in review],
                         [(3, "mention", ["constRoad"]), (4, "other_mention", ["constName"])])


class ImportTest(unittest.TestCase):
    def setUp(self):
        self.temporary = Path(self.enterContext(TemporaryDirectory())).resolve()
        self.root = self.temporary / tcs.TCS_SECTION
        self.source = self.temporary / "operator.csv"

    def run_import(self, raw):
        self.source.write_bytes(raw)
        return tcs.import_tcs(self.source, "tcs-1", self.root)

    def test_import_and_reread(self):
        raw = csv_bytes(row(1, road="안성시 합성로"), row(2), encoding="cp949")
        summary = self.run_import(raw)
        self.assertEqual(summary, {"import_id": "tcs-1", "status": "complete", "records": 2, "rows": 1,
                                   "needs_review": 0, "rejected": 0})
        bundle = self.root / "tcs-1"
        self.assertEqual((bundle / "source.csv").read_bytes(), raw)
        selection, receipt = tcs.read_tcs_snapshot(self.temporary, "tcs-1")
        self.assertEqual(json.loads(selection)["encoding"], "cp949")
        self.assertEqual(receipt["selection"]["sha256"], hashlib.sha256(selection).hexdigest())
        (bundle / "anseong.json").chmod(0o600)
        (bundle / "anseong.json").write_bytes(selection.replace("안성시".encode(), "평택시".encode()))
        with self.assertRaisesRegex(ValueError, "다릅니다"):
            tcs.read_tcs_snapshot(self.temporary, "tcs-1")

    def test_partial_and_failed_imports_keep_raw_and_reason(self):
        self.assertEqual(self.run_import(csv_bytes(row(1), ["x"]))["status"], "partial")
        self.assertEqual(tcs.read_tcs_snapshot(self.temporary, "tcs-1")[1]["selection"]["rejected"], 1)
        self.source.write_bytes(b"\xff\xfe\x80")
        self.assertEqual(tcs.import_tcs(self.source, "tcs-2", self.root)["status"], "failed")
        receipt = json.loads((self.root / "tcs-2" / "tcs.json").read_text(encoding="utf-8"))
        self.assertIn("UTF-8 또는 CP949", receipt["error"])
        self.assertEqual((self.root / "tcs-2" / "source.csv").read_bytes(), b"\xff\xfe\x80")
        with self.assertRaisesRegex(ValueError, "보관 기록"):
            tcs.read_tcs_snapshot(self.temporary, "tcs-2")

    def test_cli_exit_codes(self):
        with patch("sys.argv", ["x", "--csv"]), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as caught:
                tcs.main()
        self.assertEqual(caught.exception.code, 1)
        self.source.write_bytes(csv_bytes(row(1)))
        with (patch("sys.argv", ["x", "--csv", str(self.source), "--name", "bad name"]),
              contextlib.redirect_stderr(io.StringIO()) as error):
            self.assertEqual(tcs.main(), 1)
        self.assertIn("TCS CSV 보관 실패", error.getvalue())
        with (patch("sys.argv", ["x", "--csv", str(self.source), "--name", "tcs-3"]),
              patch.object(tcs, "TCS_ROOT", self.root), contextlib.redirect_stdout(io.StringIO())):
            self.assertEqual(tcs.main(), 0)


if __name__ == "__main__":
    unittest.main()
