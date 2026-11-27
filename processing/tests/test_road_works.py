import unittest
from unittest.mock import patch

from processing.collection.official_web import (
    SourceHTTPError, fetch_road_detail, fetch_road_listing, road_detail_url, road_listing_path,
)
from processing.collection.road_works import PARSER_VERSION, parse_road_detail, parse_road_listing


_CAPTIONS = {"planned": "예정", "ongoing": "진행중", "completed": "완료"}
_MENUS = {"planned": ("0", "0901020200"), "ongoing": ("1", "0901020100"), "completed": ("2", "0901020300")}


def _link(project_id):
    return (f'<a href="#none" onclick="req.post(this); return false;" '
            f'data-action="/depart/roadConstruction/view.do?idx={project_id}">공사</a>')


def _row(project_id, number="1"):
    return (f'<tr><td class="taC">{number}</td><td class="taC">도로시설과</td>'
            f'<td class="taL">{_link(project_id)}</td></tr>')


_EMPTY_ROW = '<tr class="taC"><td colspan="3" class="taC">검색된 결과가 없습니다.</td></tr>'


def _listing(rows, *, state="planned", current=1, total=1, caption=None):
    code, menu = _MENUS[state]
    label = caption if caption is not None else _CAPTIONS[state]
    return f"""
    <form id="list" name="list" action="/depart/roadConstruction/list.do?mId={menu}&amp;state={code}" method="post">
      <input id="page" name="page" type="hidden" value="{current}"/>
      <div class="search_box">
        <p class="page_num">현재 페이지 <span class="bold red">{current}</span> / 전체 페이지 {total}</p>
        <fieldset><select name="searchArea"><option value="">읍면동</option></select>
          <input type="button" onclick="return goPage(1);" value="검색" /></fieldset>
      </div>
      <table class="bod_maintain">
        <caption class="hidden">도로 공사 {label} 현황 - 번호, 담당부서, 사업명 순으로 나타낸 표입니다.</caption>
        <thead><tr><th>번호</th><th>담당부서</th><th>사업명</th></tr></thead>
        <tbody>{rows}</tbody>
      </table>
      <div class="box_page"><span>{current}</span><a href="#" onclick="goPage(2); return false;">2</a></div>
    </form>"""


_FIELDS = (
    ("지역", "양성면"),
    ("사업위치", "양성면 동항리 ~ 석화리"),
    ("사업량", "L=1.7km, B=20~25m(4차로)"),
    ("공사기간", "2027-03-01 ~ 2028-12-31"),
    ("현재현황", "설계중(용역사:합성엔지니어링)"),
    ("담당부서", "도로시설과(도로시설1팀)"),
    ("전화번호", "031-000-0000"),
)


def _detail(project_id="1972", *, state="planned", title="양성 우회도로 개설공사", fields=_FIELDS,
            hidden_id=None, extra=""):
    code, menu = _MENUS[state]
    rows = "".join(f"<dl>\n<dt>{label}</dt>\n<dd>{value}</dd>\n</dl>" for label, value in fields)
    return f"""<html><body><div id="conts" class="conts">
    <form id="list" name="list" action="/depart/roadConstruction/list.do?mId={menu}&amp;state={code}" method="post">
      <input id="idx" name="idx" type="hidden" value="{hidden_id or project_id}"/>
      <input id="page" name="page" type="hidden" value="1"/>
      <h4 class="mT0">{title}</h4>
      <div class="tbl_form">{rows}</div>
      <div class="hey mT20 mB20"><div id="drawingMap"><img alt="" src="https://map1.daumcdn.net/tile.png">
        <svg viewBox="0 0 10 10"><defs /><path d="M 1 1 L 2 2" /></svg><div>50m</div></div></div>
      {extra}
    </form></div></body></html>"""


class RoadTransportTest(unittest.TestCase):
    def test_paths_use_official_menu_state_and_page(self):
        self.assertEqual(
            road_listing_path("ongoing", 2),
            "/depart/roadConstruction/list.do?searchGubun=1&state=1&mId=0901020100&page=2",
        )
        self.assertEqual(
            road_detail_url("completed", "3007"),
            "https://www.anseong.go.kr/depart/roadConstruction/view.do?idx=3007&mId=0901020300&state=2",
        )

    def test_paths_reject_unknown_state_page_and_project_id(self):
        for state, page in (("closed", 1), ("planned", 0), ("planned", True), (1, 1)):
            with self.subTest(state=state, page=page), self.assertRaises(ValueError):
                road_listing_path(state, page)
        for project_id in ("0", "012", "１", "1" * 19, 12, ""):
            with self.subTest(project_id=project_id), self.assertRaises(ValueError):
                road_detail_url("planned", project_id)

    @patch("processing.collection.official_web.HTTPSConnection")
    def test_fetches_send_bodyless_get_to_fixed_host(self, connect):
        response = connect.return_value.getresponse.return_value.__enter__.return_value
        response.status, response.getheader.return_value = 200, None
        response.read.return_value = b"<html></html>"
        self.assertEqual(fetch_road_listing("planned", 1, limit=64), b"<html></html>")
        self.assertEqual(fetch_road_detail("completed", "3007", limit=64), b"<html></html>")
        self.assertEqual([call.args[0] for call in connect.call_args_list], ["www.anseong.go.kr"] * 2)
        requests = connect.return_value.request.call_args_list
        self.assertEqual([call.args for call in requests], [
            ("GET", road_listing_path("planned", 1)),
            ("GET", "/depart/roadConstruction/view.do?idx=3007&mId=0901020300&state=2"),
        ])
        self.assertTrue(all("body" not in call.kwargs for call in requests))
        response.status = 302
        with self.assertRaises(SourceHTTPError):
            fetch_road_detail("planned", "1", limit=64)


