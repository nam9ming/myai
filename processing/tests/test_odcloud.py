import contextlib
import hashlib
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unicodedata
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from processing.collection import odcloud
from processing.collection.d03 import prepare
from processing.collection.d03_sources import capture_assets
from processing.collection.official_web import DETAIL_MAX_BYTES
from processing.collection.odcloud_format import DATASETS, parse_page, select_rows


# 모든 응답은 Swagger 모델을 본뜬 합성 값이다. 실제 인증 응답으로 확인하지 않았다.
_KEY = "synthetic+odcloud/key="
_ENCODED_KEY = "synthetic%2Bodcloud%2Fkey%3D"
_LEARNING = DATASETS["digital-learning"].fields
_ROAD = DATASETS["road-construction"].fields


def learning(region="경기도", district="안성시", name="합성 배움터", address="경기도 안성시 합성로 1"):
    return dict(zip(_LEARNING, (region, district, name, address, "거점", 20)))


def road(site="경기도 안성시", location="안성시 합성면 일원", office="경기도 수원시 합성로 2",
         start="2026-01-01", end="", title="합성 도로 공사"):
    return dict(zip(_ROAD, ("합성 발주청", title, "신설", site, "합성 개요", "국도 합성호선",
                            location, "합성 시공사", office, start, end, "1000000")))


def envelope(page, per_page, total, rows, **override):
    body = {"page": page, "perPage": per_page, "totalCount": total, "currentCount": len(rows),
            "matchCount": total, "data": rows, **override}
    return json.dumps(body, ensure_ascii=False).encode()


