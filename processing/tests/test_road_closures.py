import contextlib
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from processing.collection import road_closures as rc

# 합성 값. 실제 인증 키와 실제 API 응답이 아니다. 목록 키 이름 `list`도 합성이다.
KEY = "synthetic+ex/key="
ENCODED_KEY = "synthetic%2Bex%2Fkey%3D"


def item(section="남안성IC~안성IC", name="합성 구간", **override):
    row = dict.fromkeys(rc.FIELDS, "")
    row.update(limtPlanDates="20261201", limtPlanSeq="1", routeCd="0010", useRotnm=section, icNm=name,
               cnstnStrtDates="20261201", cnstnStrtTimes="0900", blcCtnt=" 1차로 차단\n우회 안내 ")
    return {**row, **override}


def page(rows, *, page=1, total=None, code="SUCCESS", list_key="list", **override):
    body = {"code": code, "message": "합성 메시지", "count": str(len(rows) if total is None else total),
            "numOfRows": str(rc.PAGE_SIZE), "pageNo": str(page), "pageSize": "1", list_key: rows, **override}
    return json.dumps(body, ensure_ascii=False).encode()


class TransportTest(unittest.TestCase):
    def setUp(self):
        self.connect = self.enterContext(patch("processing.collection.official_web.HTTPSConnection"))
        self.response = self.connect.return_value.getresponse.return_value.__enter__.return_value
        self.response.status = 200
        self.response.getheader.side_effect = {}.get

    def test_fixed_host_path_and_query_without_key_in_record(self):
        self.response.read.return_value = page([])
        self.assertEqual(rc.fetch_page("0010", 2, KEY), page([]))
        self.assertEqual(self.connect.call_args.args[0], "data.ex.co.kr")
        method, target = self.connect.return_value.request.call_args.args
        parts = urlsplit(target)
        self.assertEqual((method, parts.path), ("GET", "/openapi/safeDriving/construction"))
        self.assertEqual(parse_qs(parts.query), {"key": [KEY], "type": ["json"], "routeCd": ["0010"],
                                                 "numOfRows": ["100"], "pageNo": ["2"]})
        self.assertNotIn("key", rc.source_url("0010", 2))

    def test_invalid_inputs_do_not_connect(self):
        for route, number, key in (("10", 1, KEY), ("００１０", 1, KEY), ("0010", 0, KEY), ("0010", 1, "short")):
            with self.subTest(route=route, page=number, key=key), self.assertRaises(ValueError):
                rc.fetch_page(route, number, key)
        self.connect.assert_not_called()

    def test_key_echo_is_rejected(self):
        for body in (KEY, ENCODED_KEY, KEY.replace("/", "\\/"), "synthetic\\u002Bex/key=", "synthetic ex/key=",
                     "synthetic&#43;ex&#47;key=", ENCODED_KEY.replace("%", "%25")):
            with self.subTest(body=body):
                self.response.read.return_value = ('{"message":"' + body + '"}').encode()
                with self.assertRaisesRegex(ValueError, "인증 키"):
                    rc.fetch_page("0010", 1, KEY)
        for raw in ("{}".encode("utf-16"), b"\xff{}"):
            self.response.read.return_value = raw
            with self.subTest(raw=raw), self.assertRaisesRegex(ValueError, "인증 키 포함 여부"):
                rc.fetch_page("0010", 1, KEY)


