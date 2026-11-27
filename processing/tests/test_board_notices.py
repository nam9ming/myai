import unittest
from unittest.mock import patch

from processing.collection.libraries import parse_board_notice, parse_library_notice
from processing.collection.library_listing import parse_board_listing, parse_library_listing
from processing.collection.official_web import (
    SourceHTTPError, board_detail_url, fetch_board_detail, fetch_board_listing,
)


def _link(notice_id, menu="0501010000"):
    return f"""<a href="#" onclick="goTo.view('list','{notice_id}','16','{menu}'); return false;">공지</a>"""


def _row(notice_id, *, number="1", pinned=False, menu="0501010000"):
    cell = '<img src="/common/img/board/icon_notice.gif" alt="공지"/>' if pinned else number
    return (f'<tr><td class="list_num">{cell}</td><td class="list_tit taL">{_link(notice_id, menu)}</td>'
            '<td class="list_part">부서</td><td class="list_date">2026-11-27</td></tr>')


def _listing(rows, *, current=1, total=3):
    return f"""<form id="list">
      <p class="page_num">현재 페이지 <span class="bold red">{current}</span> / 전체 페이지 {total}</p>
      <table class="bod_list taC"><thead><tr><th>번호</th><th>제목</th></tr></thead>
      <tbody>{rows}</tbody></table></form>"""


def _notice(notice_id="203043", body="<p>합성 본문</p>"):
    return f"""<input type="hidden" name="bIdx" value="{notice_id}"/>
    <div class="bod_wrap"><div class="bod_view"><h4>합성 시청 공지</h4>
      <div class="view_info"><ul class="clFix"><li class="view_date"><span>등록일</span> : 2026-11-27</li></ul></div>
      <div class="view_cont">{body}</div></div></div>"""


class BoardTransportTest(unittest.TestCase):
    def test_city_board_urls_are_fixed(self):
        self.assertEqual(board_detail_url("city", "203043"),
                         "https://www.anseong.go.kr/portal/bbs/view.do?bIdx=203043&mId=0501010000&ptIdx=16")
        for board, notice_id in (("library", "1"), ("other", "1"), ("city", "0"), ("city", "1" * 19), ("city", 1)):
            with self.subTest(board=board, notice_id=notice_id), self.assertRaises(ValueError):
                board_detail_url(board, notice_id)

    @patch("processing.collection.official_web.HTTPSConnection")
    def test_fetches_post_page_and_get_detail(self, connect):
        response = connect.return_value.getresponse.return_value.__enter__.return_value
        response.status, response.getheader.return_value, response.read.return_value = 200, None, b"ok"
        self.assertEqual(fetch_board_listing("city", 2, limit=64), b"ok")
        self.assertEqual(fetch_board_detail("city", "203043", limit=64), b"ok")
        listing, detail = connect.return_value.request.call_args_list
        self.assertEqual(listing.args, ("POST", "/portal/bbs/list.do?ptIdx=16&mId=0501010000"))
        self.assertEqual(listing.kwargs["body"], b"page=2")
        self.assertEqual(detail.args, ("GET", "/portal/bbs/view.do?bIdx=203043&mId=0501010000&ptIdx=16"))
        self.assertNotIn("body", detail.kwargs)
        for args in (("city", 0), ("city", True), ("library", 1)):
            with self.subTest(args=args), self.assertRaises(ValueError):
                fetch_board_listing(*args, limit=64)
        response.status = 403
        with self.assertRaises(SourceHTTPError):
            fetch_board_detail("city", "1", limit=64)


