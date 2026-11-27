from http.client import HTTPException
import traceback
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from processing.collection.official_web import DETAIL_MAX_BYTES, SourceHTTPError
from processing.collection.portal_transport import fetch_portal_page, portal_endpoint


_SYNTHETIC_KEY = "example/-_+=123"
_ENCODED_KEY = "example%2F-_%2B%3D123"


class PortalTransportTest(unittest.TestCase):
    def setUp(self):
        self.connect = self.enterContext(patch("processing.collection.official_web.HTTPSConnection"))
        self.connection = self.connect.return_value
        self.response = self.connection.getresponse.return_value.__enter__.return_value
        self.response.status = 200
        self.headers = {}
        self.response.getheader.side_effect = self.headers.get

    def test_fixed_endpoints_and_single_query_encoding(self):
        raw = b'{"response":{"items":["path\\/section%2fcontents"]}}\n'
        self.response.read.return_value = raw
        self.headers["Content-Length"] = str(len(raw))
        paths = {
            "culture": "/openapi/tn_pubr_public_cltur_fstvl_api",
            "living": "/openapi/tn_pubr_public_lbrry_api",
        }
        for category, path in paths.items():
            with self.subTest(category=category):
                self.connect.reset_mock()
                self.assertEqual(portal_endpoint(category), "https://api.data.go.kr" + path)
                self.assertEqual(fetch_portal_page(category, 2, 250, _SYNTHETIC_KEY), raw)
                self.connect.assert_called_once_with("api.data.go.kr", timeout=15)
                method, target = self.connection.request.call_args.args
                request = urlsplit(target)
                self.assertEqual((method, request.scheme, request.netloc, request.path), ("GET", "", "", path))
                self.assertEqual(parse_qs(request.query), {
                    "pageNo": ["2"], "numOfRows": ["250"], "type": ["json"], "serviceKey": [_SYNTHETIC_KEY],
                })
                self.assertIn(f"serviceKey={_ENCODED_KEY}", request.query)
                self.response.read.assert_called_once_with(DETAIL_MAX_BYTES + 1)

    def test_invalid_inputs_do_not_connect(self):
        for category, page, count, key in (
            ("https://example.invalid", 1, 1, _SYNTHETIC_KEY),
            ("culture", 0, 1, _SYNTHETIC_KEY), ("culture", True, 1, _SYNTHETIC_KEY),
            ("culture", 1, 1001, _SYNTHETIC_KEY), ("living", 1, 1, _ENCODED_KEY),
            ("living", 1, 1, ""), ("living", 1, 1, "key&x=evil"),
        ):
            with self.subTest(category=category, page=page, count=count), self.assertRaises(ValueError):
                fetch_portal_page(category, page, count, key)
        self.connect.assert_not_called()

    def test_redirects_and_http_errors_do_not_read_or_retry(self):
        self.headers["Location"] = f"https://example.invalid/?serviceKey={_ENCODED_KEY}"
        for status in (301, 302, 307, 400, 429, 500):
            with self.subTest(status=status):
                self.response.status = status
                with self.assertRaises(SourceHTTPError) as caught:
                    fetch_portal_page("culture", 1, 100, _SYNTHETIC_KEY)
                self.assertEqual(caught.exception.status, status)
                self.assertNotIn(_ENCODED_KEY, str(caught.exception))
        self.assertEqual(self.connection.request.call_count, 6)
        self.response.read.assert_not_called()

    def test_secret_is_rejected_before_returning_response_bytes(self):
        variants = (
            _SYNTHETIC_KEY.encode("ascii"),
            _ENCODED_KEY.encode("ascii"),
            _SYNTHETIC_KEY.encode("ascii").replace(b"/", rb"\/"),
            b"%65xample%2f-_%2b%3d123",
            rb"example\/-_%2B%3D123",
            rb"\u0065xample\u002f-_\u002b\u003d123",
        )
        for variant in variants:
            with self.subTest(variant=variant):
                self.response.read.return_value = b'{"credential":"' + variant + b'"}'
                with self.assertRaisesRegex(ValueError, "응답에 인증 키") as caught:
                    fetch_portal_page("living", 1, 50, _SYNTHETIC_KEY)
                self.assertNotIn(variant.decode("ascii"), str(caught.exception))

    def test_transport_errors_omit_raw_failure_details(self):
        for err in (TimeoutError(_SYNTHETIC_KEY), OSError(_SYNTHETIC_KEY), HTTPException(_ENCODED_KEY)):
            with self.subTest(error_type=type(err).__name__):
                self.connection.request.side_effect = err
                with self.assertRaises(ValueError) as failure:
                    fetch_portal_page("living", 1, 50, _SYNTHETIC_KEY)
                rendered = "".join(traceback.format_exception(failure.exception))
                self.assertNotIn(_SYNTHETIC_KEY, rendered)
                self.assertNotIn(_ENCODED_KEY, rendered)
