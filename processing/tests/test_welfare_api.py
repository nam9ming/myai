import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, quote, urlsplit

from processing.collection.official_web import SourceHTTPError
from processing.collection.welfare_api import (
    RESPONSE_MAX_BYTES, WelfareResultError, detail_source_url, fetch_detail, fetch_list, list_source_url,
    parse_detail, parse_list, service_page_url,
)

# 합성 값. 실제 인증 키와 실제 API 응답이 아니다.
KEY = "example/-_+=123"
ENCODED_KEY = "example%2F-_%2B%3D123"
_ANSEONG = "<ctpvNm>경기도</ctpvNm><sggNm>안성시</sggNm>"


def service_xml(serv_id, extra=""):
    return (f"<servList><servId>{serv_id}</servId><servNm>합성 서비스 {serv_id}</servNm>{_ANSEONG}"
            f"<servDtlLink>https://www.bokjiro.go.kr/ssis-tbu/twataa/wlfareInfo/moveTWAT52011M.do?"
            f"wlfareInfoId={serv_id}</servDtlLink><sprtCycNm>월</sprtCycNm>{extra}</servList>")


def list_xml(page, total, *ids, page_size=100, root="response", code="0", body=None):
    items = body if body is not None else "".join(service_xml(item) for item in ids)
    return (f'<?xml version="1.0" encoding="UTF-8"?><{root}><resultCode>{code}</resultCode>'
            f"<resultMessage>SUCCESS</resultMessage><numOfRows>{page_size}</numOfRows><pageNo>{page}</pageNo>"
            f"<totalCount>{total}</totalCount>{items}</{root}>").encode()


def detail_xml(serv_id, extra="", root="response", code="0", region=_ANSEONG):
    return (f'<?xml version="1.0" encoding="UTF-8"?><{root}><resultCode>{code}</resultCode>'
            f"<resultMessage>SUCCESS</resultMessage><servId>{serv_id}</servId><servNm>합성 서비스 {serv_id}</servNm>"
            f"<enfcBgngYmd>20260101</enfcBgngYmd><enfcEndYmd>99991231</enfcEndYmd>{region}"
            "<sprtTrgtCn> 합성 지원대상 &amp; 조건\n둘째 줄 </sprtTrgtCn><slctCritCn><![CDATA[<합성> 선정기준]]></slctCritCn>"
            "<aplyMtdCn></aplyMtdCn>"
            "<inqplCtadrList><wlfareInfoDtlCd>010</wlfareInfoDtlCd><wlfareInfoReldNm>합성 부서</wlfareInfoReldNm>"
            "<wlfareInfoReldCn>000-0000-0000</wlfareInfoReldCn></inqplCtadrList>"
            "<inqplCtadrList><wlfareInfoReldNm>합성 센터</wlfareInfoReldNm></inqplCtadrList>"
            f"<baslawList><wlfareInfoDtlCd>030</wlfareInfoDtlCd><wlfareInfoReldNm>합성 조례</wlfareInfoReldNm></baslawList>"
            f"{extra}</{root}>").encode()