class RoadListingTest(unittest.TestCase):
    def test_listing_reads_page_count_and_row_order(self):
        rows = _row("2687", "12") + _row("1972", "1")
        fixture = _listing(rows, state="ongoing", current=2, total=3)
        self.assertEqual(parse_road_listing(fixture.encode("utf-8-sig"), state="ongoing", page=2),
                         (3, ["2687", "1972"]))

    def test_listing_accepts_only_the_official_empty_result_row(self):
        self.assertEqual(parse_road_listing(_listing(_EMPTY_ROW).encode(), state="planned", page=1), (1, []))
        for rows in (_EMPTY_ROW + _row("5"), '<tr><td colspan="3">다른 안내</td></tr>', ""):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                parse_road_listing(_listing(rows).encode(), state="planned", page=1)
        with self.assertRaises(ValueError):
            parse_road_listing(_listing("", current=2, total=2).encode(), state="planned", page=2)

    def test_listing_rejects_detail_links_outside_body_rows(self):
        for extra in ("</tbody><tr>" + _link("6") + "</tr><tbody>", _link("6")):
            fixture = _listing(_row("5")).replace("</tbody>", extra + "</tbody>", 1)
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                parse_road_listing(fixture.encode(), state="planned", page=1)
        fixture = _listing(_row("5")).replace("</table>", "<tfoot><tr><td>" + _link("6") + "</td></tr></tfoot></table>")
        with self.assertRaises(ValueError):
            parse_road_listing(fixture.encode(), state="planned", page=1)

    def test_listing_rejects_wrong_page_or_state_tab(self):
        rows = _row("5")
        for fixture, state, page in (
            (_listing(rows, current=2, total=3), "planned", 1),
            (_listing(rows, current=3, total=2), "planned", 3),
            (_listing(rows), "ongoing", 1),
            (_listing(rows, caption="진행중"), "planned", 1),
        ):
            with self.subTest(state=state, page=page), self.assertRaises(ValueError):
                parse_road_listing(fixture.encode(), state=state, page=page)

    def test_listing_rejects_malformed_or_duplicate_links(self):
        for rows in (
            _row("0"), _row("01"), _row("1" * 19),
            _row("5").replace("view.do?idx=5", "view.do?idx=5&amp;mId=1"),
            _row("5").replace("return false;", "return true;"),
            _row("5") + _row("5"),
            '<tr><td>1</td><td>부서</td><td>링크 없음</td></tr>',
            _row("5").replace("</td></tr>", _link("6") + "</td></tr>"),
        ):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                parse_road_listing(_listing(rows).encode(), state="planned", page=1)

    def test_listing_rejects_missing_or_repeated_form(self):
        rows = _row("5")
        for fixture in (rows, _listing(rows) + _listing(rows), "<template>" + _listing(rows) + "</template>"):
            with self.subTest(fixture=fixture[:40]), self.assertRaises(ValueError):
                parse_road_listing(fixture.encode(), state="planned", page=1)


