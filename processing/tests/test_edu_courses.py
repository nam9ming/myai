import contextlib
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from processing.collection.edu_course_batch import (
    COURSE_SECTION, capture_course_batch, main, read_course_batch,
)
from processing.collection.edu_courses import (
    detail_url, fetch_detail, fetch_listing, parse_course_detail, parse_course_listing,
)


_ORIGIN = "https://www.anseong.go.kr"
_VIEW = "/edu/portal/edu/eduLctre/eduLctreView.do"
_IMAGE = "/edu/common/imgView.do?attachId=" + "a" * 64 + "&amp;fileSn=" + "b" * 32 + "&amp;mode=ratioView"
_DOWNLOAD = f"fn_egov_downFile('{'c' * 64}','{'d' * 32}'); return false;"


def _config(context="/edu"):
    return f'<script>\n\tvar yh = {{\n\t\t"mId": "1400000000",\n\t\t"contextPath": "{context}"\n\t}};\n</script>'


def _qr(url):
    return f'<script>$(document).ready(function() {{ $("#contentsQrcode").qrcode("{url}"); }});</script>'


def _slides(items=""):
    return (f'<div class="updateFileList"><div class="file_slide"><div class="file_slide_list">{items}</div>'
            '<div class="file_slide_control"><button type="button" class="file_slide_prev"><span>이전</span></button>'
            '</div></div></div>')


_PHOTO = (f'<div class="file_slide_item"><a href="/edu/DATA/EDU/PLACE/ratio/PLACE_1_ratio_.jpg" '
          f'class="file_slide_anchor" target="_blank"><img src="{_IMAGE}" alt="교육동 외관.jpg"></a></div>')
_ATTACHMENT = (f'<div id="updateFileList"><a href="#" onclick="{_DOWNLOAD}"><span class="skip">파일 다운로드</span> '
               '강의계획서.hwp</a></div><!--<ul id="updateFileList"><li>예전 목록</li></ul>-->')
_ROWS = {
    "접수기간": "2026-11-18 09:00 ~ 2026-12-18 17:00",
    "접수현황": ('\n<span>신청 <em class="em_b_black">6</em>명 / 모집인원 <em class="em_b_black">50</em>명</span>\n'
             '\t<span class="mL20">(대기신청 <em class="em_b_black">0</em>명 / 대기정원 <em>10</em>명)</span>\n'),
    "선발방법": "\n\t\t\n\t\t선착순\n\t",
    "교육기간": "2026-12-19 ~ 2026-12-19",
    "교육시간": ('\n\t\t화<span class="mL5 mR5">/</span>14:00 ~ 16:00\n'
             '\t\t<br />목<span class="mL5 mR5">/</span>14:00 ~ 16:00\n'),
    "교육장": '<span style="vertical-align:middle" class="mR10"> 시험교육장 (경기도 안성시 시험로 1 )</span>',
    "교육장 사진": _slides(_PHOTO),
    "강사명": '\n\t<a href="/edu/portal/instrctr/selectInstrctrView.do?mId=0802020000&amp;instrctrNo=1">홍길동</a>\n',
    "수강료": "\n\t\t48,000 원\n\t&nbsp;( 100000 )\n",
    "문의전화": "031-000-0000",
    "강의계획서 및 이미지": _slides() + _ATTACHMENT,
    "강좌소개": "첫 줄<br/><br/>대상: 시험 &lt;안내&gt;",
    "유의사항": "",
}


def _detail(course="5086", *, title="[12월] 시험 강좌", state="접수중", context="/edu", echo=None, **rows):
    cells = {**_ROWS, **{label.replace("_", " "): value for label, value in rows.items()}}
    body = "".join(f"<dl>\n<dt>{label}</dt>\n<dd>{value}</dd>\n</dl>" for label, value in cells.items()
                   if value is not None)
    stale = f"{_ORIGIN}{_VIEW}?mId=1400000000&eduLctreNo=3203&eduInsttNo=7&page=1&searchTxt="
    return (f"<!DOCTYPE html><html><head><title>수강신청</title>{_config(context)}</head><body><header>"
            f"{_qr(echo or detail_url(course))}</header>{_qr(stale)}"
            f'<div id="learning_cont" class="learning_content"><div class="bod_title">'
            f'<span class="bod_state_type">{state}</span><span class="bod_subject">{title}</span>'
            f'<span class="bod_btn">일반 회원으로 로그인하세요.</span></div>'
            f'<div class="bod_write">{body}</div><div class="btn_wrap mT50"><a href="/edu/x">목록</a></div>'
            "</div></body></html>")