class WelfareTransportTest(unittest.TestCase):
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

    def request(self):
        method, target = self.connection.request.call_args.args
        parts = urlsplit(target)
        return method, parts.path, parse_qs(parts.query)

    def test_list_and_detail_use_fixed_host_paths_and_region(self):
        self.reply(b"<response/>")
        self.assertEqual(fetch_list(2, 50, KEY), b"<response/>")
        self.connect.assert_called_once_with("apis.data.go.kr", timeout=15)
        self.assertEqual(self.request(), ("GET", "/B554287/LocalGovernmentWelfareInformations/LcgvWelfarelist", {
            "pageNo": ["2"], "numOfRows": ["50"], "ctpvNm": ["경기도"], "sggNm": ["안성시"], "arrgOrd": ["001"],
            "serviceKey": [KEY],
        }))
        self.assertIn(f"serviceKey={ENCODED_KEY}", self.connection.request.call_args.args[1])
        self.response.read.assert_called_once_with(RESPONSE_MAX_BYTES + 1)
        fetch_detail("WLF00000915", KEY)
        self.assertEqual(self.request(), ("GET", "/B554287/LocalGovernmentWelfareInformations/LcgvWelfaredetailed",
                                          {"servId": ["WLF00000915"], "serviceKey": [KEY]}))

    def test_recorded_urls_do_not_contain_key(self):
        for url in (list_source_url(1, 100), detail_source_url("WLF00000915")):
            self.assertNotIn("serviceKey", url)
            self.assertTrue(url.startswith("https://apis.data.go.kr/B554287/LocalGovernmentWelfareInformations/"))

    def test_invalid_inputs_do_not_connect(self):
        for call in (lambda: fetch_list(0, 10, KEY), lambda: fetch_list(1, 501, KEY), lambda: fetch_list(True, 1, KEY),
                     lambda: fetch_list(1, 10, ""), lambda: fetch_list(1, 10, "key&x=evil"),
                     lambda: fetch_list(1, 10, ENCODED_KEY), lambda: fetch_detail("WLF0000091", KEY),
                     lambda: fetch_detail("123", KEY), lambda: fetch_detail("WLF00000915&x=1", KEY)):
            with self.assertRaises(ValueError):
                call()
        self.connect.assert_not_called()

    def test_http_errors_and_redirects_are_not_followed(self):
        self.headers["Location"] = f"https://example.invalid/?serviceKey={ENCODED_KEY}"
        for status in (301, 302, 401, 429, 500):
            self.response.status = status
            with self.subTest(status=status), self.assertRaises(SourceHTTPError) as caught:
                fetch_list(1, 10, KEY)
            self.assertEqual(caught.exception.status, status)
            self.assertTrue(str(caught.exception).startswith("복지 API"))
            self.assertNotIn(ENCODED_KEY, str(caught.exception))
        self.response.read.assert_not_called()

    def test_list_transport_errors_do_not_say_detail(self):
        for error, expected in ((TimeoutError(KEY), "복지 API 응답의 대기 시간을 초과했습니다."),
                                (OSError(KEY), "복지 API 응답을 받지 못했습니다.")):
            self.response.read.side_effect = error
            with self.subTest(error=type(error).__name__), self.assertRaises(ValueError) as caught:
                fetch_list(1, 100, KEY)
            self.assertEqual(str(caught.exception), expected)

    def test_key_echo_is_rejected_in_raw_url_json_and_xml_reference_forms(self):
        nested = KEY
        for _ in range(7):
            nested = quote(nested, safe="")
        for echoed in (KEY, ENCODED_KEY, "example&#47;-_&#43;&#61;123", "example&#x2F;-_&#x2B;=123",
                       "example%2f-_%2b%3d123", "%65xample/-_+=123", "example&amp;#47;-_+=123",
                       "example\\/-_\\u002B=123", "\\u0065xample/-_+=123", "example/-_ =123", nested):
            raw = f"<response><resultMessage>{echoed}</resultMessage></response>".encode()
            self.reply(raw)
            with self.subTest(echoed=echoed), self.assertRaisesRegex(WelfareResultError, "인증 키") as caught:
                fetch_list(1, 10, KEY)
            self.assertNotIn(KEY, str(caught.exception))
        # NUL 바이트가 있는 본문은 키가 %-인코딩됐거나 아예 없어도 확인 전에 거부한다.
        for codec in ("utf-16-le", "utf-16-be", "utf-16", "utf-32-le", "utf-32-be"):
            for echoed in (KEY, ENCODED_KEY, "SUCCESS"):
                self.reply(f"<response><resultMessage>{echoed}</resultMessage></response>".encode(codec))
                with (self.subTest(codec=codec, echoed=echoed),
                      self.assertRaisesRegex(WelfareResultError, "NUL 바이트.*인증 키") as caught):
                    fetch_list(1, 10, KEY)
                self.assertNotIn(KEY, str(caught.exception))
        # UTF-8이 아닌 본문(EBCDIC 키, EUC-KR 한글)은 UTF-8로 비교할 수 없어 확인 전에 거부한다.
        for codec, echoed in (("cp500", KEY), ("cp500", ENCODED_KEY), ("euc-kr", "합성")):
            self.reply(f"<response><resultMessage>{echoed}</resultMessage></response>".encode(codec))
            with (self.subTest(codec=codec, echoed=echoed),
                  self.assertRaisesRegex(WelfareResultError, "UTF-8이 아니어서 인증 키") as caught):
                fetch_list(1, 10, KEY)
            self.assertNotIn(KEY, str(caught.exception))
        self.reply(b"\xef\xbb\xbf" + f"<response>{KEY}</response>".encode())
        with self.assertRaisesRegex(WelfareResultError, "인증 키가 포함"):
            fetch_list(1, 10, KEY)

    def test_unrelated_escapes_still_pass_echo_check(self):
        raw = "<response><resultMessage>소득 50%이하 &amp;amp; https://a.example/?q=%2B\\/</resultMessage></response>"
        for body in (raw.encode(), b"\xef\xbb\xbf" + raw.encode()):
            self.reply(body)
            self.assertEqual(fetch_list(1, 10, KEY), body)