class OdcloudTransportTest(unittest.TestCase):
    def setUp(self):
        self.connect = self.enterContext(patch("processing.collection.official_web.HTTPSConnection"))
        self.connection = self.connect.return_value
        self.response = self.connection.getresponse.return_value.__enter__.return_value
        self.response.status = 200
        self.headers = {}
        self.response.getheader.side_effect = self.headers.get

    def test_swagger_paths_and_query(self):
        raw = envelope(2, 300, 0, [])
        self.response.read.return_value = raw
        paths = {
            "digital-learning": "/api/15134509/v1/uddi:b87e06b5-9a2a-4627-a3b3-c7a850904a62",
            "road-construction": "/api/15052289/v1/uddi:7cb3d05a-3099-4572-8a39-997740b78f76",
        }
        for name, path in paths.items():
            with self.subTest(name=name):
                self.connect.reset_mock()
                self.assertEqual(odcloud.odcloud_endpoint(name), "https://api.odcloud.kr" + path)
                self.assertEqual(odcloud.fetch_odcloud_page(name, 2, 300, _KEY), raw)
                self.connect.assert_called_once_with("api.odcloud.kr", timeout=15)
                method, target = self.connection.request.call_args.args
                request = urlsplit(target)
                self.assertEqual((method, request.netloc, request.path), ("GET", "", path))
                self.assertEqual(parse_qs(request.query), {
                    "page": ["2"], "perPage": ["300"], "returnType": ["JSON"], "serviceKey": [_KEY]})
                self.assertIn(f"serviceKey={_ENCODED_KEY}", request.query)
                self.assertNotIn(_KEY, odcloud.page_source(name, 2, 300))
                self.response.read.assert_called_once_with(DETAIL_MAX_BYTES + 1)
        self.assertEqual(DATASETS["road-construction"].swagger_url,
                         "https://infuser.odcloud.kr/oas/docs?namespace=15052289/v1")
        self.assertEqual(DATASETS["digital-learning"].catalog_url, "https://www.data.go.kr/data/15134509/fileData.do")

    def test_invalid_inputs_do_not_connect(self):
        for name, page, count, key in (
            ("https://example.invalid", 1, 1, _KEY), ("digital-learning", 0, 1, _KEY),
            ("digital-learning", True, 1, _KEY), ("road-construction", 1, 1001, _KEY),
            ("road-construction", 1, 0, _KEY), ("road-construction", 1, 1, ""),
            ("road-construction", 1, 1, "key&x=evil"), ("road-construction", 1, 1, _ENCODED_KEY),
        ):
            with self.subTest(name=name, page=page, count=count, key=key), self.assertRaises(ValueError):
                odcloud.fetch_odcloud_page(name, page, count, key)
        self.connect.assert_not_called()

    def test_redirect_and_http_errors_stop_without_reading(self):
        self.headers["Location"] = f"https://example.invalid/?serviceKey={_ENCODED_KEY}"
        for status in (301, 302, 401, 500):
            with self.subTest(status=status):
                self.response.status = status
                with self.assertRaisesRegex(ValueError, rf"^파일데이터 API HTTP 응답 오류\({status}\)\.$") as caught:
                    odcloud.fetch_odcloud_page("digital-learning", 1, 10, _KEY)
                self.assertNotIn(_ENCODED_KEY, str(caught.exception))
        self.response.read.assert_not_called()

    def test_key_echo_is_rejected(self):
        for variant in (_KEY.encode(), _ENCODED_KEY.encode(), _KEY.encode().replace(b"/", rb"\/"),
                        rb"synthetic+odcloud\/key="):
            with self.subTest(variant=variant):
                self.response.read.return_value = b'{"msg":"' + variant + b'"}'
                with self.assertRaisesRegex(ValueError, "인증 키") as caught:
                    odcloud.fetch_odcloud_page("road-construction", 1, 10, _KEY)
                self.assertNotIn(_KEY, str(caught.exception))

    def test_page_size_limit(self):
        self.headers["Content-Length"] = str(DETAIL_MAX_BYTES + 1)
        with self.assertRaisesRegex(ValueError, "허용 크기"):
            odcloud.fetch_odcloud_page("digital-learning", 1, 10, _KEY)
        self.response.read.assert_not_called()
        del self.headers["Content-Length"]
        self.response.read.return_value = b" " * (DETAIL_MAX_BYTES + 1)
        with self.assertRaisesRegex(ValueError, "허용 크기"):
            odcloud.fetch_odcloud_page("digital-learning", 1, 10, _KEY)

    def test_transport_errors_use_odcloud_wording(self):
        # 공통 요청 함수의 '공식 웹' 문구가 파일데이터 API 실패 기록에 남지 않는다.
        cases = (
            ("size", {"Content-Length": str(DETAIL_MAX_BYTES + 1)}, None, "파일데이터 API 응답이 허용 크기를 초과했습니다."),
            ("encoding", {"Content-Encoding": "gzip"}, None, "파일데이터 API 응답의 인코딩을 지원하지 않습니다."),
            ("timeout", {}, TimeoutError(), "파일데이터 API 응답의 대기 시간을 초과했습니다."),
            ("connection", {}, ConnectionRefusedError(), "파일데이터 API 응답을 받지 못했습니다."),
        )
        for label, headers, error, message in cases:
            with self.subTest(label):
                self.headers.clear()
                self.headers.update(headers)
                self.connection.request.side_effect = error
                with self.assertRaises(ValueError) as caught:
                    odcloud.fetch_odcloud_page("road-construction", 1, 10, _KEY)
                self.assertEqual(str(caught.exception), message)
        with TemporaryDirectory() as temp:
            root = Path(temp).resolve() / "collection-odcloud"
            self.assertEqual(odcloud.collect_odcloud("road-construction", "run", root, _KEY)["status"], "failed")
            receipt = json.loads((root / "run" / "odcloud.json").read_bytes())
        self.assertEqual(receipt["error"], "파일데이터 API 응답을 받지 못했습니다.")