def _row(course, number=1, extra=""):
    link = f"{_VIEW}?mId=1400000000&amp;eduLctreNo={course}&amp;page=1&amp;searchTxt="
    status = f"{_VIEW}?mId=1400000000&amp;page=1&amp;eduLctreNo={course}&amp;searchTxt="
    return (f'<tr><td>{number}</td><td>기타<br />()</td><td class="text_left"><a href="{link}">강좌</a></td>'
            f'<td>무료</td><td><a href="{status}" class="btn xsmall type3">접수중</a>{extra}</td></tr>')


def _listing(*courses, current=1, total=2, caption="수강신청 목록 - 번호, 교육강좌명 순으로 정보제공", rows=None):
    rows = rows if rows is not None else "".join(_row(course) for course in courses)
    return (f"<html><head>{_config()}</head><body>"
            '<form id="list" action="/edu/portal/edu/eduLctre/selectEduLctreWebList.do" method="get">'
            f'<input type="hidden" name="page" value="{current}" /></form>'
            f'<div class="bod_head"><p class="page_num">전체 <b>12</b>건 [ <b>{current}</b> / {total}페이지 ]</p></div>'
            f'<table class="bod_maintain"><caption>{caption}</caption><thead><tr><th>번호</th></tr></thead>'
            f"<tbody>{rows}</tbody></table></body></html>").encode()


class CourseListingTest(unittest.TestCase):
    def test_listing_returns_pages_and_ids_in_order(self):
        self.assertEqual(parse_course_listing(_listing("5094", "5086", "5085", current=2), page=2),
                         (2, ["5094", "5086", "5085"]))

    def test_listing_rejects_mismatch_or_format_change(self):
        other_link = '<a href="/edu/portal/edu/eduInstt/x.do?mId=1400000000">기관</a>'
        cases = [
            ("페이지 번호", _listing("1", current=2)),
            ("같은 강좌", _listing("1", "1")),
            ("구조", _listing("1", caption="기관 목록")),
            ("구조", _listing(rows="")),
            ("구조", _listing(rows=_row("1", extra=other_link))),
            ("구조", _listing(rows=_row("1").replace("eduLctreNo=1&amp;page", "eduLctreNo=2&amp;page", 1))),
            ("구조", _listing(rows=_row("01"))),
        ]
        for number, (message, raw) in enumerate(cases):
            with self.subTest(case=number), self.assertRaisesRegex(ValueError, message):
                parse_course_listing(raw, page=1)