class WelfareUrlTest(unittest.TestCase):
    def test_service_page_is_public_bokjiro_url_without_key(self):
        self.assertEqual(service_page_url("WLF00000915"),
                         "https://www.bokjiro.go.kr/ssis-tbu/twataa/wlfareInfo/moveTWAT52011M.do?wlfareInfoId=WLF00000915")
        with self.assertRaises(ValueError):
            service_page_url("WLF00000915&serviceKey=x")


class WelfareListParseTest(unittest.TestCase):
    def test_parses_documented_fields_verbatim_and_keeps_unknown_null(self):
        extra = "<lifeNmArray> 청년, 중장년 </lifeNmArray><inqNum></inqNum><rprsCtadr>합성</rprsCtadr>"
        for root in ("response", "wantedList"):
            raw = list_xml(1, 2, body=service_xml("WLF00000915", extra) + service_xml("WLF00000001"), root=root)
            total, items = parse_list(raw, page=1, page_size=100)
            self.assertEqual(total, 2)
            first = items[0]
            self.assertEqual(first["fields"]["servId"], "WLF00000915")
            self.assertEqual(first["fields"]["lifeNmArray"], " 청년, 중장년 ")
            self.assertTrue(first["fields"]["servDtlLink"].endswith("wlfareInfoId=WLF00000915"))
            self.assertIsNone(first["fields"]["inqNum"])
            self.assertEqual(first["unknown"]["inqNum"], "empty")
            self.assertEqual(first["unknown"]["aplyMtdNm"], "missing")
            self.assertEqual(first["undocumented"], {"rprsCtadr": "합성"})

    def test_empty_total_is_valid(self):
        self.assertEqual(parse_list(list_xml(1, 0), page=1, page_size=100), (0, []))

    def test_rejects_unsafe_or_malformed_xml(self):
        bomb = ('<?xml version="1.0"?><!DOCTYPE response [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;&a;">]>'
                "<response><resultCode>&b;</resultCode></response>")
        external = '<!DOCTYPE response [<!ENTITY x SYSTEM "file:///etc/passwd">]><response>&x;</response>'
        for raw in (bomb.encode(), external.encode(), b"<!doctype response><response/>",
                    b'<response><!ENTITY x "y"></response>', b"<response><resultCode>0</response>",
                    b"not xml", b"", "<response>합성</response>".encode("euc-kr"),
                    '<?xml version="1.0" encoding="EUC-KR"?><response/>'.encode(), b"<response>\x00</response>",
                    b"<response>&undefined;</response>", b"x" * (RESPONSE_MAX_BYTES + 1)):
            with self.subTest(raw=raw[:60]), self.assertRaises(ValueError):
                parse_list(raw, page=1, page_size=100)

    def test_error_result_codes_and_gateway_envelopes_are_rejected(self):
        for code in ("30", "99", "", "SUCCESS", "000"):
            with self.subTest(code=code), self.assertRaises(WelfareResultError):
                parse_list(list_xml(1, 0, code=code), page=1, page_size=100)
        gateway = (b"<OpenAPI_ServiceResponse><cmmMsgHeader><returnReasonCode>22</returnReasonCode>"
                   b"</cmmMsgHeader></OpenAPI_ServiceResponse>")
        with self.assertRaisesRegex(WelfareResultError, "최상위"):
            parse_list(gateway, page=1, page_size=100)
        with self.assertRaisesRegex(WelfareResultError, "최상위"):
            parse_list(list_xml(1, 0, root="wantedDtl"), page=1, page_size=100)
        # 표준 API처럼 header 안에 결과 코드를 둔 오류 응답도 하위 구조 오류가 아니라 서비스 오류다.
        nested = b"<response><header><resultCode>22</resultCode></header></response>"
        for raw in (nested, b"not xml", "<response>합성</response>".encode("euc-kr")):
            with self.subTest(raw=raw), self.assertRaises(WelfareResultError):
                parse_list(raw, page=1, page_size=100)

    def test_rejects_paging_and_item_mismatches(self):
        cases = (
            (list_xml(2, 3, "WLF00000003", page_size=2), 1, 2),
            (list_xml(1, 3, "WLF00000003", page_size=3), 1, 2),
            (list_xml(1, 3, "WLF00000001", page_size=2), 1, 2),
            (list_xml(2, 3, "WLF00000003", "WLF00000004", page_size=2), 2, 2),
            (list_xml(1, 2, "WLF00000001", "WLF00000001", page_size=2), 1, 2),
            (list_xml(1, 1, "WLF0000001", page_size=2), 1, 2),
            (list_xml(1, -1, page_size=2), 1, 2),
            (list_xml(1, "", page_size=2), 1, 2),
        )
        for raw, page, size in cases:
            with self.subTest(raw=raw[-160:]), self.assertRaises(ValueError):
                parse_list(raw, page=page, page_size=size)

    def test_rejects_other_region_missing_name_or_changed_structure(self):
        other = service_xml("WLF00000001").replace("안성시", "평택시")
        missing = "<servList><servId>WLF00000001</servId><servNm>합성</servNm><ctpvNm>경기도</ctpvNm></servList>"
        nameless = service_xml("WLF00000001").replace("<servNm>합성 서비스 WLF00000001</servNm>", "<servNm> </servNm>")
        repeated = service_xml("WLF00000001", "<servNm>두 번째</servNm>")
        nested = service_xml("WLF00000001", "<lifeNmArray><code>004</code></lifeNmArray>")
        text = service_xml("WLF00000001").replace("<servList>", "<servList>묶음 글자")
        tail = service_xml("WLF00000001").replace("</servNm>", "</servNm>꼬리 글자")
        for body in (other, missing, nameless, repeated, nested, text, tail, service_xml("WLF00000001") + "목록 밖"):
            with self.subTest(body=body[-80:]), self.assertRaises(ValueError):
                parse_list(list_xml(1, 1, body=body), page=1, page_size=100)


