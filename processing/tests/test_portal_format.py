import csv
from io import StringIO
import json
import unittest

from processing.collection.__main__ import parse_portal
from processing.collection.portal_format import csv_header, csv_row, parse_page


# 2026-11-29 실제 응답 행의 열 이름(값은 모두 합성)이다.
REAL_KEYS = {
    "culture": (
        "fstvlNm", "opar", "fstvlStartDate", "fstvlEndDate", "fstvlCo", "mnnstNm", "auspcInsttNm",
        "suprtInsttNm", "phoneNumber", "homepageUrl", "relateInfo", "rdnmadr", "lnmadr", "latitude",
        "longitude", "referenceDate", "insttCode", "insttNm",
    ),
    "living": (
        "lbrryNm", "ctprvnNm", "signguNm", "lbrrySe", "closeDay", "weekdayOperOpenHhmm", "weekdayOperColseHhmm",
        "satOperOperOpenHhmm", "satOperCloseHhmm", "holidayOperOpenHhmm", "holidayCloseOpenHhmm", "seatCo",
        "bookCo", "pblictnCo", "noneBookCo", "lonCo", "lonDaycnt", "rdnmadr", "operInstitutionNm", "phoneNumber",
        "plotAr", "buldAr", "homepageUrl", "latitude", "longitude", "referenceDate", "insttCode", "insttNm",
    ),
}


def record(category, **values):
    return {**dict.fromkeys(REAL_KEYS[category], ""), **values}


def envelope(items, *, page=1, size=2, total=2, header=None):
    """실제 응답처럼 response 감싸기 없이 header·body를 최상위에 둔다."""
    return {
        "header": header or {"resultCode": "00", "resultMsg": "NORMAL SERVICE."},
        "body": {"items": items, "numOfRows": size, "pageNo": page, "totalCount": total},
    }


def _page(rows, **options):
    return json.dumps(envelope({"item": rows}, **options), ensure_ascii=False).encode("utf-8")


def _csv(category, records):
    stream = StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(csv_header(category))
    writer.writerows(csv_row(category, item) for item in records)
    return stream.getvalue()