class CourseDetailTest(unittest.TestCase):
    def test_detail_keeps_displayed_text_and_separate_schedules(self):
        record = parse_course_detail(_detail(), course_id="5086")
        self.assertEqual(record["official_url"], f"{_ORIGIN}{_VIEW}?eduLctreNo=5086&mId=1400000000")
        self.assertEqual((record["external_id"], record["title"]), ("5086", "[12월] 시험 강좌"))
        self.assertEqual(record["fields"], {
            "reception_status": "접수중",
            "application_period": "2026-11-18 09:00 ~ 2026-12-18 17:00",
            "enrollment_status": "신청 6명 / 모집인원 50명 (대기신청 0명 / 대기정원 10명)",
            "selection_method": "선착순",
            "course_period": "2026-12-19 ~ 2026-12-19",
            "course_schedule": "화/14:00 ~ 16:00\n목/14:00 ~ 16:00",
            "venue": "시험교육장 (경기도 안성시 시험로 1 )",
            "instructor": "홍길동",
            "fee": "48,000 원 ( 100000 )",
            "contact_phone": "031-000-0000",
            "description": "첫 줄\n대상: 시험 <안내>",
            "notes": None,
        })
        self.assertEqual(record["media"], [
            {"field": "venue_photos", "kind": "image", "label": "교육동 외관.jpg",
             "url": f"{_ORIGIN}{_IMAGE.replace('&amp;', '&')}"},
            {"field": "course_materials", "kind": "attachment", "label": "강의계획서.hwp",
             "url": f"{_ORIGIN}/edu/cmm/fms/FileDown.do?atchFileId={'c' * 64}&fileSn={'d' * 32}"},
        ])
        self.assertEqual(record["review_flags"], ["attachment:course_materials", "image:venue_photos", "missing:notes"])

    def test_free_and_blank_fees_are_kept_apart(self):
        free = parse_course_detail(_detail("1", 수강료="\n\t무료\n"), course_id="1")
        blank = parse_course_detail(_detail("1", 수강료="\n\t\n"), course_id="1")
        self.assertEqual((free["fields"]["fee"], blank["fields"]["fee"]), ("무료", None))
        self.assertNotIn("missing:fee", free["review_flags"])
        self.assertIn("missing:fee", blank["review_flags"])

    def test_end_br_breaks_line_like_browser(self):
        record = parse_course_detail(_detail(교육시간="화/14:00 ~ 16:00</br>목/14:00 ~ 16:00"), course_id="5086")
        self.assertEqual(record["fields"]["course_schedule"], "화/14:00 ~ 16:00\n목/14:00 ~ 16:00")

    def test_sessions_with_the_same_title_stay_distinct(self):
        first = parse_course_detail(_detail("5085", 교육기간="2026-12-12 ~ 2026-12-12"), course_id="5085")
        second = parse_course_detail(_detail("5086"), course_id="5086")
        self.assertEqual(first["title"], second["title"])
        self.assertNotEqual((first["external_id"], first["official_url"], first["fields"]["course_period"]),
                            (second["external_id"], second["official_url"], second["fields"]["course_period"]))

    def test_detail_rejects_other_course_site_or_format(self):
        cases = [
            ("강좌 번호", _detail(echo=detail_url("5085"))),
            ("사이트 경로", _detail(context="")),
            ("알 수 없는 항목", _detail(대상="성인")),
            ("빠진 항목", _detail(교육장=None)),
            ("교육시간 칸 형식", _detail(교육시간="<div>화</div>")),
            ("구조", _detail(교육장_사진="<p>사진 설명</p>")),
            ("구조", _detail(교육장_사진="사진 설명")),
            ("구조", _detail(교육장='<span class="mR10" class="blind">시험교육장</span>')),
            ("구조", "<script>alert('잘못된 접근입니다.');</script>"),
            ("화면 표시", _detail(교육장="<span hidden>숨은 교육장</span>")),
            ("화면 표시", _detail(수강료='<span style="display:none">무료</span>')),
            ("화면 표시", _detail(수강료='<span class="blind">유료 </span>무료')),
            ("화면 표시", _detail(수강료='<a href="#" onclick="x()"><span class="skip">유료 </span>무료</a>')),
            ("화면 표시", _detail(title='<span class="blind">[취소] </span>강좌')),
            ("화면 표시", _detail().replace("<dl>", '<dl class="blind">', 1)),
            ("구조", _detail().replace('<div class="bod_write">', '<div class="bod_write">※ 유료로 변경되었습니다.')),
            ("구조", _detail().replace("<dt>수강료</dt>", "<dt>수강료</dt>(재료비 별도)")),
            ("구조", _detail().replace('<div class="bod_title">', '<div class="bod_title">[숨김접두]')),
            ("강좌명", _detail(title="")),
            ("해석이 갈리는", _detail(강좌소개="<!--->숨김-->")),
        ]
        for number, (message, text) in enumerate(cases):
            with self.subTest(case=number), self.assertRaisesRegex(ValueError, message):
                parse_course_detail(text, course_id="5086")

    @patch("processing.collection.official_web.HTTPSConnection")
    def test_requests_use_fixed_edu_paths(self, connect):
        response = connect.return_value.getresponse.return_value.__enter__.return_value
        response.status, response.getheader.return_value, response.read.return_value = 200, None, b"ok"
        fetch_listing(3, limit=64)
        fetch_detail("5086", limit=64)
        self.assertEqual([call.args for call in connect.return_value.request.call_args_list], [
            ("GET", "/edu/portal/edu/eduLctre/selectEduLctreWebList.do?mId=1400000000&page=3"),
            ("GET", f"{_VIEW}?eduLctreNo=5086&mId=1400000000"),
        ])
        response.status = 404
        with self.assertRaisesRegex(ValueError, "안성배움e 강좌 HTTP 응답 오류\\(404\\)"):
            fetch_detail("5086", limit=64)
        for value in ("0", "05", "1" * 19, "1a"):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "강좌 번호"):
                detail_url(value)


