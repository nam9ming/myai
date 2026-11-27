"""합성 전국축제 CSV와 행사 상세 JSON의 필드·형식 차이를 검증한다."""

import csv
import io
import json
import unittest

from processing.collection.events import parse_event_detail, parse_festival_csv


def festival_csv(rows):
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow([
        "축제명", "개최장소", "축제시작일자", "축제종료일자", "소재지도로명주소",
        "소재지지번주소", "주최기관명", "홈페이지주소", "축제내용",
    ])
    writer.writerows(rows)
    return "\ufeff" + output.getvalue()


class FestivalCsvTest(unittest.TestCase):
    def test_filters_by_address_exact_organizer_or_official_domain(self):
        rows = [
            ("주소 축제", "합성광장, 제1구역", "2026-10-01", "2026-10-02",
             "경기도 안성시 합성로 1", "", "", "", "첫째 줄\n둘째 줄"),
            ("지번 축제", "", "", "", "", "안성시 합성동 1", "", "", ""),
            ("기관 축제", "", "", "", "", "", "경기도 안성시", "", ""),
            ("공식 링크 축제", "", "", "", "", "", "", "https://www.anseong.go.kr/festival", ""),
            ("외지 축제", "안성시 이름을 쓴 장소", "", "", "경기도 가상시 길", "", "",
             "https://notanseong.go.kr/festival", ""),
            ("다른 지역 행사", "", "", "", "경기도 가상시 길", "", "안성시",
             "https://www.anseong.go.kr/festival", ""),
            ("유사 주소 축제", "", "", "", "경기도 안성시장로 1", "", "안성시민 모임", "", ""),
        ]
        items = parse_festival_csv(festival_csv(rows))
        self.assertEqual([item["title"] for item in items],
                         ["주소 축제", "지번 축제", "기관 축제", "공식 링크 축제"])
        self.assertEqual(items[0], {
            "source": "festival_portal",
            "external_id": None,
            "source_record": 1,
            "title": "주소 축제",
            "official_url": None,
            "fields": {"place": "합성광장, 제1구역", "start_date": "2026-10-01",
                       "end_date": "2026-10-02", "road_address": "경기도 안성시 합성로 1",
                       "description": "첫째 줄\n둘째 줄"},
        })
        self.assertEqual(items[3]["official_url"], "https://www.anseong.go.kr/festival")
        self.assertEqual([item["source_record"] for item in items], [1, 2, 3, 4])

    def test_no_relevant_rows_is_a_valid_result(self):
        self.assertEqual(parse_festival_csv("축제명,소재지도로명주소\n외지,가상시 가상로\n"), [])

    def test_rejects_malformed_headers_and_rows(self):
        for raw in (
            "축제명",
            "축제명,축제명,소재지도로명주소\n",
            "축제명,소재지도로명주소\n축제\n",
            "축제명,소재지도로명주소\n축제,안성시,잉여 열\n",
            "축제명,소재지도로명주소\n,경기도 안성시 합성로\n",
            '축제명,소재지도로명주소\n"닫히지 않은 제목,경기도 안성시',
        ):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                parse_festival_csv(raw)


class EventDetailTest(unittest.TestCase):
    def test_free_form_fields_and_original_markup_are_preserved(self):
        raw = json.dumps({
            "idx": 17,
            "title": "합성 나눔 행사",
            "eventSdate": "2026-10-01",
            "eventEdate": "2026-10-03",
            "eventTime": "첫날 오후 / 나머지 추후 공지",
            "eventFee": "재료비 0원 / 선택 체험 별도",
            "eventPlace": "합성광장",
            "eventTarget": "보호자 동반 초등학생",
            "deptName": "합성기관",
            "url": "https://www.anseong.go.kr/event/main.do",
            "attachId": "synthetic-file",
            "thumbnail": "synthetic-poster",
            "contents": "<p>원문 <strong>안내</strong></p>",
        })
        self.assertEqual(parse_event_detail(raw, event_id="17"), {
            "source": "anseong_events",
            "external_id": "17",
            "title": "합성 나눔 행사",
            "official_url": "https://www.anseong.go.kr/event/main.do",
            "source_url": "https://www.anseong.go.kr/event/program/popup/detail.do?idx=17",
            "review_flags": ["attachment", "thumbnail"],
            "fields": {
                "start_date": "2026-10-01",
                "end_date": "2026-10-03",
                "time": "첫날 오후 / 나머지 추후 공지",
                "fee": "재료비 0원 / 선택 체험 별도",
                "place": "합성광장",
                "target": "보호자 동반 초등학생",
                "organizer": "합성기관",
                "description": "<p>원문 <strong>안내</strong></p>",
            },
        })

    def test_optional_fields_can_be_missing_or_blank_and_zero_is_kept(self):
        blank = parse_event_detail(
            '{"idx":17,"title":"합성","eventTime":null,"eventPlace":" ","url":""}', event_id="17")
        self.assertEqual(blank["fields"], {})
        self.assertIsNone(blank["official_url"])
        self.assertNotIn("review_flags", blank)
        zero = parse_event_detail('{"idx":"17","title":"합성","eventFee":"0"}', event_id="17")
        self.assertEqual(zero["fields"], {"fee": "0"})
        self.assertIsNone(zero["official_url"])

    def test_invalid_optional_urls_are_not_carried_through(self):
        for url in ("/event/main.do", "ftp://example.invalid/file",
                    "https://example.invalid:invalid", "https://example.invalid/a b"):
            with self.subTest(url=url):
                obj = parse_event_detail(json.dumps({"idx": 17, "title": "합성", "url": url}), event_id="17")
                self.assertIsNone(obj["official_url"])

    def test_rejects_noncanonical_ids_mismatches_and_malformed_json(self):
        for key, raw in (
            ("017", '{"title":"합성"}'),
            ("17", '{"idx":"18","title":"합성"}'),
            ("1", '{"idx":true,"title":"합성"}'),
            ("17", '{"title":"합성"}'),
            ("17", '{"idx":17,"title":"합성","title":"중복"}'),
            ("17", '{"idx":17,"title":5}'),
            ("17", '{"idx":17,"title":"합성","eventFee":["별도"]}'),
            ("17", '[{"title":"목록"}]'),
        ):
            with self.subTest(key=key, raw=raw), self.assertRaises(ValueError):
                parse_event_detail(raw, event_id=key)
