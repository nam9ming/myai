import json
import unittest

from processing.collection.event_listing import parse_event_listing


def _listing(*rows, page=1, total=10):
    return json.dumps({
        "curPage": page,
        "totalCnt": total,
        "list": list(rows),
        "listOrder": 10,
        "paginationInfo": "<button>다음 페이지</button>",
    }).encode("utf-8")


class EventListingTest(unittest.TestCase):
    def test_preserves_row_order_and_canonicalizes_ids(self):
        raw = _listing({"idx": 24, "title": "합성 게시물"}, {"idx": "17"}, {"idx": 10**17}, page=2)
        self.assertEqual(parse_event_listing(raw, page=2), (10, ["24", "17", "100000000000000000"]))

    def test_empty_first_and_later_pages_expose_reported_total(self):
        self.assertEqual(parse_event_listing(_listing(total=0), page=1), (0, []))
        self.assertEqual(parse_event_listing(_listing(page=2, total=3), page=2), (3, []))

    def test_rejects_invalid_requested_or_reported_page(self):
        for page in (0, -1, True, "1"):
            with self.subTest(page=page), self.assertRaisesRegex(ValueError, "페이지 번호"):
                parse_event_listing(_listing(total=0), page=page)
        for current in (2, True, "1", 1.0, None):
            with self.subTest(current=current), self.assertRaisesRegex(ValueError, "페이지 번호"):
                parse_event_listing(_listing(page=current, total=0), page=1)

    def test_rejects_invalid_totals_and_impossible_row_counts(self):
        for total in (None, True, "1", 1.0, -1):
            with self.subTest(total=total), self.assertRaisesRegex(ValueError, "전체 건수"):
                parse_event_listing(_listing(total=total), page=1)
        for raw, page in (
            (_listing(total=1), 1),
            (_listing({"idx": 1}, total=0), 1),
            (_listing({"idx": 1}, {"idx": 2}, page=2, total=2), 2),
        ):
            with self.subTest(page=page), self.assertRaisesRegex(ValueError, "행 개수"):
                parse_event_listing(raw, page=page)

    def test_rejects_duplicate_invalid_or_missing_ids_and_non_object_rows(self):
        for value in (True, 1.0, "01", "１", "3\n", 0, -1, 10**18, "1&idx=2", None):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "게시물 번호"):
                parse_event_listing(_listing({"idx": value}), page=1)
        with self.assertRaisesRegex(ValueError, "게시물 번호"):
            parse_event_listing(_listing({"title": "합성 자리표시자"}), page=1)
        with self.assertRaisesRegex(ValueError, "중복 게시물"):
            parse_event_listing(_listing({"idx": 15}, {"idx": "15"}), page=1)
        with self.assertRaisesRegex(ValueError, "행은 JSON 객체"):
            parse_event_listing(_listing("15"), page=1)

    def test_rejects_non_list_wrong_json_shape_and_non_json_responses(self):
        for raw in (
            b'{"curPage":1,"totalCnt":0,"list":{}}',
            b'{"curPage":1,"totalCnt":0}',
            b'{"curPage":1,"totalCnt":0,"list":[],"list":[]}',
            b'{"curPage":1,"totalCnt":0,"list":[]} garbage',
            b'["invalid"]',
            b'<html>placeholder</html>',
        ):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                parse_event_listing(raw, page=1)

    def test_rejects_oversize_lists_before_reading_rows(self):
        with self.assertRaisesRegex(ValueError, "페이지당 최대"):
            parse_event_listing(_listing(*([None] * 101), total=101), page=1)