class ParseTest(unittest.TestCase):
    def test_keeps_values_verbatim_and_blank_as_null(self):
        total, key, items = rc.parse_page(page([item(extra="원문")]), "0010", 1)
        self.assertEqual((total, key), (1, "list"))
        fields = items[0]["fields"]
        self.assertEqual(fields["blcCtnt"], " 1차로 차단\n우회 안내 ")
        self.assertIsNone(fields["cnstnEndDates"])
        self.assertEqual(items[0]["unknown"]["cnstnEndDates"], "empty")
        self.assertEqual(items[0]["undocumented"], {"extra": "원문"})
        row = item()
        del row["hveqUseYn"]
        self.assertEqual(rc.parse_page(page([row]), "0010", 1)[2][0]["unknown"]["hveqUseYn"], "missing")

    def test_rejects_error_codes_and_changed_structure(self):
        rows = [item()]
        cases = {
            "결과 코드": (page(rows, code="ERROR"), page(rows, code=None)),
            "구조": (page(rows, other=[]), page(rows, list_key="message"), page(rows, list_key="data", list=1)),
            "페이지": (page(rows, page=2), page(rows, numOfRows="10")),
            "항목 수": (page(rows, total=2), page([], total=1)),
            "형식": (page(rows, count="1.0"), page([item(totCrgwCnt=2.5)]), page([item(blcForm=["a"])]),
                   page([item(hveqUseYn=True)])),
            "노선코드": (page([item(routeCd="10")]), page([item(routeCd=None)])),
            "JSON": (b"<html></html>", b"\xef\xbb\xbf{}", b'{"code":"SUCCESS","code":"SUCCESS"}', b"[]"),
        }
        for message, raws in cases.items():
            for raw in raws:
                with self.subTest(raw=raw), self.assertRaisesRegex(ValueError, message):
                    rc.parse_page(raw, "0010", 1)

    def test_selects_only_explicit_section_text(self):
        # 3.2 뒤에 생긴 문자(Garay, 3.14의 casefold가 옛 글자로 바꾸는 U+A7CB)도 파이썬 판과 관계없이 검토로 간다.
        # 반각 채움·반각 'ㅡ'·첫가끝 채움·첫가끝 'ㅡ'·NFD '수원'·호환 채움은 자모뿐이라 자리표시다.
        names = ("-", "없음", "\U00010D50", "\ua7cb", "ㅡ", "\uffa0", "\uffda", "\u115f\u1160", "\u1173",
                 "\u1109\u116e\u110b\u116f\u11ab", " \u3164 ")
        rows = [item(), item(section="서울TG~수원IC", name=""), item(section="", name=""),
                item(section="안성면 부근", name="합성"), item(section="합성", name="합성", cnstnCtnt="북안성 방면 공사"),
                item(section="", name="", mtnofKorNm="안성지사"), *[item(section="경부선", name=n) for n in names]]
        matched, review = [], []
        rc.select_items(3, rc.parse_page(page(rows), "0010", 1)[2], matched, review)
        self.assertEqual([(m["position"], m["match"]) for m in matched], [(1, {"useRotnm": "남안성IC~안성IC"})])
        self.assertEqual([(r["position"], r["reason"], r["mentions"]) for r in review],
                         [(2, "blank_section", []), (3, "blank_section", []), (4, "mention", ["useRotnm"]),
                          (5, "other_mention", ["cnstnCtnt"]), (6, "blank_section", ["mtnofKorNm"]),
                          *[(n, "blank_section", []) for n in range(7, 18)]])
        self.assertEqual(review[5]["record"]["fields"]["icNm"], "-")
        self.assertFalse(rc._no_location("\uffa0수원IC"))
        self.assertEqual(matched[0]["page"], 3)

    def test_markup_goes_to_review_before_matching(self):
        # 태그·문자 참조가 있으면 화면 글자를 알 수 없어 일치·불일치 모두 원문으로 정하지 않는다.
        rows = [item(section="안성IC&lt;"), item(section="경부선", name="&#xC548;성IC"),
                item(section="경부선", name="평택IC", cnstnCtnt="안<b></b>성 방면"), item(blcCtnt="1차로<br>차단")]
        matched, review = [], []
        rc.select_items(1, rc.parse_page(page(rows), "0010", 1)[2], matched, review)
        self.assertEqual(matched, [])
        self.assertEqual([(r["position"], r["reason"], r["mentions"]) for r in review],
                         [(1, "markup", ["useRotnm"]), (2, "markup", []), (3, "markup", []),
                          (4, "markup", ["useRotnm"])])

    def test_invisible_characters_go_to_review_before_matching(self):
        # 보이지 않는 문자는 일치를 만들거나(`안성`+ZWSP+`면`) 지운다(`안`+ZWSP+`성IC`). JSON `\u0000`도 같다.
        chars = "\x00\x08\x0b\x0c\x0e\x1f\x7f\x9f\u00ad\u034f\u061c\u17b4\u17b5\u180b\u180f\u200b\u200f\u202a\u202e" \
                "\u2060\u206f\ufe00\ufe0f\ufeff\U0001bca0\U0001bca3\U0001d173\U0001d17a\U000e0000\U000e0fff"
        rows = [item(section="무주 안성\u200b면 부근"), item(section="안성\ufe0f면"),
                *[item(section="경부선", name=f"안{c}성IC") for c in chars], item(section="경부선", name="\uffa0수원IC"),
                item(section="경부선", name="평택IC", cnstnCtnt="안\u00ad성 방면"),
                # 채움 문자 앞 제어 문자도 빈 값이 아니라 invisible이다.
                item(section="경부선", name="\x1c\u3164"), item(section="\x0b\u3164", name="평택IC"),
                # str.strip이 지우는 제어 문자만 있어도 빈 값이 아니다.
                item(section="경부선", name="\x1c"), item(section="경부선", name="\x85 "), item(section="\x0b", name="평택IC"),
                item(section="경부선", name="평택IC", blcCtnt="\x0b"),
                item(blcCtnt="1차로\t차단\r\n")]
        matched, review = [], []
        rc.select_items(1, rc.parse_page(page(rows), "0010", 1)[2], matched, review)
        self.assertEqual([m["position"] for m in matched], [len(rows)])
        self.assertEqual([(r["position"], r["reason"]) for r in review], [(n, "invisible") for n in range(1, len(rows))])
        self.assertEqual([r["mentions"] for r in review[:3]], [["useRotnm"], ["useRotnm"], []])


