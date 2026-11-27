import unittest

from processing.collection.library_listing import parse_library_listing


def _notice_link(web_id, *, board="16", menu="0401010000"):
    return f"""<a href="#" onclick="goTo.view('list','{web_id}','{board}','{menu}'); return false;">공지</a>"""


def _listing(rows, *, current=1, total=2):
    return f"""
    <form id="list">
      <p class="page_num">
        현재 페이지 <span class="bold red">{current}</span> / 전체 페이지 {total}
      </p>
      <table class="bod_list taC">
        <thead><tr><th>번호와 제목</th></tr></thead>
        <tbody>{rows}</tbody>
      </table>
    </form>"""


def _row(content):
    return f"<tr><td>{content}</td></tr>"


class LibraryListingTest(unittest.TestCase):
    def test_listing_reads_verified_page_and_preserves_row_order(self):
        rows = _row(_notice_link("99") + '<a href="/download">첨부</a>') + _row(_notice_link("8"))
        fixture = f"""
        <template>{_listing(_row(_notice_link("90")))}</template>
        {_notice_link("50")}
        {_listing(rows, current=2, total=78)}
        <table><tbody>{_row(_notice_link("51"))}</tbody></table>
        """
        self.assertEqual(parse_library_listing(fixture.encode("utf-8-sig"), page=2),
                         (78, ["99", "8"]))

    def test_listing_rejects_wrong_page_or_inconsistent_count(self):
        rows = _row(_notice_link("99"))
        for current, total, requested in ((2, 3, 1), (2, 1, 2), (0, 2, 1), (1, 2, True)):
            with self.subTest(current=current, total=total, requested=requested):
                with self.assertRaises(ValueError):
                    parse_library_listing(_listing(rows, current=current, total=total).encode(), page=requested)

    def test_listing_rejects_malformed_links_wrong_board_and_missing_row_ids(self):
        for link in (
            _notice_link("0"), _notice_link("001"), _notice_link("１２"),
            _notice_link("1" * 19), _notice_link("1", board="17"),
            _notice_link("1", menu="0401020000"),
            _notice_link("1").replace("return false;", "return true;"),
            _notice_link("1").replace('href="#"', 'href="#" onclick="other()"'),
            '<template>' + _notice_link("5") + '</template>',
            '<a href="/unrecognized">공지</a>',
        ):
            with self.subTest(link=link), self.assertRaises(ValueError):
                parse_library_listing(_listing(_row(link)).encode(), page=1)

    def test_listing_rejects_duplicate_ids_and_multiple_links_in_one_row(self):
        for rows in (
            _row(_notice_link("99")) * 2,
            _row(_notice_link("99") + _notice_link("98")),
        ):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                parse_library_listing(_listing(rows).encode(), page=1)

    def test_listing_rejects_truncated_unknown_and_unverified_empty_pages(self):
        valid_html = _listing(_row(_notice_link("99")))
        for raw in (
            valid_html.split("</tbody>")[0].encode(),
            valid_html.split("</form>")[0].encode(),
            valid_html.replace('id="list"', 'id="another-board"').encode(),
            _listing("").encode(),
            (_listing(_row(_notice_link("99"))) * 2).encode(),
            b"\xff", b"\x00",
        ):
            with self.subTest(raw=raw[:90]), self.assertRaises(ValueError):
                parse_library_listing(raw, page=1)

    def test_listing_caps_rows(self):
        rows = [_row(_notice_link(str(web_id))) for web_id in range(1, 102)]
        self.assertEqual(len(parse_library_listing(_listing("".join(rows[:100])).encode(), page=1)[1]), 100)
        with self.assertRaises(ValueError):
            parse_library_listing(_listing("".join(rows)).encode(), page=1)