class CourseBatchTest(unittest.TestCase):
    def setUp(self):
        self.private = Path(self.enterContext(TemporaryDirectory())).resolve()
        self.root = self.private / COURSE_SECTION
        self.enterContext(patch("processing.collection.edu_course_batch.sleep"))
        self.listing = self.enterContext(patch("processing.collection.edu_course_batch.fetch_listing"))
        self.detail = self.enterContext(patch("processing.collection.edu_course_batch.fetch_detail"))
        self.detail.side_effect = lambda course, **_options: _detail(course).encode()

    def test_batch_keeps_raw_and_reads_back_checked_records(self):
        self.listing.side_effect = [_listing("5086", "5085", total=2), _listing("4673", current=2, total=2)]
        summary = capture_course_batch("run", self.root)
        self.assertEqual(summary, {"batch_id": "run", "status": "complete", "discovery_status": "complete",
                                   "selected": 3, "parsed": 3})
        receipt = json.loads((self.root / "run" / "batch.json").read_text(encoding="utf-8"))
        self.assertEqual(receipt["schema_version"], "citizen-edu-course-batch-v1")
        self.assertEqual(receipt["pages"][1]["source_url"],
                         f"{_ORIGIN}/edu/portal/edu/eduLctre/selectEduLctreWebList.do?mId=1400000000&page=2")
        self.assertEqual((self.root / "run" / "detail-5085.html").read_bytes(), _detail("5085").encode())

        courses = read_course_batch(self.private, "run", {"5085", "5086"})
        self.assertEqual(courses["5085"]["record"], parse_course_detail(_detail("5085"), course_id="5085"))
        self.assertEqual(courses["5086"]["raw_asset_path"], "collection-edu-courses/run/detail-5086.html")
        self.assertEqual(courses["5086"]["official_url"], detail_url("5086"))

        parsed = self.root / "run" / "parsed-5086.json"
        original = parsed.read_bytes()
        for changed, message in ((original.replace(b"edu-course-parser-v2", b"edu-course-parser-v1"), "파서 버전"),
                                 (original.replace("선착순".encode(), "추첨".encode()), "파싱 결과")):
            parsed.chmod(0o600)
            parsed.write_bytes(changed)
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                read_course_batch(self.private, "run", {"5086"})
        parsed.write_bytes(original)
        (self.root / "run" / "detail-5086.html").write_bytes(_detail("5086", state="접수마감").encode())
        with self.assertRaisesRegex(ValueError, "해시"):
            read_course_batch(self.private, "run", {"5086"})

    def test_failed_detail_keeps_raw_and_reason(self):
        self.listing.return_value = _listing("5086", "1", total=1)
        alert = b"<script>alert('x');</script>"
        self.detail.side_effect = lambda course, **_options: alert if course == "1" else _detail(course).encode()
        summary = capture_course_batch("run", self.root)
        receipt = json.loads((self.root / "run" / "batch.json").read_text(encoding="utf-8"))
        self.assertEqual((summary["status"], summary["parsed"]), ("partial", 1))
        self.assertEqual(receipt["items"][1]["status"], "parse_failed")
        self.assertIn("구조", receipt["items"][1]["error"])
        self.assertEqual((self.root / "run" / "detail-1.html").read_bytes(), alert)
        with self.assertRaisesRegex(ValueError, "파싱이 완료된"):
            read_course_batch(self.private, "run", {"1"})

    def test_cli_exit_codes(self):
        self.listing.return_value = _listing("5086", total=1)
        with (patch("processing.collection.edu_course_batch.COURSE_ROOT", self.root),
              patch("sys.argv", ["edu_course_batch", "--name", "cli"]),
              contextlib.redirect_stdout(io.StringIO()) as output):
            self.assertEqual(main(), 0)
            self.assertEqual(json.loads(output.getvalue())["parsed"], 1)
            with contextlib.redirect_stderr(io.StringIO()) as error:
                self.assertEqual(main(), 1)
        self.assertIn("이미 사용 중인 수집 이름", error.getvalue())


if __name__ == "__main__":
    unittest.main()