class WelfareDetailParseTest(unittest.TestCase):
    def test_keeps_text_verbatim_and_related_lists(self):
        record = parse_detail(detail_xml("WLF00000915", "<newField>합성</newField>"), service_id="WLF00000915")
        fields = record["fields"]
        self.assertNotIn("resultCode", fields)
        self.assertEqual(fields["sprtTrgtCn"], " 합성 지원대상 & 조건\n둘째 줄 ")
        self.assertEqual(fields["slctCritCn"], "<합성> 선정기준")
        self.assertEqual((fields["enfcBgngYmd"], fields["enfcEndYmd"]), ("20260101", "99991231"))
        self.assertIsNone(fields["aplyMtdCn"])
        self.assertEqual(record["unknown"]["aplyMtdCn"], "empty")
        self.assertEqual(record["unknown"]["alwServCn"], "missing")
        self.assertEqual(record["undocumented"], {"newField": "합성"})
        contacts = record["related"]["inqplCtadrList"]
        self.assertEqual(contacts[0]["fields"], {"wlfareInfoDtlCd": "010", "wlfareInfoReldNm": "합성 부서",
                                                 "wlfareInfoReldCn": "000-0000-0000"})
        self.assertEqual(contacts[1]["unknown"], {"wlfareInfoDtlCd": "missing", "wlfareInfoReldCn": "missing"})
        self.assertEqual((record["related"]["inqplHmpgReldList"], record["related"]["basfrmList"]), ([], []))
        self.assertEqual(record["related"]["baslawList"][0]["fields"]["wlfareInfoReldNm"], "합성 조례")
        self.assertEqual(parse_detail(detail_xml("WLF00000915", root="wantedDtl"), service_id="WLF00000915"),
                         parse_detail(detail_xml("WLF00000915"), service_id="WLF00000915"))

    def test_region_is_optional_in_detail_but_must_match(self):
        record = parse_detail(detail_xml("WLF00000915", region=""), service_id="WLF00000915")
        self.assertEqual(record["unknown"]["sggNm"], "missing")
        with self.assertRaises(ValueError):
            parse_detail(detail_xml("WLF00000915", region="<sggNm>평택시</sggNm>"), service_id="WLF00000915")

    def test_rejects_wrong_identity_code_or_structure(self):
        cases = (
            (detail_xml("WLF00000001"), "WLF00000915"),
            (detail_xml("WLF00000915", code="10"), "WLF00000915"),
            (detail_xml("WLF00000915", root="wantedList"), "WLF00000915"),
            (detail_xml("WLF00000915", "<basfrmList><wlfareInfoDtlCd>010</wlfareInfoDtlCd></basfrmList>"),
             "WLF00000915"),
            (detail_xml("WLF00000915", "<applmetList><servSeCode>070</servSeCode></applmetList>"), "WLF00000915"),
            (detail_xml("WLF00000915", "<servId>WLF00000915</servId>"), "WLF00000915"),
            (detail_xml("WLF00000915").replace("<servNm>합성 서비스 WLF00000915</servNm>".encode(), b""),
             "WLF00000915"),
            (detail_xml("WLF00000915"), "WLF-1"),
            (detail_xml("WLF00000915", "<basfrmList>2026년 신청서 양식</basfrmList>"), "WLF00000915"),
            (detail_xml("WLF00000915", "<baslawList><wlfareInfoReldNm>조례</wlfareInfoReldNm>본문</baslawList>"),
             "WLF00000915"),
        )
        for raw, serv_id in cases:
            with self.subTest(raw=raw[-120:], serv_id=serv_id), self.assertRaises(ValueError):
                parse_detail(raw, service_id=serv_id)


if __name__ == "__main__":
    unittest.main()