class RoadDetailTest(unittest.TestCase):
    def test_detail_keeps_each_field_and_parses_only_an_exact_period(self):
        record = parse_road_detail(_detail(), state="planned", project_id="1972")
        self.assertEqual(PARSER_VERSION, "road-works-parser-v1", "출력 형식을 바꾸면 파서 버전도 올린다.")
        self.assertEqual(record, {
            "external_id": "1972",
            "official_url": road_detail_url("planned", "1972"),
            "listing_state": "planned",
            "title": "양성 우회도로 개설공사",
            "fields": {
                "region": "양성면",
                "location": "양성면 동항리 ~ 석화리",
                "quantity": "L=1.7km, B=20~25m(4차로)",
                "construction_period": "2027-03-01 ~ 2028-12-31",
                "current_status": "설계중(용역사:합성엔지니어링)",
                "department": "도로시설과(도로시설1팀)",
                "phone": "031-000-0000",
            },
            "construction_period_range": {"start": "2027-03-01", "end": "2028-12-31"},
            "review_flags": [],
        })

    def test_detail_keeps_inverted_or_unparsed_period_text_for_review(self):
        for period, flag in (
            ("2021-08-26 ~ 2021-06-22", "period_inverted"),
            ("2021-02-30 ~ 2021-06-22", "period_unparsed"),
            ("2021-01-01~2021-02-01", "period_unparsed"),
            ("2021년 상반기", "period_unparsed"),
        ):
            fields = tuple((label, period if label == "공사기간" else value) for label, value in _FIELDS)
            with self.subTest(period=period):
                record = parse_road_detail(_detail(fields=fields), state="planned", project_id="1972")
                self.assertEqual(record["fields"]["construction_period"], period)
                self.assertIsNone(record["construction_period_range"])
                self.assertEqual(record["review_flags"], [flag])

    def test_detail_marks_blank_fields_as_unstated(self):
        fields = tuple((label, "  " if label in ("사업량", "공사기간") else value) for label, value in _FIELDS)
        record = parse_road_detail(_detail(fields=fields), state="planned", project_id="1972")
        self.assertIsNone(record["fields"]["quantity"])
        self.assertIsNone(record["fields"]["construction_period"])
        self.assertIsNone(record["construction_period_range"])
        self.assertEqual(record["review_flags"], ["missing:construction_period", "missing:quantity"])

    def test_detail_rejects_an_absent_field_as_format_change(self):
        fields = tuple(item for item in _FIELDS if item[0] != "전화번호")
        with self.assertRaises(ValueError):
            parse_road_detail(_detail(fields=fields), state="planned", project_id="1972")

    def test_detail_does_not_derive_lifecycle_from_status_text(self):
        fields = tuple((label, "공사 중" if label == "현재현황" else value) for label, value in _FIELDS)
        record = parse_road_detail(_detail(state="completed", fields=fields), state="completed", project_id="1972")
        self.assertEqual(record["listing_state"], "completed")
        self.assertEqual(record["fields"]["current_status"], "공사 중")
        self.assertEqual(record["review_flags"], [])

    def test_detail_normalizes_whitespace_and_inline_markup(self):
        fields = tuple((label, "안성시 <span>대덕면</span>\n\t내리" if label == "사업위치" else value)
                       for label, value in _FIELDS)
        record = parse_road_detail(_detail(fields=fields, title=" 대덕\n 내리도로 "), state="planned",
                                   project_id="1972")
        self.assertEqual(record["title"], "대덕 내리도로")
        self.assertEqual(record["fields"]["location"], "안성시 대덕면 내리")

    def test_detail_separates_line_breaks_and_paragraphs(self):
        values = {"전화번호": "031-000-0001<br>031-000-0002", "사업량": "<p>L=1km</p><p>B=10m</p>",
                  "지역": "양성면</br>동항리"}
        fields = tuple((label, values.get(label, value)) for label, value in _FIELDS)
        record = parse_road_detail(_detail(fields=fields, title="가나<br>다라"), state="planned", project_id="1972")
        self.assertEqual(record["fields"]["phone"], "031-000-0001 031-000-0002")
        self.assertEqual(record["fields"]["quantity"], "L=1km B=10m")
        self.assertEqual(record["fields"]["region"], "양성면 동항리")
        self.assertEqual(record["title"], "가나 다라")
        self.assertEqual(parse_road_detail(_detail(title="가</br>나"), state="planned", project_id="1972")["title"],
                         "가 나")

    def test_detail_rejects_block_markup_outside_known_inline_tags(self):
        for title, value in (("양성", "가<hr>나"), ("양성", "<h5>가</h5><h5>나</h5>"), ("양성", "<blockquote>가</blockquote>"),
                             ("가<div>나</div>", "양성면"), ("가<hr>나", "양성면"), ("<pre>가</pre>", "양성면")):
            fields = tuple((label, value if label == "지역" else item) for label, item in _FIELDS)
            with self.subTest(title=title, value=value), self.assertRaises(ValueError):
                parse_road_detail(_detail(fields=fields, title=title), state="planned", project_id="1972")

    def test_parser_assertion_is_reported_as_format_error(self):
        with patch("processing.collection.road_works.HTMLParser.feed", side_effect=AssertionError):
            with self.assertRaises(ValueError):
                parse_road_detail(_detail(), state="planned", project_id="1972")
            with self.assertRaises(ValueError):
                parse_road_listing(_listing(_row("5")).encode(), state="planned", page=1)

    def test_detail_rejects_changed_or_ambiguous_structure(self):
        for fixture in (
            _detail(hidden_id="1973"),
            _detail(title=" "),
            _detail(fields=_FIELDS + (("비고", "추가 항목"),)),
            _detail(fields=_FIELDS + (("지역", "중복"),)),
            _detail(extra='<h4>두 번째 제목</h4>'),
            _detail(extra='<div class="tbl_form"></div>'),
            _detail(state="ongoing"),
            _detail().replace('<div class="tbl_form">', '<div class="other">'),
            _detail() + _detail(),
            "<template>" + _detail() + "</template>",
            _detail().replace("\x3c/dd>", "", 1),
            _detail() + "\x00",
        ):
            with self.subTest(fixture=fixture[-80:]), self.assertRaises(ValueError):
                parse_road_detail(fixture, state="planned", project_id="1972")

    def test_detail_rejects_invalid_arguments(self):
        for state, project_id in (("closed", "1972"), ("planned", "01"), ("planned", 1972)):
            with self.subTest(state=state, project_id=project_id), self.assertRaises(ValueError):
                parse_road_detail(_detail(), state=state, project_id=project_id)


if __name__ == "__main__":
    unittest.main()
