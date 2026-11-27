from datetime import date
import unittest
from unittest.mock import patch

from processing.collection.official_web import DETAIL_MAX_BYTES, SourceHTTPError, detail_url, fetch_detail, fetch_listing


class OfficialWebTest(unittest.TestCase):
    def setUp(self):
        connection_patch = patch("processing.collection.official_web.HTTPSConnection")
        self.connect = connection_patch.start()
        self.addCleanup(connection_patch.stop)
        self.connection = self.connect.return_value
        self.response = self.connection.getresponse.return_value.__enter__.return_value
        self.response.status = 200
        self.headers = {}
        self.response.getheader.side_effect = self.headers.get
        self.response.read.return_value = b"{}"

    def test_only_canonical_sources_have_urls(self):
        self.assertEqual(
            detail_url("culture", "17"),
            "https://www.anseong.go.kr/event/program/popup/detail.do?idx=17",
        )
        self.assertEqual(
            detail_url("living", "77"),
            "https://www.anseong.go.kr/library/bbs/view.do?bIdx=77&mId=0401010000&ptIdx=16",
        )
        for category, web_id in (
            ("https://example.invalid", "17"), ("culture", ""), ("culture", "0"),
            ("culture", "017"), ("culture", "３"), ("culture", "1\n"),
            ("culture", "1&idx=9"), ("living", "1" * 19),
        ):
            with self.subTest(category=category, web_id=web_id):
                with self.assertRaises(ValueError):
                    fetch_detail(category, web_id, limit=64)
        self.connect.assert_not_called()

    def test_exact_request_reads_unchanged_bytes_and_closes(self):
        self.headers["Content-Length"] = "2"
        self.assertEqual(fetch_detail("culture", "17", limit=2), b"{}")
        self.connect.assert_called_once_with("www.anseong.go.kr", timeout=15)
        self.connection.request.assert_called_once_with(
            "GET", "/event/program/popup/detail.do?idx=17",
            headers={
                "User-Agent": "yeogi-it/official-source-capture",
                "Accept-Encoding": "identity",
                "Connection": "close",
            },
        )
        self.response.read.assert_called_once_with(3)
        self.connection.close.assert_called_once()

    def test_redirects_and_error_response_do_not_read_or_retry(self):
        self.headers["Location"] = "https://example.invalid/private"
        for status in (302, 404, 500):
            with self.subTest(status=status):
                self.connection.request.reset_mock()
                self.response.status = status
                with self.assertRaisesRegex(ValueError, rf"HTTP 응답 오류\({status}\)"):
                    fetch_detail("culture", "17", limit=64)
                self.connection.request.assert_called_once()
        self.response.read.assert_not_called()

    def test_rejects_oversize_with_or_without_declared_length(self):
        self.headers["Content-Length"] = "4"
        with self.assertRaisesRegex(ValueError, "허용 크기"):
            fetch_detail("living", "77", limit=2)
        self.response.read.assert_not_called()

        self.headers.clear()
        self.response.read.return_value = b"abc"
        with self.assertRaisesRegex(ValueError, "허용 크기"):
            fetch_detail("living", "77", limit=2)
        self.response.read.assert_called_once_with(3)

    def test_rejects_truncated_and_ambiguous_framing(self):
        self.headers["Content-Length"] = "3"
        with self.assertRaisesRegex(ValueError, "전송 중 중단"):
            fetch_detail("culture", "17", limit=64)
        self.headers["Transfer-Encoding"] = "chunked"
        with self.assertRaisesRegex(ValueError, "전송 형식"):
            fetch_detail("culture", "17", limit=64)
        self.headers.pop("Transfer-Encoding")
        self.headers["Content-Length"] = "3, 3"
        with self.assertRaisesRegex(ValueError, "길이가 유효하지"):
            fetch_detail("culture", "17", limit=64)

    def test_chunked_bytes_need_no_length_and_compressed_bodies_are_rejected(self):
        self.headers["Transfer-Encoding"] = "chunked"
        self.assertEqual(fetch_detail("culture", "17", limit=64), b"{}")
        self.response.read.reset_mock()
        self.headers["Content-Encoding"] = "gzip"
        with self.assertRaisesRegex(ValueError, "인코딩"):
            fetch_detail("culture", "17", limit=64)
        self.response.read.assert_not_called()

    def test_timeout_hides_raw_exception_and_closes(self):
        self.response.read.side_effect = TimeoutError("비공개 데이터")
        with self.assertRaisesRegex(ValueError, "대기 시간을 초과") as caught:
            fetch_detail("culture", "17", limit=64)
        self.assertNotIn("비공개 데이터", str(caught.exception))
        self.assertTrue(caught.exception.__suppress_context__)
        self.connection.close.assert_called_once()

    def test_invalid_size_limit_does_not_connect(self):
        for limit in (0, -1, True, DETAIL_MAX_BYTES + 1):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                fetch_detail("culture", "17", limit=limit)
        self.connect.assert_not_called()

    def test_event_listing_uses_exact_public_query(self):
        self.assertEqual(fetch_listing("culture", 2, date(2026, 11, 1), date(2026, 11, 30), limit=64), b"{}")
        method, path = self.connection.request.call_args.args
        self.assertEqual(method, "GET")
        self.assertEqual(path, "/event/program/list/json.do?page=2&searchSdate=2026-11-01&searchEdate=2026-11-30")
        self.assertNotIn("body", self.connection.request.call_args.kwargs)

    def test_library_listing_posts_only_page_to_the_notice_board(self):
        self.response.status = 429
        with self.assertRaises(SourceHTTPError) as caught:
            fetch_listing("living", 2, None, None, limit=64)
        self.assertEqual(caught.exception.status, 429)
        method, path = self.connection.request.call_args.args
        self.assertEqual((method, path), ("POST", "/library/bbs/list.do?ptIdx=16&mId=0401010000"))
        self.assertEqual(self.connection.request.call_args.kwargs["body"], b"page=2")
        self.assertEqual(self.connection.request.call_args.kwargs["headers"]["Content-Type"],
                         "application/x-www-form-urlencoded")
        self.response.read.assert_not_called()

    def test_listing_rejects_invalid_page_or_period_before_request(self):
        day = date(2026, 11, 1)
        for args in (("culture", 0, day, day), ("culture", 1, None, None),
                     ("culture", 1, day, date(2027, 1, 1)), ("living", 1, day, day),
                     ("unknown", 1, None, None)):
            with self.subTest(args=args), self.assertRaises(ValueError):
                fetch_listing(*args, limit=64)
        self.connect.assert_not_called()
