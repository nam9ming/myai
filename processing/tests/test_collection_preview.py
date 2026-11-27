import hashlib
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from processing.collection.__main__ import preview, read_input


class CollectionPreviewTest(unittest.TestCase):
    def setUp(self):
        self.event = {
            "title": "합성 시민 행사",
            "official_url": "https://example.invalid/events/12",
            "fields": {"start_date": "2026-11-01", "end_date": "2026-11-02", "place": "제1공간"},
        }

    def test_event_match_keeps_conflicting_fields_and_both_inputs(self):
        web = {**self.event, "fields": {**self.event["fields"], "place": "제2공간"}}
        result = preview("culture", [self.event], web, "a" * 64, "b" * 64)
        self.assertEqual(result["relationship"], {
            "state": "candidate", "portal_indexes": [0],
            "conflicts": {"place": {"portal": "제1공간", "web": "제2공간"}},
        })
        self.assertEqual(result["portal"]["sha256"], "a" * 64)
        self.assertEqual(result["web"]["record"]["fields"]["place"], "제2공간")

    def test_missing_link_and_duplicate_portal_rows_stay_unresolved(self):
        no_link = {**self.event, "official_url": None}
        self.assertEqual(preview("culture", [self.event], no_link, "", "")["relationship"]["state"], "unresolved")
        self.assertEqual(preview("culture", [self.event, self.event], self.event, "", "")["relationship"]["state"], "ambiguous")

    def test_library_links_are_candidates_and_baseline_is_kept(self):
        portal = [{"title": "테스트시 가 도서관", "fields": {"weekday_open": "09:00"}}]
        notice = {"title": "테스트시 가 도서관 임시 휴관", "fields": {"description": "시설 점검"}}
        result = preview("living", portal, notice, "", "")
        self.assertEqual(result["relationship"]["portal_indexes"], [0])
        self.assertEqual(result["portal"]["records"][0]["fields"]["weekday_open"], "09:00")
        unknown = {"title": "관내 도서관 안내", "fields": {"description": "일부 시설 휴관"}}
        self.assertEqual(preview("living", portal, unknown, "", "")["relationship"]["state"], "unresolved")
        embedded = {"title": "테스트시 가 도서관별 안내", "fields": {"description": "시설 점검"}}
        self.assertEqual(preview("living", portal, embedded, "", "")["relationship"]["state"], "unresolved")

    def test_raw_hash_includes_utf8_bom_and_input_has_size_limit(self):
        raw = "제목".encode("utf-8-sig")
        with TemporaryDirectory() as work:
            path = Path(work) / "sample.csv"
            path.write_bytes(raw)
            self.assertEqual(read_input(path, len(raw), "시험"), ("제목", hashlib.sha256(raw).hexdigest()))
            with self.assertRaisesRegex(ValueError, "허용 크기"):
                read_input(path, len(raw) - 1, "시험")

    def test_event_preview_cli_reads_two_source_files(self):
        with TemporaryDirectory() as work:
            folder = Path(work)
            portal = folder / "portal.csv"
            portal.write_text(
                "축제명,개최장소,축제시작일자,축제종료일자,소재지도로명주소,"
                "소재지지번주소,주최기관명,홈페이지주소\n"
                "합성 시민 행사,제1공간,2026-11-01,2026-11-02,경기도 안성시 시험로 1,"
                ",경기도 안성시,https://example.invalid/events/12\n",
                encoding="utf-8",
            )
            detail = folder / "web.json"
            detail.write_text(json.dumps({
                "idx": 12, "title": "합성 시민 행사", "eventSdate": "2026-11-01",
                "eventEdate": "2026-11-02", "eventFee": "0", "eventPlace": "제2공간",
                "url": "https://example.invalid/events/12",
            }, ensure_ascii=False), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, "-B", "-m", "processing.collection", "culture",
                 "--portal-csv", str(portal), "--web-detail", str(detail), "--web-id", "12"],
                capture_output=True, text=True, timeout=10,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data["relationship"]["state"], "candidate")
        self.assertEqual(data["web"]["record"]["fields"]["fee"], "0")
        self.assertEqual(data["relationship"]["conflicts"]["place"]["web"], "제2공간")

    def test_library_preview_cli_keeps_attachment_review_flag(self):
        with TemporaryDirectory() as work:
            folder = Path(work)
            portal = folder / "portal.csv"
            portal_bytes = "도서관명,시도명,시군구명\n합성도서관,경기도,안성시\n".encode("euc-kr")
            portal.write_bytes(portal_bytes)
            detail = folder / "web.html"
            detail.write_text(
                '<input type="hidden" name="bIdx" value="77">'
                '<div class="bod_view"><h4>합성도서관 공지</h4>'
                '<div class="view_cont"><p>시설 점검 안내</p></div>'
                '<dl class="view_file"><dd><a href="/notice.hwpx">한글 문서</a></dd></dl></div>',
                encoding="utf-8",
            )
            result = subprocess.run(
                [sys.executable, "-B", "-m", "processing.collection", "living",
                 "--portal-csv", str(portal), "--web-detail", str(detail), "--web-id", "77"],
                capture_output=True, text=True, timeout=10,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data["relationship"]["portal_indexes"], [0])
        self.assertEqual(data["portal"]["sha256"], hashlib.sha256(portal_bytes).hexdigest())
        self.assertEqual(data["web"]["record"]["review_flags"], ["attachment"])


if __name__ == "__main__":
    unittest.main()
