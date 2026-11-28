import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from processing.collection.library_program_batch import (
    PROGRAM_SECTION, capture_program_batch, read_program_assets,
)
from processing.collection.library_programs import (
    parse_program_detail, parse_program_listing, program_detail_url, program_listing_url, program_record,
)

_HEADERS = ("도서관", "행사구분", "행사명", "행사기간", "행사대상", "접수자/정원(대기정원)", "접수현황")
# 메뉴의 `a.on`과 스크립트 안 표 문자열은 목록으로 읽지 않아야 한다.
_NOISE = ('<nav><a class="on" href="/library/contents.do?mId=0202020000">행사신청</a></nav>'
          '<script>var html = "<table class=\'bod_list\'><tr><td>x</td></tr></table>";</script>')
_FORM = '<form id="listForm" name="listForm" action="/library/activity/program/list.do?mId=0202020000" method="post">'
_SCRIPTS = ('<!-- DWR --><script src="/dwr/interface/EgovFileMngDwr.js"></script><script src="/dwr/engine.js"></script>'
            '<script src="/common/js/common/EgovFileUtils.js"></script>')
_FILE = ('<div id="updateFileList" data-saved-file-container="y"><ul><li>'
         '<a href="#" onclick="fn_egov_downFile(\'be6e\',\'f9a1\'); return false;">'
         '<span class="mR5">강의계획서.hwp</span>&nbsp;[47.5 KByte]</a></li></ul></div>')


def row(idx, status="접수중", *, title=None, period="2026-12-10 ~ 2026-12-10<br/> 19:00 ~ 21:00", extra=""):
    return (f'<tr><td>공도</td><td><strong class="skyblue">기타</strong><br/>(동아리)</td>'
            f'<td><a href="/library/activity/program/view.do?mId=0202020000&idx={idx}">{title or "행사 " + idx}</a></td>'
            f'<td>{period}</td><td>시민 누구나</td><td>14/100<br/>(0/30)</td>'
            f'<td>\n<span class="state" data-button="write" data-idx="{idx}" data-state="{status}">{status}</span>\n</td>'
            f'{extra}</tr>')


def listing(*rows, page=1, total=3, current=None, headers=_HEADERS, end=None):
    head = "".join(f'<th scope="col" class="wp8">{label}</th>' for label in headers)
    end = end if end is not None else f'<a href="#" onclick="module.goPage({total}); return false;" class="btn_end">맨끝</a>'
    return (f'<html><body>{_NOISE}{_FORM}<input id="currentPageNo" name="currentPageNo" type="hidden" value="{page}"/>'
            '<div class="table_responsive"><table class="bod_list taC"><caption>행사신청 목록</caption>'
            f'<colgroup><col span="1"><col span="1"></colgroup><thead><tr>{head}</tr></thead>'
            f'<tbody>\n{"".join(rows)}\n</tbody></table></div></form><div class="bod_foot"><div class="box_page">'
            f'<a href="#" onclick="module.goPage(1); return false;" class="btn_first">맨첨</a>'
            f'<a class="on"><b>{current or page}</b></a>{end}</div></div></body></html>').encode()


_FIELDS = (
    ("행사명", "세계를 잇는 직업 특강"), ("접수기간", "2026-11-17 09:00 ~ 2026-11-28 16:00"),
    ("행사기간", "\n2026-11-28  ~ 2026-11-28\n"), ("행사요일", "토요일"), ("행사시간", "14:00 ~ 16:00"),
    ("행사대상", "시민 누구나"), ("장소", "아양도서관 2층 다목적홀"), ("온라인접수", "신청 : 10명 / 정원 : 50명"),
    ("재료비", "없음."), ("접수방법", ""), ("행사내용", "첫&nbsp;줄<br>둘째&nbsp;&nbsp;줄<br><br>셋째"),
    ("문의전화", "031-678-0733"), ("첨부파일", "자료없음"),
)