class OdcloudFormatTest(unittest.TestCase):
    def test_valid_pages_and_last_page_count(self):
        rows = [learning(), learning(district="평택시")]
        self.assertEqual(parse_page("digital-learning", envelope(1, 2, 3, rows), 1, 2), (3, rows))
        self.assertEqual(parse_page("digital-learning", envelope(2, 2, 3, rows[:1]), 2, 2), (3, rows[:1]))
        self.assertEqual(parse_page("road-construction", envelope(1, 5, 0, []), 1, 5), (0, []))

    def test_envelope_errors(self):
        rows = [learning()]
        extra = json.loads(envelope(1, 1, 1, rows))
        extra["code"] = -4
        missing = json.loads(envelope(1, 1, 1, rows))
        del missing["matchCount"]
        cases = {
            "extra key": json.dumps(extra).encode(),
            "missing key": json.dumps(missing).encode(),
            "error body": '{"code": -4, "msg": "등록되지 않은 인증키"}'.encode(),
            "not object": b"[]",
            "duplicate key": b'{"page": 1, "page": 1}',
            "page": envelope(2, 1, 2, rows),
            "per page": envelope(1, 2, 1, rows),
            "string count": envelope(1, 1, 1, rows, totalCount="1", matchCount="1"),
            "bool count": envelope(1, 1, 1, rows, currentCount=True),
            "match count": envelope(1, 1, 1, rows, matchCount=0),
            "current count": envelope(1, 1, 1, rows, currentCount=0),
            "short page": envelope(1, 1, 3, []),
            "extra rows": envelope(1, 1, 0, rows, currentCount=1),
            "data type": envelope(1, 1, 1, rows, data={"0": rows[0]}),
            "row type": envelope(1, 1, 1, ["행"]),
            "row keys": envelope(1, 1, 1, [{**rows[0], "추가열": "값"}]),
            "row missing key": envelope(1, 1, 1, [{k: v for k, v in rows[0].items() if k != "이용정원"}]),
            "float": envelope(1, 1, 1, [{**rows[0], "이용정원": 1.5}]),
            "bool value": envelope(1, 1, 1, [{**rows[0], "이용정원": False}]),
            "nested": envelope(1, 1, 1, [{**rows[0], "배움터명": ["이름"]}]),
            "nul": envelope(1, 1, 1, [{**rows[0], "배움터명": "a\x00b"}]),
            "broken json": b'{"page": 1',
        }
        for label, raw in cases.items():
            with self.subTest(label), self.assertRaises(ValueError):
                parse_page("digital-learning", raw, 1, 1)
        with self.assertRaises(ValueError):
            parse_page("road-construction", envelope(1, 1, 1, rows), 1, 1)
        with self.assertRaises(ValueError):
            parse_page("unknown", envelope(1, 1, 1, rows), 1, 1)

    def select(self, name, rows):
        matched, review, unmentioned = [], [], []
        select_rows(name, 3, rows, matched, review, unmentioned)
        return matched, review, unmentioned

    def test_learning_filter_needs_exact_region_and_district(self):
        rows = [
            learning(),
            learning(region=" 경기도", district="안성시 "),
            learning(region="경기", name="안성 배움터"),
            learning(region="전라북도", district="무주군", name="안성면 배움터", address="무주군 안성면 1"),
            learning(district="평택시", address="경기도 안성시 합성로 3"),
            learning(district="평택시", name="평택 배움터", address="경기도 평택시 합성로 4"),
            learning(region=None, district=None, address=None),
            learning(region=unicodedata.normalize("NFD", "경기도"), district=unicodedata.normalize("NFD", "안성시")),
            # 시군구가 비거나 자리표시면 다른 열이 채워져 있어도 판정할 수 없다.
            learning(district=None, name="공도읍 행정복지센터", address=""),
            learning(region=None, district=" - ", name="안성 배움터", address=None),
            learning(region=None),
        ]
        matched, review, unmentioned = self.select("digital-learning", rows)
        self.assertEqual([(entry["page"], entry["position"]) for entry in matched], [(3, 1), (3, 2), (3, 8)])
        # NFC는 판정에만 쓰고 원문 값은 그대로 남긴다.
        self.assertEqual(matched[2]["match"]["fields"]["시군구"], unicodedata.normalize("NFD", "안성시"))
        self.assertEqual(matched[1]["match"]["fields"], {"관리지역": " 경기도", "시군구": "안성시 "})
        self.assertIs(matched[0]["record"], rows[0])
        self.assertEqual(matched[0]["missing"], [])
        self.assertEqual([(entry["position"], entry["reason"], entry["mentions"]) for entry in review], [
            (3, "mention", ["시군구", "배움터명", "배움터주소"]), (4, "mention", ["배움터명", "배움터주소"]),
            (5, "mention", ["배움터주소"]), (10, "blank_location", ["배움터명"]),
            (11, "mention", ["시군구", "배움터주소"])])
        self.assertIs(review[3]["record"], rows[9])
        # '안성' 표기가 없는 빈 행은 record 없이 위치만 남긴다.
        self.assertEqual(unmentioned, [{"page": 3, "position": 7}, {"page": 3, "position": 9}])

    def test_road_filter_uses_site_and_location(self):
        rows = [
            road(),
            road(site="경기도 평택시", location="평택시~안성시 구간"),
            road(site="경기도 평택시", location="평택시 일원", office="경기도 안성시 현장사무실",
                 title="안성시 방향 연결도로"),
            road(site="전라북도 무주군", location="무주군 안성면 일원"),
            road(site="경기 안성", location="일죽면 일원"),
            road(start=" ", end=None),
            {**road(site=None, location=""), "사업개요": "안성시 공도읍~양성면 확장", "노선명": "국도38호선(안성~평택)"},
            road(site=" ", location=None, office="경기도 안성시 현장사무실"),
            road(site=unicodedata.normalize("NFD", "경기도 안성시"), location="일원"),
            road(site="경기도 평택시", location=unicodedata.normalize("NFD", "무주군 안성면")),
            {**road(site="-", location="-"), "사업개요": "안성시 공도읍~양성면 확장"},
            {**road(site="경기도", location=None), "사업개요": "안성시 공도읍~양성면 확장"},
            {**road(site="경기도 평택시", location="평택시 일원"), "발주청": "안성시", "노선명": "안성~평택"},
            # 시공사·현장주소의 '안성'만으로는 검토로 넘기지 않는다.
            {**road(site="경기도 평택시", location="평택시 일원", office="경기도 안성시 1"), "시공사": "안성건설"},
            road(site=None, location="-"),
        ]
        matched, review, unmentioned = self.select("road-construction", rows)
        self.assertEqual([entry["position"] for entry in matched], [1, 2, 6, 9])
        self.assertEqual(matched[0]["match"]["fields"], {"주요사업지": "경기도 안성시", "공사위치": "안성시 합성면 일원"})
        self.assertEqual(matched[1]["match"]["fields"], {"공사위치": "평택시~안성시 구간"})
        self.assertEqual(matched[0]["missing"], ["준공일"])
        self.assertEqual(matched[2]["missing"], ["시작일", "준공일"])
        self.assertEqual((matched[2]["record"]["시작일"], matched[2]["record"]["준공일"]), (" ", None))
        # 판단 열이 모두 빈 행의 mentions는 모든 열에서 찾는다. 위치 열에 '안성'이 없으면 발주청·공사명·사업개요·노선명을 본다.
        self.assertEqual([(entry["position"], entry["reason"], entry["mentions"]) for entry in review], [
            (3, "other_mention", ["공사명"]), (4, "mention", ["공사위치"]), (5, "mention", ["주요사업지"]),
            (7, "blank_location", ["사업개요", "노선명"]), (8, "blank_location", ["현장주소"]),
            (10, "mention", ["공사위치"]), (11, "blank_location", ["사업개요"]),
            (12, "other_mention", ["사업개요"]), (13, "other_mention", ["발주청", "노선명"])])
        self.assertTrue(all(entry["record"] is rows[entry["position"] - 1] for entry in review))
        self.assertEqual(unmentioned, [{"page": 3, "position": 15}])

    def test_word_placeholders_count_as_blank(self):
        # '미정'·'해당없음'·'N/A' 같은 낱말 자리표시는 '-'와 같이 판정 열을 채우지 않는다.
        learning_rows = [
            learning(region=None, district="미정", name="공도읍 행정복지센터", address=None),
            learning(region=None, district=" 해당 없음 ", name="안성 배움터", address=None),
            learning(region=None, district="미정지구", name="공도읍 행정복지센터", address=None),
        ]
        matched, review, unmentioned = self.select("digital-learning", learning_rows)
        self.assertEqual(matched, [])
        self.assertEqual([(entry["position"], entry["reason"], entry["mentions"]) for entry in review],
                         [(2, "blank_location", ["배움터명"])])
        # 자리표시 집합에 없는 낱말은 채워진 값이라 판정 후 버린다.
        self.assertEqual(unmentioned, [{"page": 3, "position": 1}])
        road_rows = [
            road(site="미정", location="해당없음", office="경기도 안성시 현장"),
            road(site="N/A", location=None, office="경기도 안성시"),
            road(site="n / a", location="없음"),
            road(site="미상", location="-", start="미정", end="해당 없음"),
            road(start="미정", end="N/A"),
        ]
        matched, review, unmentioned = self.select("road-construction", road_rows)
        self.assertEqual([(entry["position"], entry["missing"]) for entry in matched], [(5, ["시작일", "준공일"])])
        self.assertEqual((matched[0]["record"]["시작일"], matched[0]["record"]["준공일"]), ("미정", "N/A"))
        self.assertEqual([(entry["position"], entry["reason"], entry["mentions"]) for entry in review],
                         [(1, "blank_location", ["현장주소"]), (2, "blank_location", ["현장주소"])])
        self.assertEqual(unmentioned, [{"page": 3, "position": 3}, {"page": 3, "position": 4}])


