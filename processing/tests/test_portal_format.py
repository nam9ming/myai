import csv
from io import StringIO
import json
import unittest

from processing.collection.__main__ import parse_portal
from processing.collection.portal_format import csv_header, csv_row, parse_page


def _page(items, *, page=1, size=2, total=2, code="00"):
    return json.dumps({
        "response": {
            "header": {"resultCode": code, "resultMsg": "응답에 포함된 비공개 합성 표시"},
            "body": {"pageNo": page, "numOfRows": size, "totalCount": total, "items": items},
        }
    }).encode("utf-8")


def _csv(category, records):
    stream = StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(csv_header(category))
    writer.writerows(csv_row(category, record) for record in records)
    return stream.getvalue()


class PortalFormatTest(unittest.TestCase):
    def test_parses_exact_page_count_and_empty_search(self):
        raw = _page([{"name": "마지막 합성 자료"}], page="002", size="2", total="3")
        self.assertEqual(parse_page(raw, 2, 2), (3, [{"name": "마지막 합성 자료"}]))
        self.assertEqual(parse_page(_page([], total=0), 1, 2), (0, []))

    def test_rejects_unsuccessful_codes_without_echoing_error_message(self):
        for code in (0, "22", None):
            with self.subTest(code=code), self.assertRaisesRegex(ValueError, "성공 코드") as caught:
                parse_page(_page([], total=0, code=code), 1, 2)
            self.assertNotIn("비공개", str(caught.exception))

    def test_rejects_page_size_wrong_offset_and_incomplete_rows(self):
        for raw, page, size in (
            (_page([], page=2, total=0), 1, 2),
            (_page([], size=1, total=0), 1, 2),
            (_page([{}, {}], page=2, total=3), 2, 2),
            (_page([{}], total=4), 1, 2),
            (_page([], total=True), 1, 2),
            (_page({"item": [{}]}), 1, 2),
            (b'<result>error</result>', 1, 2),
        ):
            with self.subTest(page=page, size=size), self.assertRaises(ValueError):
                parse_page(raw, page, size)

    def test_festival_mapping_preserves_precise_values_and_csv_rows(self):
        record = {
            "fstvlNm": "합성 축제",
            "opar": '제1공간, "합성"',
            "fstvlStartDate": "2026-11-01",
            "fstvlEndDate": "2026-11-03",
            "fstvlCo": "첫 줄\n둘째 줄",
            "auspcInsttNm": "합성 기관",
            "homepageUrl": "https://example.invalid/festival",
            "rdnmadr": "경기도 안성시 시험로",
            "lnmadr": "경기도 안성시 합성동 1",
            "latitude": "PRECISION",
            "longitude": None,
        }
        raw = _page([record, {"fstvlNm": "다른 행사", "rdnmadr": "경기도 다른시 시험로"}])
        raw = raw.replace(b'"PRECISION"', b"37.12345678901234567890")
        _, rows = parse_page(raw, 1, 2)
        projected, = parse_portal("culture", _csv("culture", rows))
        self.assertEqual(projected["title"], "합성 축제")
        self.assertEqual(projected["official_url"], "https://example.invalid/festival")
        self.assertEqual(projected["fields"], {
            "start_date": "2026-11-01", "end_date": "2026-11-03", "place": '제1공간, "합성"',
            "road_address": "경기도 안성시 시험로", "parcel_address": "경기도 안성시 합성동 1",
            "latitude": "37.12345678901234567890", "organizer": "합성 기관", "description": "첫 줄\n둘째 줄",
        })

    def test_library_projection_uses_exact_documented_field_spellings(self):
        record = {
            "LBRRY_NM": "합성도서관", "CTPRVN_NM": "경기도", "SIGNGU_NM": "안성시",
            "CLOSE_DAY": "월", "WEEKDAY_OPER_OPEN_HHMM": 900, "WEEKDAY_OPER_COLSE_HHMM": "17:00",
            "SAT_OPER_OPER_OPEN_HHMM": "10:00", "SAT_OPER_CLOSE_HHMM": "18:00",
            "HOLIDAY_OPER_OPEN_HHMM": "11:00", "HOLIDAY_CLOSE_OPEN_HHMM": "16:00",
            "RDNMADR": "경기도 안성시 시험로", "OPER_INSTITUTION_NM": "합성 운영기관",
            "HOMEPAGE_URL": "https://example.invalid/library",
        }
        projected, = parse_portal("living", _csv("living", [record]))
        self.assertEqual(projected["title"], "합성도서관")
        self.assertEqual(projected["official_url"], "https://example.invalid/library")
        self.assertEqual(projected["fields"], {
            "address": "경기도 안성시 시험로", "closed_days": "월",
            "weekday_open": "900", "weekday_close": "17:00", "saturday_open": "10:00",
            "saturday_close": "18:00", "holiday_open": "11:00", "holiday_close": "16:00",
            "operator": "합성 운영기관",
        })

    def test_csv_rejects_unknown_shape_and_invalid_mapped_cells(self):
        for category, record in (
            ("culture", {"fstvlNm": "합성"}),
            ("culture", {"rdnmadr": "경기도 안성시"}),
            ("culture", {"fstvlNm": 7, "rdnmadr": "경기도 안성시"}),
            ("culture", {"fstvlNm": "합성", "rdnmadr": None, "opar": True}),
            ("culture", {"fstvlNm": "합성", "rdnmadr": None, "opar": ["목록"]}),
            ("culture", {"fstvlNm": "합성", "rdnmadr": None, "opar": "제어\x00문자"}),
            ("living", {"LBRRY_NM": "합성", "CTPRVN_NM": "경기도", "signguNm": "안성시"}),
        ):
            with self.subTest(category=category, record=record), self.assertRaises(ValueError):
                csv_row(category, record)
        with self.assertRaisesRegex(ValueError, "분야"):
            csv_header("unknown")