def detail(idx, *fields, button=None, head=("구분", "아양도서관", "행사구분", "특강")):
    pairs = fields or _FIELDS
    rows = "".join(f"<tr><th>{label}</th><td colspan=\"3\">{value}</td></tr>" for label, value in pairs)
    first = "<tr>" + "".join(f"<{tag}>{text}</{tag}>" for tag, text in zip(("th", "td") * 2, head)) + "</tr>"
    button = button if button is not None else (
        f'<a href="javascript:void(0);" data-button="write" data-idx="{idx}" data-state="A" class="btn">신청하기</a>')
    return (f'<html><body>{_NOISE}{_FORM}<input id="currentPageNo" name="currentPageNo" type="hidden" value="1"/></form>'
            f'<div class="tbl-box"><table class="tbl"><caption>문화강좌 신청확인</caption>'
            f'<colgroup><col span="1" class="w15"></colgroup><tbody>{first}{rows}</tbody></table></div>'
            f'<div class="taC mT30">{button}<a href="javascript:void(0);" data-button="list">목록</a></div>'
            '</body></html>')


def replace(label, value):
    return tuple((name, value if name == label else old) for name, old in _FIELDS)


class LibraryProgramParserTest(unittest.TestCase):
    def test_urls_use_fixed_menu_and_page_parameter(self):
        self.assertEqual(program_listing_url(2), "https://www.anseong.go.kr/library/activity/program/list.do"
                                                 "?mId=0202020000&currentPageNo=2")
        self.assertEqual(program_detail_url("7666"),
                         "https://www.anseong.go.kr/library/activity/program/view.do?idx=7666&mId=0202020000")
        for value in ("0", "1a", "1" * 19, 7):
            with self.subTest(value=value), self.assertRaises(ValueError):
                program_detail_url(value)

    def test_listing_keeps_cells_and_status_verbatim(self):
        total, rows = parse_program_listing(listing(row("7406"), row("7607", "대기자접수중")), page=1)
        self.assertEqual(total, 3)
        self.assertEqual([program_id for program_id, _ in rows], ["7406", "7607"])
        self.assertEqual(rows[1][1], {
            "library": "공도", "program_type": "기타\n(동아리)", "title": "행사 7607",
            "activity_period": "2026-12-10 ~ 2026-12-10\n19:00 ~ 21:00", "target": "시민 누구나",
            "enrollment": "14/100\n(0/30)", "application_status": "대기자접수중",
        })
        # 비어도 되는 목록 칸은 null과 사유를 남긴다.
        _, rows = parse_program_listing(listing(row("1").replace("<td>시민 누구나</td>", "<td></td>")), page=1)
        record = program_record(1, rows[0][1], parse_program_detail(detail("1"), "1"))
        self.assertIsNone(record["listing"]["target"])
        self.assertEqual(record["unknown"]["listing.target"], "empty")

    def test_listing_rejects_changed_structure_or_page(self):
        bad_link = row("1").replace("idx=1", "idx=1&x=2")
        status = ">접수중</span>"
        cases = {
            "form action": listing(row("1")).replace(b"list.do?mId=0202020000\" method", b"list.do?mId=1\" method"),
            "second table": listing(row("1")).replace(
                b"</form>", f'<table class="bod_list"><tbody>{row("2")}</tbody></table></form>'.encode()),
            "hidden page": listing(row("1"), page=2, current=1),
            "current page": listing(row("1"), current=2),
            "beyond total": listing(row("1"), page=4, total=3),
            "headers": listing(row("1"), headers=_HEADERS[:-1] + ("상태",)),
            "no end": listing(row("1"), end=""),
            "no rows": listing(),
            "extra cell": listing(row("1", extra="<td>x</td>")),
            "second link": listing(row("1", title='<a href="/library/x">x</a>')),
            "other cell link": listing(row("1", period='<a href="/library/x">x</a>')),
            "status idx": listing(row("1").replace('data-idx="1"', 'data-idx="2"')),
            "status image": listing(row("1").replace(status, '><img src="/img/state_ing.gif" alt="">접수중</span>')),
            "empty status": listing(row("1").replace(status, "></span>")),
            "empty title": listing(row("1", title=" ")),
            "hidden cell": listing(row("1").replace("<td>시민", '<td style="display:none">시민')),
            "link": listing(bad_link),
            "duplicate": listing(row("1"), row("1")),
            "tag": listing(row("1", period="<div>2026-12-10</div>")),
            "hidden": listing(row("1", period='<span style="display:none">x</span>')),
            "stray text": listing(row("1") + "x"),
            "nul": listing(row("1")).replace(b"</html>", b"\x00</html>"),
        }
        for name, raw in cases.items():
            with self.subTest(name=name), self.assertRaises(ValueError):
                parse_program_listing(raw, page=4 if name == "beyond total" else 1)

    def test_detail_keeps_schedules_apart_and_unknowns_null(self):
        record = parse_program_detail(detail("7666"), "7666")
        fields = record["fields"]
        self.assertEqual(fields["application_period"], "2026-11-17 09:00 ~ 2026-11-28 16:00")
        self.assertEqual((fields["activity_period"], fields["activity_weekday"], fields["activity_time"]),
                         ("2026-11-28 ~ 2026-11-28", "토요일", "14:00 ~ 16:00"))
        self.assertEqual(fields["material_cost"], "없음.")
        self.assertEqual(fields["description"], "첫 줄\n둘째 줄\n\n셋째")
        self.assertEqual(fields["library"], "아양도서관")
        self.assertIsNone(fields["supplies"])
        self.assertEqual(record["unknown"], {"instructor": "missing", "supplies": "missing",
                                             "application_method": "empty", "notes": "missing"})
        self.assertEqual((record["attachments"], record["review_flags"], record["apply_button_state"]), ([], [], "A"))
        self.assertEqual(record["cross_reference_candidate"], {"integrated_reservation_program_idx": "7666"})
        self.assertEqual(record["official_url"], program_detail_url("7666"))

    def test_detail_attachment_cell_variants(self):
        record = parse_program_detail(detail("1", *replace("첨부파일", _SCRIPTS + _FILE)), "1")
        self.assertEqual((record["attachments"], record["review_flags"]), (["강의계획서.hwp [47.5 KByte]"], ["attachment"]))
        # 파일 목록도 `자료없음`도 없이 스크립트만 있으면 첨부 유무를 확정하지 않는다.
        record = parse_program_detail(detail("1", *replace("첨부파일", _SCRIPTS)), "1")
        self.assertIsNone(record["attachments"])
        self.assertEqual(record["unknown"]["attachments"], "empty")
        record = parse_program_detail(detail("1", *replace("행사내용", '<img src="/a.png" alt="안내">')), "1")
        self.assertEqual((record["fields"]["description"], record["review_flags"]), (None, ["image:description"]))

    def test_detail_rejects_mismatch_or_changed_format(self):
        cases = {
            "button idx": detail("1", button='<a data-button="write" data-idx="2" data-state="A">신청</a>'),
            "no button": detail("1", button="<span></span>"),
            "repeated attr": detail("1", button='<a data-button="write" data-idx="2" data-idx="1">신청</a>'),
            "unknown label": detail("1", *_FIELDS, ("수강료", "1000원")),
            "duplicate": detail("1", *_FIELDS, ("장소", "다른 곳")),
            "missing": detail("1", *(pair for pair in _FIELDS if pair[0] != "접수기간")),
            "no attachment row": detail("1", *(pair for pair in _FIELDS if pair[0] != "첨부파일")),
            "empty title": detail("1", *replace("행사명", " ")),
            "style": detail("1", *replace("장소", '<span style="color:#fff">비밀</span>')),
            "script": detail("1", *replace("장소", "<script>x</script>")),
            "table": detail("1", *replace("장소", "<table><tr><td>x</td></tr></table>")),
            "unclosed": detail("1", *replace("장소", "<p>x")),
            "attachment text": detail("1", *replace("첨부파일", "파일 있음")),
            "attachment link": detail("1", *replace("첨부파일", '<a href="/x.hwp">x.hwp</a>')),
            "attachment script": detail("1", *replace("첨부파일", '<script src="/other.js"></script>')),
            "odd cells": detail("1", head=("구분", "아양도서관", "행사구분")),
            "caption": detail("1").replace("문화강좌 신청확인", "문화강좌 목록"),
            "label tag": detail("1").replace("<th>장소</th>", "<th><span>장소</span></th>"),
            "hidden row": detail("1").replace("<tr><th>재료비", '<tr style="display:none"><th>재료비'),
            "hidden cell": detail("1").replace('<td colspan="3">없음.', '<td colspan="3" hidden>없음.'),
            "hidden table": detail("1").replace('<table class="tbl">', '<table class="tbl" style="display:none">'),
        }
        for name, text in cases.items():
            with self.subTest(name=name), self.assertRaises(ValueError):
                parse_program_detail(text, "1")