class CollectTest(unittest.TestCase):
    def setUp(self):
        self.temporary = self.enterContext(TemporaryDirectory())
        self.root = Path(self.temporary).resolve() / rc.CLOSURE_SECTION
        self.enterContext(patch.object(rc, "sleep"))

    def collect(self, *responses, name="closures-1"):
        with patch.object(rc, "fetch_page", side_effect=list(responses)) as fetch:
            result = rc.collect_road_closures("0010", name, self.root, KEY)
        return result, fetch

    def test_collects_pages_and_rereads_archive(self):
        first = [item(limtPlanSeq=str(n)) for n in range(rc.PAGE_SIZE)]
        result, fetch = self.collect(page(first, total=101), page([item(section="합성")], page=2, total=101))
        self.assertEqual(result, {"snapshot_id": "closures-1", "status": "complete", "pages": 2, "rows": 101})
        self.assertEqual([call.args for call in fetch.call_args_list], [("0010", 1, KEY), ("0010", 2, KEY)])
        bundle = self.root / "closures-1"
        receipt = (bundle / "closures.json").read_text(encoding="utf-8")
        self.assertNotIn(KEY, receipt)
        self.assertNotIn(ENCODED_KEY, receipt)
        selection, record = rc.read_road_closure_snapshot(self.root.parent, "closures-1")
        document = json.loads(selection)
        self.assertEqual((len(document["rows"]), len(document["needs_review"])), (100, 0))
        self.assertEqual((record["list_key"], record["selection"]["rows"]), ("list", 100))
        (bundle / "page-2.json").chmod(0o600)
        (bundle / "page-2.json").write_bytes(page([item()], page=2, total=101))
        with self.assertRaisesRegex(ValueError, "해시"):
            rc.read_road_closure_snapshot(self.root.parent, "closures-1")

    def test_failure_keeps_raw_and_reason(self):
        raw = page([item()], code="LIMIT")
        result, _ = self.collect(raw)
        self.assertEqual(result["status"], "failed")
        bundle = self.root / "closures-1"
        self.assertEqual((bundle / "page-1.json").read_bytes(), raw)
        self.assertIn("LIMIT", json.loads((bundle / "closures.json").read_text(encoding="utf-8"))["error"])
        self.assertFalse((bundle / "anseong.json").exists())
        with self.assertRaisesRegex(ValueError, "완료된"):
            rc.read_road_closure_snapshot(self.root.parent, "closures-1")

    def test_repeated_rows_and_zero_count_fail_closed(self):
        first = [item(limtPlanSeq=str(n)) for n in range(rc.PAGE_SIZE)]
        cases = {"앞 페이지": (page(first, total=101), page([first[0]], page=2, total=101)),
                 "0건": (page([]),)}
        for message, responses in cases.items():
            with self.subTest(message=message):
                result, _ = self.collect(*responses, name=message.encode().hex())
                bundle = self.root / message.encode().hex()
                self.assertEqual((result["status"], result["pages"]), ("failed", len(responses)))
                self.assertIn(message, json.loads((bundle / "closures.json").read_text(encoding="utf-8"))["error"])
                self.assertFalse((bundle / "anseong.json").exists())

    def test_missing_key_and_cli_exit_codes(self):
        with self.assertRaisesRegex(ValueError, rc.SERVICE_KEY_ENV):
            rc.collect_road_closures("0010", "closures-1", self.root, "")
        self.assertFalse(self.root.exists())
        for status, code in (("complete", 0), ("failed", 2)):
            summary = {"snapshot_id": "x", "status": status, "pages": 1, "rows": 0}
            with (self.subTest(status=status), patch("sys.argv", ["x", "--route-cd", "0010", "--name", "x"]),
                  patch.object(rc, "collect_road_closures", return_value=summary),
                  contextlib.redirect_stdout(io.StringIO())):
                self.assertEqual(rc.main(), code)


if __name__ == "__main__":
    unittest.main()