class BoardListingTest(unittest.TestCase):
    def test_pinned_rows_are_separated_from_numbered_rows(self):
        rows = _row("201926", pinned=True) + _row("185869", pinned=True) + _row("203066", number="1424")
        fixture = _listing(rows + _row("203062", number="1423"), current=2, total=143)
        self.assertEqual(parse_board_listing(fixture.encode(), board="city", page=2),
                         (143, ["203066", "203062"], ["201926", "185869"]))

    def test_pinned_notice_may_also_appear_as_a_numbered_row(self):
        fixture = _listing(_row("201926", pinned=True) + _row("201926", number="1300"))
        self.assertEqual(parse_board_listing(fixture.encode(), board="city", page=1), (3, ["201926"], ["201926"]))

    def test_reads_multiline_markup_with_omitted_cell_end_tags(self):
        rows = """
        <tr>
          <td class="list_num">
            <img src="/common/img/board/icon_notice.gif" alt="공지"/>
          <td class="list_tit taL ">
            <a href="#" onclick="goTo.view('list','201926','16','0501010000'); return false;">
              <b>합성 고정 글</b></a>
          <td class="list_file">
        </tr>
        <tr>
          <td class="list_num">
            1424
          <td class="list_tit taL ">
            <a href="#" onclick="goTo.view('list','203066','16','0501010000'); return false;">합성 글
              <span class="ico_new"><span class="blind">새 글</span></span></a>
          <td class="list_date">2026-11-27
        </tr>"""
        self.assertEqual(parse_board_listing(_listing(rows).encode(), board="city", page=1),
                         (3, ["203066"], ["201926"]))
        library = rows.replace("0501010000", "0401010000")
        self.assertEqual(parse_library_listing(_listing(library).encode(), page=1), (3, ["201926", "203066"]))

    def test_rejects_unrecognized_number_cells(self):
        number_cell = '<td class="list_num">1</td>'
        for replacement in (
            '<td class="list_num"><span>공지</span></td>', "", '<td class="list_num"></td>',
            '<td class="list_num">-</td>', '<td class="list_num"><img alt="공지"/><img alt="new"/></td>',
            '<td class="list_num" class="x">1</td>', '<td class="list_num"><img alt="x" alt="공지"/></td>',
            '<td class="list_num"><img alt="새글"/></td>', '<td class="list_num">1</td><td class="list_num">2</td>',
            '<td class>1</td>',
        ):
            fixture = _listing(_row("5").replace(number_cell, replacement))
            with self.subTest(replacement=replacement), self.assertRaisesRegex(ValueError, "^시청 공지 목록"):
                parse_board_listing(fixture.encode(), board="city", page=1)

    def test_rejects_page_with_only_pinned_rows(self):
        with self.assertRaisesRegex(ValueError, "번호가 붙은 글이 없습니다"):
            parse_board_listing(_listing(_row("5", pinned=True), current=2).encode(), board="city", page=2)

    def test_rejects_other_board_ambiguous_pin_or_duplicates(self):
        for rows in (
            _row("5", menu="0401010000"),
            _row("5").replace(">1<", '><img alt="공지"/>1<'),
            _row("5", pinned=True) * 2,
            _row("5") * 2,
        ):
            with self.subTest(rows=rows[:80]), self.assertRaises(ValueError):
                parse_board_listing(_listing(rows).encode(), board="city", page=1)
        with self.assertRaises(ValueError):
            parse_board_listing(_listing(_row("5")).encode(), board="library", page=1)

    def test_library_listing_keeps_previous_combined_result(self):
        rows = _row("9", pinned=True, menu="0401010000") + _row("8", menu="0401010000")
        self.assertEqual(parse_library_listing(_listing(rows).encode(), page=1), (3, ["9", "8"]))
        number_cell = '<td class="list_num">1</td>'
        for replacement in ('<td class="list_num"><img alt="새글"/></td>', '<td class="list_num"><img alt="공지"/>3</td>',
                            '<td class="list_num">1</td><td class="list_num">2</td>', ""):
            row = _row("7", menu="0401010000").replace(number_cell, replacement)
            with self.subTest(replacement=replacement):
                self.assertEqual(parse_library_listing(_listing(row).encode(), page=1), (3, ["7"]))
        duplicate = _listing(_row("9", menu="0401010000") * 2, current=2, total=1)
        with self.assertRaisesRegex(ValueError, "구조가 올바르지"):
            parse_library_listing(duplicate.encode(), page=2)
        with self.assertRaises(ValueError):
            parse_library_listing(_listing(_row("9", pinned=True, menu="0401010000")
                                           + _row("9", menu="0401010000")).encode(), page=1)


class BoardNoticeTest(unittest.TestCase):
    def test_city_notice_uses_board_url_and_source(self):
        record = parse_board_notice(_notice(), board="city", notice_id="203043")
        self.assertEqual(record, {
            "source": "city_notice",
            "external_id": "203043",
            "title": "합성 시청 공지",
            "official_url": board_detail_url("city", "203043"),
            "fields": {"description": "합성 본문", "published_date": "2026-11-27"},
        })

    def test_city_notice_checks_id_before_reading_html(self):
        with self.assertRaisesRegex(ValueError, "18자리"):
            parse_board_notice("\x00", board="city", notice_id="1" * 19)

    def test_city_notice_errors_name_the_board(self):
        with self.assertRaisesRegex(ValueError, "^시청 공지 .*번호"):
            parse_board_notice(_notice("1"), board="city", notice_id="203043")
        with self.assertRaisesRegex(ValueError, "^시청 공지 본문 텍스트.*이미지"):
            parse_board_notice(_notice(body='<p><img src="/x.png" alt=""></p>'), board="city", notice_id="203043")
        with self.assertRaises(ValueError):
            parse_board_notice(_notice(), board="library", notice_id="203043")

    def test_library_notice_is_unchanged(self):
        record = parse_library_notice(_notice(), notice_id="203043")
        self.assertEqual(record["source"], "library_notice")
        self.assertEqual(record["official_url"],
                         "https://www.anseong.go.kr/library/bbs/view.do?bIdx=203043&mId=0401010000&ptIdx=16")
        with self.assertRaisesRegex(ValueError, "^도서관 공지 "):
            parse_library_notice(_notice("1"), notice_id="203043")


if __name__ == "__main__":
    unittest.main()