class LibraryProgramBatchTest(unittest.TestCase):
    def setUp(self):
        self.private = Path(self.enterContext(TemporaryDirectory())).resolve()
        self.root = self.private / PROGRAM_SECTION
        self.enterContext(patch("processing.collection.library_program_batch.sleep"))
        self.listing = self.enterContext(patch("processing.collection.library_program_batch.fetch_program_listing"))
        self.detail = self.enterContext(patch("processing.collection.library_program_batch.fetch_program_detail"))
        self.listing.side_effect = [listing(row("9"), row("7", "접수마감"), total=2),
                                    listing(row("8", "접수완료"), page=2, total=2)]
        self.detail.side_effect = lambda program_id, **_options: detail(program_id).encode()

    def test_capture_keeps_listing_status_next_to_detail_record(self):
        summary = capture_program_batch("run", self.root)
        self.assertEqual(summary, {"batch_id": "run", "status": "complete", "discovery_status": "complete",
                                   "selected": 3, "parsed": 3})
        directory = self.root / "run"
        receipt = json.loads((directory / "batch.json").read_text(encoding="utf-8"))
        self.assertEqual(receipt["schema_version"], "citizen-library-program-batch-v1")
        self.assertEqual([page["source_url"] for page in receipt["pages"]], [program_listing_url(1), program_listing_url(2)])
        self.assertEqual([item["web_id"] for item in receipt["items"]], ["9", "7", "8"])
        parsed = json.loads((directory / "parsed-8.json").read_text(encoding="utf-8"))
        self.assertEqual((parsed["schema_version"], parsed["parser_version"]),
                         ("citizen-library-program-v1", "library-program-parser-v1"))
        self.assertEqual(parsed["sha256"], hashlib.sha256((directory / "detail-8.html").read_bytes()).hexdigest())
        self.assertEqual((parsed["record"]["list_page"], parsed["record"]["listing"]["application_status"]), (2, "접수완료"))
        self.assertEqual(parsed["record"]["external_id"], "8")

    def test_detail_failure_keeps_raw_and_reason(self):
        self.detail.side_effect = [detail("2").encode(), ValueError("합성 수신 실패"), detail("8").encode()]
        summary = capture_program_batch("run", self.root)
        receipt = json.loads((self.root / "run" / "batch.json").read_text(encoding="utf-8"))
        self.assertEqual((summary["status"], summary["parsed"]), ("partial", 1))
        self.assertEqual([item["status"] for item in receipt["items"]], ["parse_failed", "fetch_failed", "parsed"])
        self.assertIn("행사 번호가 요청과 일치하지 않습니다", receipt["items"][0]["error"])
        self.assertTrue((self.root / "run" / "detail-9.html").exists())

    def test_read_assets_revalidates_raw_and_parsed_record(self):
        capture_program_batch("run", self.root)
        assets = read_program_assets(self.private, "run", {"8", "9"})
        self.assertEqual(assets["8"]["raw_asset_path"], f"{PROGRAM_SECTION}/run/detail-8.html")
        self.assertEqual(assets["8"]["official_url"], program_detail_url("8"))
        self.assertEqual(assets["8"]["collection_method"], "official-web-library-program")
        directory = self.root / "run"
        receipt = json.loads((directory / "batch.json").read_text(encoding="utf-8"))
        self.assertEqual((assets["8"]["listing_raw_asset_path"], assets["8"]["listing_url"]),
                         (f"{PROGRAM_SECTION}/run/list-2.html", program_listing_url(2)))
        self.assertEqual((assets["8"]["listing_raw_sha256"], assets["8"]["listing_collected_at"]),
                         (receipt["pages"][1]["sha256"], receipt["pages"][1]["fetched_at"]))
        with self.assertRaisesRegex(ValueError, "파싱이 완료된"):
            read_program_assets(self.private, "run", {"5"})

        originals = {path: path.read_bytes() for path in directory.iterdir()}

        def rewrite_receipt(change):
            changed = json.loads(originals[directory / "batch.json"])
            change(changed)
            (directory / "batch.json").write_text(json.dumps(changed, ensure_ascii=False), encoding="utf-8")

        def detail_and_parsed():
            # 원본과 파싱 결과를 함께 바꿔도 수집 기록의 해시가 다르면 거부한다.
            (directory / "detail-9.html").write_text(detail("9", *replace("장소", "다른 곳")), encoding="utf-8")
            parsed = json.loads(originals[directory / "parsed-9.json"])
            parsed["record"]["fields"]["place"] = "다른 곳"
            parsed["sha256"] = hashlib.sha256((directory / "detail-9.html").read_bytes()).hexdigest()
            (directory / "parsed-9.json").write_text(json.dumps(parsed, ensure_ascii=False), encoding="utf-8")

        def listing_without_row():
            (directory / "list-1.html").write_bytes(listing(row("7", "접수마감"), total=2))
            rewrite_receipt(lambda data: data["pages"][0].update(
                sha256=hashlib.sha256((directory / "list-1.html").read_bytes()).hexdigest()))

        tampering = {
            "batch id": (lambda: rewrite_receipt(lambda data: data.update(batch_id="other")), "규격·이름"),
            "detail url": (lambda: rewrite_receipt(lambda data: data["items"][0].update(source_url="x")), "파싱이 완료된"),
            "listing url": (lambda: rewrite_receipt(lambda data: data["pages"][0].update(source_url="x")), "목록 페이지"),
            "detail with parsed": (detail_and_parsed, "해시"),
            "listing row gone": (listing_without_row, "원본과 다릅니다"),
        }
        for name, (change, message) in tampering.items():
            with self.subTest(name=name):
                change()
                with self.assertRaisesRegex(ValueError, message):
                    read_program_assets(self.private, "run", {"9"})
                for path, content in originals.items():
                    path.write_bytes(content)
        parsed = json.loads((directory / "parsed-9.json").read_text(encoding="utf-8"))
        for change, message in ((lambda: parsed["record"]["listing"].update(application_status="접수중!"), "원본과 다릅니다"),
                                (lambda: parsed.update(parser_version="old"), "다른 파서 버전")):
            with self.subTest(message=message):
                change()
                (directory / "parsed-9.json").write_text(json.dumps(parsed, ensure_ascii=False), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, message):
                    read_program_assets(self.private, "run", {"9"})
        (directory / "list-1.html").write_bytes(listing(row("9", "접수완료"), row("7"), total=2))
        with self.assertRaisesRegex(ValueError, "해시"):
            read_program_assets(self.private, "run", {"7"})


if __name__ == "__main__":
    unittest.main()