class OdcloudCollectionTest(unittest.TestCase):
    def setUp(self):
        self.private = Path(self.enterContext(TemporaryDirectory())).resolve() / "private"
        self.root = self.private / "collection-odcloud"
        self.bundle = self.root / "run"
        self.pages = [
            envelope(1, 2, 3, [road(), road(site="충청북도 진천군", location="진천군 일원")]),
            envelope(2, 2, 3, [road(site="전라북도 무주군", location="무주군 안성면", start="", end="")]),
        ]
        self.fetch = self.enterContext(patch.object(odcloud, "fetch_odcloud_page", side_effect=self.pages))
        self.enterContext(patch.object(odcloud, "PAGE_SIZE", 2))
        self.sleep = self.enterContext(patch.object(odcloud, "sleep"))

    def collect(self, name="road-construction"):
        return odcloud.collect_odcloud(name, "run", self.root, _KEY)

    def receipt(self):
        return json.loads((self.bundle / "odcloud.json").read_bytes())

    def test_snapshot_keeps_raw_pages_and_selection(self):
        self.assertEqual(self.collect(), {"snapshot_id": "run", "status": "complete", "pages": 2, "rows": 3})
        self.sleep.assert_called_once_with(0.6)
        selection, receipt = odcloud.read_odcloud_snapshot(self.private, "run")
        self.assertEqual((receipt["swagger_url"], receipt["catalog_url"]), (
            "https://infuser.odcloud.kr/oas/docs?namespace=15052289/v1",
            "https://www.data.go.kr/data/15052289/fileData.do"))
        for index, (entry, raw) in enumerate(zip(receipt["responses"], self.pages), 1):
            self.assertEqual((self.bundle / f"page-{index}.json").read_bytes(), raw)
            self.assertEqual(entry["sha256"], hashlib.sha256(raw).hexdigest())
            self.assertEqual(entry["source_url"], odcloud.page_source("road-construction", index, 2))
        document = json.loads(selection)
        self.assertEqual(document["rule"], "주요사업지 또는 공사위치에 '안성시' 포함")
        self.assertEqual([(row["page"], row["position"]) for row in document["rows"]], [(1, 1)])
        self.assertEqual(document["rows"][0]["record"], road())
        self.assertEqual([(row["page"], row["mentions"]) for row in document["needs_review"]], [(2, ["공사위치"])])
        self.assertEqual(document["blank_location_unmentioned"], [])
        self.assertEqual((receipt["selection"]["rows"], receipt["selection"]["needs_review"],
                          receipt["selection"]["blank_location_unmentioned"]), (1, 1, 0))
        for path in self.bundle.iterdir():
            self.assertNotIn(_KEY.encode(), path.read_bytes())
            self.assertNotIn(_ENCODED_KEY.encode(), path.read_bytes())
        self.assertEqual(self.bundle.stat().st_mode & 0o777, 0o700)
        with self.assertRaisesRegex(ValueError, "이미 사용"):
            self.collect()
        self.assertEqual(self.fetch.call_count, 2)

    def test_failures_keep_raw_pages_and_reason(self):
        changed = envelope(2, 2, 4, [road(), road(title="다른 공사")])
        first_rows = json.loads(self.pages[0])["data"]
        repeated_first = envelope(1, 2, 4, first_rows)
        # 열 순서만 바꾼 같은 행 묶음도 반복으로 본다.
        repeated = envelope(2, 2, 4, [dict(reversed(row.items())) for row in first_rows])
        for label, responses, reason in (
            ("total changed", [self.pages[0], changed], "전체 건수가 달라"),
            ("repeated page", [repeated_first, repeated], "앞 페이지의 행"),
            # 정렬이 흔들려 앞 페이지 행이 다시 오고 다른 행이 빠진 경우
            ("unstable paging", [self.pages[0], envelope(2, 2, 3, [road()])], "빠진 행"),
            ("zero total", [envelope(1, 2, 0, [])], "0건"),
            ("over cap", [envelope(1, 2, 41, [road(), road()])], "한도"),
            ("envelope", [envelope(1, 2, 3, [road()])], "행 개수"),
            ("http", [self.pages[0], ValueError("파일데이터 API HTTP 응답 오류(500).")], "HTTP 응답 오류"),
        ):
            with self.subTest(label), TemporaryDirectory() as temp:
                root = Path(temp).resolve() / "collection-odcloud"
                self.fetch.side_effect = responses
                summary = odcloud.collect_odcloud("road-construction", "run", root, _KEY)
                self.assertEqual(summary["status"], "failed")
                receipt = json.loads((root / "run" / "odcloud.json").read_bytes())
                self.assertIn(reason, receipt["error"])
                self.assertNotIn("selection", receipt)
                self.assertFalse((root / "run" / "anseong.json").exists())
                for index, raw in enumerate(r for r in responses if isinstance(r, bytes)):
                    self.assertEqual((root / "run" / f"page-{index + 1}.json").read_bytes(), raw)

    def test_same_row_within_one_page_is_kept(self):
        # 한 응답 안의 같은 행은 원본 자료의 중복일 수 있어 그대로 둔다.
        self.fetch.side_effect = [envelope(1, 2, 3, [road(), road()]), self.pages[1]]
        self.assertEqual(self.collect()["status"], "complete")
        selection, _ = odcloud.read_odcloud_snapshot(self.private, "run")
        self.assertEqual([row["position"] for row in json.loads(selection)["rows"]], [1, 2])

    def test_blank_rows_without_mention_keep_only_position(self):
        # 전국 10,000행이 모두 위치가 비어도 record를 담지 않아 선택 결과가 8 MiB를 넘지 않는다.
        overview = "합성 사업개요 " * 12
        pages = [envelope(page, 500, 10_000, [
            {**road(site=None, location="", office="부산광역시 합성구 합성로 1", title=f"합성 공사 {page}-{position}"),
             "사업개요": overview} for position in range(1, 501)]) for page in range(1, 21)]
        self.fetch.side_effect = pages
        with patch.object(odcloud, "PAGE_SIZE", 500):
            self.assertEqual(self.collect()["status"], "complete")
            selection, receipt = odcloud.read_odcloud_snapshot(self.private, "run")
        document = json.loads(selection)
        self.assertEqual((document["rows"], document["needs_review"]), ([], []))
        self.assertEqual(len(document["blank_location_unmentioned"]), 10_000)
        self.assertEqual(document["blank_location_unmentioned"][-1], {"page": 20, "position": 500})
        self.assertEqual(receipt["selection"]["blank_location_unmentioned"], 10_000)
        self.assertLess(len(selection), 1024 * 1024)

    def test_failed_snapshot_is_not_readable(self):
        self.fetch.side_effect = [self.pages[0], envelope(2, 2, 4, [road(), road(title="다른 공사")])]
        self.collect()
        with self.assertRaisesRegex(ValueError, "완료된"):
            odcloud.read_odcloud_snapshot(self.private, "run")

    def test_missing_key_or_bad_name_creates_nothing(self):
        for name, key in (("run", ""), ("../run", _KEY)):
            with self.subTest(name=name), self.assertRaises(ValueError):
                odcloud.collect_odcloud("road-construction", name, self.root, key)
        with self.assertRaises(ValueError):
            odcloud.collect_odcloud("unknown", "run", self.root, _KEY)
        self.assertFalse(self.root.exists())
        self.fetch.assert_not_called()

    def test_tampered_archive_is_rejected(self):
        self.collect()
        for filename, bad in (
            ("page-1.json", self.pages[0].replace("진천군 일원".encode(), "안성시 일원".encode())),
            ("anseong.json", b'{"rows": []}\n'),
        ):
            with self.subTest(filename=filename):
                asset = self.bundle / filename
                initial = asset.read_bytes()
                asset.write_bytes(bad)
                with self.assertRaises(ValueError):
                    odcloud.read_odcloud_snapshot(self.private, "run")
                asset.write_bytes(initial)
        initial = (self.bundle / "odcloud.json").read_bytes()
        for change in (
            lambda r: r["selection"].update(rows=2),
            lambda r: r.update(swagger_url="https://example.invalid"),
            lambda r: r.update(dataset="digital-learning"),
            lambda r: r["responses"][1].update(source_url=r["responses"][1]["source_url"] + "&serviceKey=x"),
            lambda r: r["responses"][0].update(rows=1),
            lambda r: r["responses"][0].update(fetched_at="2026-02-30T00:00:00Z"),
            lambda r: r.update(rows=2),
            lambda r: r.update(endpoint=r["endpoint"].replace("uddi:", "uddi:x", 1)),
        ):
            receipt = json.loads(initial)
            change(receipt)
            (self.bundle / "odcloud.json").write_text(json.dumps(receipt, ensure_ascii=False))
            with self.assertRaises(ValueError):
                odcloud.read_odcloud_snapshot(self.private, "run")
        # 같은 자료의 다른 uddi로 받은 보관본은 변조와 구별되는 오류로 다시 수집을 안내한다.
        for endpoint, reason in (
            ("https://api.odcloud.kr/api/15052289/v1/uddi:00000000-0000-4000-8000-000000000000", "다시 수집"),
            ("https://api.odcloud.kr/api/15134509/v1/uddi:b87e06b5-9a2a-4627-a3b3-c7a850904a62", "확인할 수 없습니다"),
        ):
            receipt = json.loads(initial)
            receipt["endpoint"] = endpoint
            (self.bundle / "odcloud.json").write_text(json.dumps(receipt, ensure_ascii=False))
            with self.subTest(endpoint=endpoint), self.assertRaisesRegex(ValueError, reason):
                odcloud.read_odcloud_snapshot(self.private, "run")
        (self.bundle / "odcloud.json").write_bytes(initial)
        odcloud.read_odcloud_snapshot(self.private, "run")

    def review(self, *extra, **document):
        path = self.private / "review.json"
        path.write_text(json.dumps({
            "archive_kind": "odcloud", "archive_name": "run", "data_kind": "synthetic",
            "documents": [{
                "asset": "1", "official_url": odcloud.page_source("road-construction", 1, 2),
                "publisher": "합성 기관", "document_id": "40000000-0000-4000-8000-000000000002",
                "document_version_id": "50000000-0000-4000-8000-000000000002", "version_no": 1,
                "title": "검토한 공사", "official_number": None, "published_date": None, "collected_at": None,
                "cleaned_text": "검토한 공사 정보", "redaction_log": [], **document, **changes,
            } for changes in ({}, *extra)],
        }, ensure_ascii=False))
        return path

    def test_d03_prepares_raw_page_and_rejects_tampering(self):
        self.collect()
        self.assertEqual(prepare(self.review(), "prepared", self.private)["documents"], 1)
        doc, = json.loads((self.private / "collection-d03" / "prepared" / "source-import.json").read_bytes())["documents"]
        self.assertEqual(doc["raw_asset_path"], "collection-odcloud/run/page-1.json")
        self.assertEqual(doc["raw_sha256"], hashlib.sha256(self.pages[0]).hexdigest())
        self.assertEqual(doc["collection_method"], "data-go-kr-odcloud-api")
        self.assertEqual(doc["collected_at"], self.receipt()["responses"][0]["fetched_at"].replace("+00:00", "Z"))
        self.assertEqual((doc["use_review"], doc["check_result"]), ("pending", "unchecked"))
        for keys, reason in (({"portal"}, "응답 페이지"), ({"3"}, "응답 페이지")):
            with self.subTest(keys=keys), self.assertRaisesRegex(ValueError, reason):
                capture_assets(self.private, "odcloud", "run", keys)
        with self.assertRaises(ValueError):
            prepare(self.review(official_url=odcloud.page_source("road-construction", 2, 2)), "wrong-url", self.private)
        # 한 응답 페이지의 안성시 행 여러 개를 각각 문서로 등록할 수 있다.
        second = {"document_id": "40000000-0000-4000-8000-000000000003",
                  "document_version_id": "50000000-0000-4000-8000-000000000003", "title": "검토한 다른 공사"}
        self.assertEqual(prepare(self.review(second), "shared-page", self.private)["documents"], 2)
        shared = json.loads((self.private / "collection-d03" / "shared-page" / "source-import.json").read_bytes())
        self.assertEqual({(doc["raw_asset_path"], doc["raw_sha256"]) for doc in shared["documents"]},
                         {("collection-odcloud/run/page-1.json", hashlib.sha256(self.pages[0]).hexdigest())})
        with self.assertRaisesRegex(ValueError, "document_id"):
            prepare(self.review({"document_version_id": second["document_version_id"]}), "same-doc", self.private)
        (self.bundle / "page-2.json").write_bytes(self.pages[1].replace(b'"page": 2', b'"page": 2 '))
        with self.assertRaisesRegex(ValueError, "해시"):
            prepare(self.review(), "tampered", self.private)
        self.assertFalse((self.private / "collection-d03" / "tampered").exists())


    def test_learning_snapshot_round_trips_to_d03(self):
        rows = [learning(), learning(district="평택시", name="평택 배움터", address="경기도 평택시 합성로 4")]
        page = envelope(1, 2, 2, rows)
        self.fetch.side_effect = [page]
        self.assertEqual(self.collect("digital-learning"), {"snapshot_id": "run", "status": "complete", "pages": 1, "rows": 2})
        selection, receipt = odcloud.read_odcloud_snapshot(self.private, "run")
        self.assertEqual((self.bundle / "anseong.json").read_bytes(), selection)
        document = json.loads(selection)
        self.assertEqual((document["dataset"], document["category"], document["needs_review"]),
                         ("digital-learning", "education", []))
        entry, = document["rows"]
        self.assertEqual(entry["match"], {"rule": "관리지역=경기도 그리고 시군구=안성시",
                                          "fields": {"관리지역": "경기도", "시군구": "안성시"}})
        # 정수 이용정원이 문자열·실수로 바뀌지 않고 원문 그대로 남는다.
        self.assertEqual(entry["record"], learning())
        self.assertIs(type(entry["record"]["이용정원"]), int)
        self.assertEqual((entry["page"], entry["position"], entry["missing"]), (1, 1, []))
        self.assertEqual(receipt["selection"]["rows"], 1)
        source_url = odcloud.page_source("digital-learning", 1, 2)
        self.assertEqual(prepare(self.review(official_url=source_url, title="합성 배움터"), "learning",
                                 self.private)["documents"], 1)
        doc, = json.loads((self.private / "collection-d03" / "learning" / "source-import.json").read_bytes())["documents"]
        self.assertEqual((doc["raw_asset_path"], doc["raw_sha256"], doc["official_url"], doc["collection_method"]), (
            "collection-odcloud/run/page-1.json", hashlib.sha256(page).hexdigest(), source_url, "data-go-kr-odcloud-api"))
        self.assertEqual(doc["collected_at"], receipt["responses"][0]["fetched_at"].replace("+00:00", "Z"))