class PortalFormatTest(unittest.TestCase):
    def test_parses_real_shape_and_exact_last_page_count(self):
        row = record("culture", fstvlNm="마지막 합성 자료")
        self.assertEqual(parse_page("culture", _page([row], page=2, total=3), 2, 2), (3, [row]))
        rows = [record("living", lbrryNm="합성"), record("living", lbrryNm="합성2")]
        self.assertEqual(parse_page("living", _page(rows, total=5), 1, 2), (5, rows))

    def test_rejects_header_other_than_observed_success_without_echoing_message(self):
        rows = [record("culture")] * 2
        for header in (
            {"resultCode": "22", "resultMsg": "비공개 합성 표시"},
            {"resultCode": "00", "resultMsg": "비공개 합성 표시"},
            {"resultCode": 0, "resultMsg": "NORMAL SERVICE."},
            {"resultCode": "00"},
            {"resultCode": "00", "resultMsg": "NORMAL SERVICE.", "type": "json"},
        ):
            with self.subTest(header=header), self.assertRaisesRegex(ValueError, "성공 코드") as caught:
                parse_page("culture", _page(rows, header=header), 1, 2)
            self.assertNotIn("비공개", str(caught.exception))

    def test_rejects_unobserved_envelopes_and_counts(self):
        row = record("culture")
        documented = {"response": envelope([row, row])}
        extra_top = {**envelope({"item": [row, row]}), "type": "json"}
        extra_body = envelope({"item": [row, row]})
        extra_body["body"]["resultType"] = "json"
        for document, page, message in (
            (documented, 1, "최상위"),
            (extra_top, 1, "최상위"),
            (extra_body, 1, "body의 키"),
            (envelope({"item": [row, row]}, page="1"), 1, "JSON 정수"),
            (envelope({"item": [row, row]}, total=True), 1, "JSON 정수"),
            (envelope({"item": [row, row]}, size=1), 1, "요청과 다릅니다"),
            (envelope({"item": [row, row]}, page=2), 1, "요청과 다릅니다"),
            (envelope({"item": [row]}, total=4), 1, "행 개수"),
            (envelope({"item": [row, row]}, page=2, total=3), 2, "행 개수"),
        ):
            with self.subTest(document=document), self.assertRaisesRegex(ValueError, message):
                parse_page("culture", json.dumps(document).encode(), page, 2)
        with self.assertRaises(ValueError):
            parse_page("culture", b"<response><header><resultCode>00</resultCode></header></response>", 1, 2)

    def test_rejects_empty_and_single_object_items_never_observed(self):
        row = record("culture")
        for items, total, message in (
            ({"item": []}, 0, "빈 페이지"),
            ("", 0, "빈 페이지"),
            ({}, 0, "빈 페이지"),
            ({"item": row}, 1, "items"),
            ([row], 1, "items"),
            ({"item": [row], "numOfRows": 1}, 1, "items"),
            ({}, 1, "items"),
            (None, 1, "items"),
        ):
            with self.subTest(items=items, total=total), self.assertRaisesRegex(ValueError, message):
                parse_page("culture", json.dumps(envelope(items, total=total)).encode(), 1, 2)
        # 마지막 페이지 뒤의 요청도 같은 빈 페이지 거부다.
        with self.assertRaisesRegex(ValueError, "빈 페이지"):
            parse_page("culture", _page([], page=2, total=2), 2, 2)

    def test_rejects_rows_other_than_observed_columns_and_string_values(self):
        culture = record("culture")
        missing = dict(culture)
        del missing["relateInfo"]
        old_living = {key.upper(): "" for key in REAL_KEYS["living"]}
        for category, row, message in (
            ("culture", missing, "열 이름"),
            ("culture", {**culture, "extra": ""}, "열 이름"),
            ("culture", record("living"), "열 이름"),
            ("living", old_living, "열 이름"),
            ("culture", "행", "열 이름"),
            ("culture", {**culture, "latitude": None}, "문자열"),
            ("culture", {**culture, "insttCode": 4550000}, "문자열"),
            ("culture", {**culture, "opar": ["목록"]}, "문자열"),
            ("culture", {**culture, "opar": "제어\x00문자"}, "NUL"),
        ):
            with self.subTest(row=row), self.assertRaisesRegex(ValueError, message):
                parse_page(category, _page([row], size=1, total=1), 1, 1)
        decimal = _page([culture], size=1, total=1).replace(b'"latitude": ""', b'"latitude": 37.1')
        with self.assertRaisesRegex(ValueError, "문자열"):
            parse_page("culture", decimal, 1, 1)
        for unknown in ("unknown", None):
            with self.subTest(unknown=unknown), self.assertRaisesRegex(ValueError, "분야"):
                parse_page(unknown, _page([culture], size=1, total=1), 1, 1)
        with self.assertRaisesRegex(ValueError, "분야"):
            csv_header("unknown")

    def test_festival_mapping_preserves_values_and_csv_rows(self):
        item = record(
            "culture", fstvlNm="합성 축제", opar='제1공간, "합성"', fstvlStartDate="2026-11-01",
            fstvlEndDate="2026-11-03", fstvlCo="첫 줄\n둘째 줄", auspcInsttNm="합성 기관",
            homepageUrl="https://example.invalid/festival", rdnmadr="경기도 안성시 시험로",
            lnmadr="경기도 안성시 합성동 1", latitude="37.12345678901234567890", relateInfo="CSV에 없는 열",
        )
        other = record("culture", fstvlNm="다른 행사", rdnmadr="경기도 다른시 시험로")
        _, rows = parse_page("culture", _page([item, other]), 1, 2)
        projected, = parse_portal("culture", _csv("culture", rows))
        self.assertEqual(projected["title"], "합성 축제")
        self.assertEqual(projected["official_url"], "https://example.invalid/festival")
        self.assertEqual(projected["fields"], {
            "start_date": "2026-11-01", "end_date": "2026-11-03", "place": '제1공간, "합성"',
            "road_address": "경기도 안성시 시험로", "parcel_address": "경기도 안성시 합성동 1",
            "latitude": "37.12345678901234567890", "organizer": "합성 기관", "description": "첫 줄\n둘째 줄",
        })

    def test_library_projection_uses_real_camel_case_fields_for_anseong_filter(self):
        item = record(
            "living", lbrryNm="합성도서관", ctprvnNm="경기도", signguNm="안성시", closeDay="월",
            weekdayOperOpenHhmm="09:00", weekdayOperColseHhmm="17:00", satOperOperOpenHhmm="10:00",
            satOperCloseHhmm="18:00", holidayOperOpenHhmm="11:00", holidayCloseOpenHhmm="16:00",
            rdnmadr="경기도 안성시 시험로", operInstitutionNm="합성 운영기관",
            homepageUrl="https://example.invalid/library", seatCo="CSV에 없는 열",
        )
        others = [record("living", lbrryNm="다른도서관", ctprvnNm="경기도", signguNm="수원시",
                         rdnmadr="경기도 안성시 주소만 맞음"),
                  record("living", lbrryNm="안성 이름만", ctprvnNm="경기", signguNm="안성시")]
        _, rows = parse_page("living", _page([item, *others], size=3, total=3), 1, 3)
        projected, = parse_portal("living", _csv("living", rows))
        self.assertEqual(projected["title"], "합성도서관")
        self.assertEqual(projected["official_url"], "https://example.invalid/library")
        self.assertEqual(projected["fields"], {
            "address": "경기도 안성시 시험로", "closed_days": "월",
            "weekday_open": "09:00", "weekday_close": "17:00", "saturday_open": "10:00",
            "saturday_close": "18:00", "holiday_open": "11:00", "holiday_close": "16:00",
            "operator": "합성 운영기관",
        })