class OdcloudCliTest(unittest.TestCase):
    def run_main(self, argv, env):
        with (patch("sys.argv", ["odcloud", *argv]), patch.dict("os.environ", env, clear=True),
              contextlib.redirect_stderr(io.StringIO()) as error, contextlib.redirect_stdout(io.StringIO()) as out):
            return odcloud.main(), error.getvalue(), out.getvalue()

    def test_exit_codes(self):
        with TemporaryDirectory() as temp, patch.object(odcloud, "ODCLOUD_ROOT", Path(temp).resolve() / "odcloud"):
            with patch.object(odcloud, "fetch_odcloud_page", side_effect=AssertionError("요청 금지")):
                code, error, _ = self.run_main(["digital-learning", "--name", "run"], {})
            self.assertEqual(code, 1)
            self.assertIn("서비스 키", error)
            with patch.object(odcloud, "fetch_odcloud_page", return_value=envelope(1, 500, 1, [learning()])):
                code, _, out = self.run_main(["digital-learning", "--name", "ok"], {odcloud.SERVICE_KEY_ENV: _KEY})
            self.assertEqual((code, json.loads(out)["status"]), (0, "complete"))
            with patch.object(odcloud, "fetch_odcloud_page", return_value=b"{}"):
                code, _, out = self.run_main(["digital-learning", "--name", "bad"], {odcloud.SERVICE_KEY_ENV: _KEY})
            self.assertEqual((code, json.loads(out)["status"]), (2, "failed"))


if __name__ == "__main__":
    unittest.main()
