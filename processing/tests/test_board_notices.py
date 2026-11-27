import time
import unittest
from unittest.mock import patch

from processing.collection.libraries import (
    BOARD_PARSER_VERSIONS, board_parser_version, parse_board_media, parse_board_notice, parse_library_media,
    parse_library_notice,
)
from processing.collection.library_listing import parse_board_listing, parse_library_listing
from processing.collection.official_web import (
    BOARDS, SourceHTTPError, board_detail_url, fetch_board_detail, fetch_board_listing,
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


CITY_VIEW = "/portal/bbs/view.do?ptIdx=16&amp;mId=0501010000"
LIBRARY_VIEW = "/library/bbs/view.do?ptIdx=16&amp;mId=0401010000"


IMAGE = "/common/imgView.do?attachId=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa&amp;fileSn=bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb&amp;mode=origin"


def _notice(notice_id="203043", body="<p>합성 본문</p>", view=CITY_VIEW):
    form = f'<form id="viewForm" action="{view}" method="post"></form>' if view else ""
    return f"""{form}<input type="hidden" name="bIdx" value="{notice_id}"/>
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
        self.assertEqual(dict(BOARD_PARSER_VERSIONS), {"city": "city-notice-parser-v3", "edu": "edu-notice-parser-v3"},
                         "게시판의 출력·허용 규칙을 바꾸면 그 게시판의 파서 버전을 올린다.")
        self.assertEqual(set(BOARD_PARSER_VERSIONS), set(BOARDS), "모든 게시판에 파서 버전이 있어야 한다.")
        for board in ("library", "other", None):
            with self.subTest(board=board), self.assertRaises(ValueError):
                board_parser_version(board)
        flagged = parse_board_notice(_notice(body='<p>본문</p><p><img src="/x.png" alt=""></p>'),
                                     board="city", notice_id="203043")
        self.assertEqual(flagged["review_flags"], ["inline_image"])
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

    def test_notice_html_must_belong_to_the_requested_board(self):
        for view in (None, LIBRARY_VIEW, "/portal/bbs/view.do?ptIdx=16&amp;mId=0501020000"):
            with self.subTest(view=view), self.assertRaisesRegex(ValueError, "게시판"):
                parse_board_notice(_notice(view=view), board="city", notice_id="203043")
        for fixture in (_notice() + _notice(), _notice().replace('id="viewForm"', 'id="viewForm" id="x"')):
            with self.assertRaises(ValueError):
                parse_board_notice(fixture, board="city", notice_id="203043")
        with self.assertRaisesRegex(ValueError, "^도서관 공지 .*게시판"):
            parse_library_notice(_notice(view=CITY_VIEW), notice_id="203043")
        for duplicated in ('id="viewForm" id="x"', 'id="x" id="viewForm"'):
            fixture = _notice(view=LIBRARY_VIEW).replace('id="viewForm"', duplicated)
            with self.subTest(duplicated=duplicated), self.assertRaisesRegex(ValueError, "속성이 중복"):
                parse_library_notice(fixture, notice_id="203043")
        self.assertEqual(parse_library_notice(_notice(view=LIBRARY_VIEW), notice_id="203043")["source"],
                         "library_notice")

    def test_hidden_elements_in_body_are_rejected(self):
        """브라우저 표시를 확정할 수 없으므로 hidden 요소가 있는 본문 영역은 추정하지 않고 거부한다."""
        pages = [
            _notice().replace("<h4>", "<h4 hidden>"),
            _notice().replace('<div class="bod_view">', '<div class="bod_view" hidden>'),
            _notice(body='<p>앞</p><p hidden>숨김<div>보이는 조건</div></p>'),
            _notice(body='<ul><li hidden>숨김<li>보임</ul>'),
            _notice(body='<p>본문<img hidden src="/common/imgView.do" alt=""></p>'),
            _notice(body='<p>앞</p><div hidden/><p>뒤</p>'),
            _notice(body='<p hidden style="display:block">보이는 조건</p>'),
            _notice(body='<dl><dd hidden><a href="#">첨부</a></dd></dl>'),
            _notice().replace("</div></div></div>",
                              '</div><dl class="view_file"><dd hidden><a href="#" onclick="x">첨부</a></dd></dl></div></div>'),
            _notice(body='<p>앞</p><svg><style><div hidden></style></svg><p>본문</p>'),
            _notice(body='<p>앞</p><math><style>x</style></math>'),
            _notice(body='<p>앞</p><!--><div hidden>--><p>본문</p>'),
            _notice(body='<p>앞</p><!-- a --!><p>본문</p>'),
            _notice(body='<p>앞</p><!-- a --!><div hidden>--><p>본문</p>'),
            _notice(body='<p>앞</p><![CDATA[><div hidden>]]><p>본문</p>'),
            _notice(body='<p style="display: none">숨김</p>'),
            _notice(body='<p style="color:red; VISIBILITY:hidden">숨김</p>'),
            _notice(body='<style>.x{display:none}</style><p class="x">숨김</p>'),
            _notice(body='<noscript>숨김</noscript>'),
            _notice(body='<iframe>숨김</iframe>'),
            _notice(body='<details><summary>요약</summary>숨김</details>'),
            _notice(body='<dialog>숨김</dialog>'),
            _notice(body='<title>숨김</title>'),
            _notice().replace('<div class="bod_view">', '<div class="bod_view" style="display:none">'),
            _notice(body='<p style="display:none" style="color:red">숨김</p>'),
            _notice(body='<p class="a" class="b">본문</p>'),
            _notice(body='<p style="display:/**/none">숨김</p>'),
            _notice(body='<p style="display:\\6e one">숨김</p>'),
            _notice(body='<p style="opacity: 0">숨김</p>'),
            _notice(body='<p style="opacity:0.0">숨김</p>'),
            _notice(body='<p style="font-size:0px">숨김</p>'),
            _notice(body='<p style="visibility: collapse">숨김</p>'),
            _notice(body='<p style="content-visibility:hidden">숨김</p>'),
            _notice(body='<svg><text>숨김</text></svg>'),
            _notice(body='<math><mi>숨김</mi></math>'),
            _notice(body='<p>앞</p><!--->보임-->'),
            _notice(body='<p>앞</p><script><!--<script></script>--><p>숨김</p>'),
            *(_notice(body=f'<{tag}>숨김</{tag}>') for tag in (
                'video', 'audio', 'canvas', 'object', 'noembed', 'noframes', 'datalist', 'rp', 'select', 'xmp',
                'textarea')),
            *(_notice(body=f'<p style="{style}">숨김</p>') for style in (
                'position:absolute;left:-9999px', 'text-indent:-9999px', 'margin-left: -120px',
                'width:0;height:0;overflow:hidden', 'transform:scale(0)', 'clip-path:inset(50%)',
                'color:transparent', 'color: rgba(0,0,0,0)', 'opacity:0.001', 'opacity:calc(0)',
                'font-size:calc(0px)')),
        ]
        for page in pages:
            with self.subTest(page=page[-90:]):
                with self.assertRaisesRegex(ValueError, "^시청 공지 .*(숨김|해석이 갈리는)"):
                    parse_board_notice(page, board="city", notice_id="203043")
                with self.assertRaisesRegex(ValueError, "숨김|해석이 갈리는"):
                    parse_board_media(page, board="city", notice_id="203043")
                library = page.replace(CITY_VIEW, LIBRARY_VIEW)
                with self.assertRaisesRegex(ValueError, "^도서관 공지 .*(숨김|해석이 갈리는)"):
                    parse_library_notice(library, notice_id="203043")
                with self.assertRaisesRegex(ValueError, "숨김|해석이 갈리는"):
                    parse_library_media(library, notice_id="203043")
        outside = ('<div hidden><span>메뉴</span></div><p style="display:none;position:absolute">메뉴</p>'
                   '<svg><title>아이콘</title></svg>' + _notice())
        self.assertEqual(parse_board_notice(outside, board="city", notice_id="203043")["title"], "합성 시청 공지")
        self.assertEqual(parse_board_media(outside, board="city", notice_id="203043"), [])
        library = outside.replace(CITY_VIEW, LIBRARY_VIEW)
        self.assertEqual(parse_library_notice(library, notice_id="203043")["title"], "합성 시청 공지")
        self.assertEqual(parse_library_media(library, notice_id="203043"), [])
        page_script = '<script>var x = "<div hidden>"; /*<!-- Al Chat -- >*/</script><template><p hidden>틀</p></template>'
        shown = page_script + _notice(
            body='<p>본문</p><!-- 정상 주석 --><!----><details open><summary>요약</summary>내용</details>'
                 '<script src="/dwr/engine.js"></script><p style="color:red">강조</p>'
                 '<p style="opacity:0.95; font-size:16px; display:inline-block; font-family:\'맑은 고딕\';'
                 ' text-indent:-31.4pt; letter-spacing:-0.57px; background-color: rgba(0,0,0,0.1);'
                 ' max-width:800px; overflow:hidden">글꼴</p>'
                 '<p>&lt;!-- 예시 문구</p><!-- 메모 -- ><p>숨은 내용</p> --><p>끝</p>') + (
            '<svg><title>마이크 권한이 필요합니다.</title></svg>')
        self.assertEqual(parse_board_notice(shown, board="city", notice_id="203043")["fields"]["description"],
                         "본문\n요약내용\n강조\n글꼴\n<!-- 예시 문구\n끝")

    def test_comment_rules_do_not_depend_on_python_patch_version(self):
        """3.13.5와 3.14는 `--!>`·`-- >`·`<!-->`에서 주석을 닫는지가 달랐다. 결과가 같도록 종료 규칙을 고정한다."""
        for markup in ('<!-- a --!><p>본문</p>', '<!-- a --!><div hidden>--><p>본문</p>', '<!--><p>본문</p>',
                       '<!-- 끝나지 않는 주석<p>본문</p>'):
            for where in ('body', 'before'):
                page = _notice(body=markup) if where == 'body' else markup + _notice()
                with self.subTest(markup=markup, where=where), \
                        self.assertRaisesRegex(ValueError, "^시청 공지 페이지에 브라우저와 해석이 갈리는"):
                    parse_board_notice(page, board="city", notice_id="203043")
        swallowed = '<!-- x -- >' + _notice() + '-->'
        with self.assertRaisesRegex(ValueError, "본문 영역을 확인할 수 없습니다"):
            parse_board_notice(swallowed, board="city", notice_id="203043")

    def test_body_markup_outside_the_allowlist_is_rejected(self):
        """본문 영역은 허용한 태그·속성·인라인 스타일만 받는다. 목록 밖 표기는 숨김 여부를 추정하지 않는다."""
        bodies = [
            '<link rel="stylesheet" href="data:text/css,p{display:none}"><p>숨김</p>', '<div popover>숨김</div>',
            '<progress>숨김</progress>', '<meter>숨김</meter>', '<p inert>숨김</p>', '<p aria-hidden="true">숨김</p>',
            '<input type="text" value="숨김">', '<p style="font-size:0mm">숨김</p>', '<p style="font-size:0Q">숨김</p>',
            '<p style="font-size:0e0px">숨김</p>', '<p style="font:0/0 a">숨김</p>', '<p style="color:#0000">숨김</p>',
            '<p style="color:#ffffff00">숨김</p>', '<p style="text-indent:-1e3px">숨김</p>',
            '<p style="text-indent:calc(9999px * -1)">숨김</p>', '<p style="text-indent:9999px">숨김</p>',
            '<p style="padding-left:5000px">숨김</p>', '<p style="margin-left:-99em">숨김</p>',
            '<p style="width:0 !important;width:100px;height:0 !important;height:10px;overflow:hidden">숨김</p>',
            '<p style="display:none! important">숨김</p>', '<p style="background:url(/img/a.png)">보임</p>',
            '<p style="line-height:0">숨김</p>', '<p style="letter-spacing:-50px">숨김</p>',
            '<p style="opacity:0.4">숨김</p>',
            f'<img width="0" height="0" src="{IMAGE}" alt="숨은 그림">', f'<img height="0" src="{IMAGE}">',
            f'<img width="0" width="100" src="{IMAGE}">', '<p><font size="2" size="1">숨김</font></p>',
            '<table cellpadding="99999"><tr><td>밀린 문구</td></tr></table>', '<table width="9999"><tr><td>밀린 문구</td></tr></table>', '<p align="center" align="left">본문</p>', '<p style="-webkit-text-fill-color:transparent">숨김</p>',
            '<template><svg><style></template>보이는 문구</style></svg></template><p>끝</p>',
            '<p>앞</p><script>document.write(\'<div hidden>\')</script><span>숨은 문구</span>',
            '<script src="https://invalid.example/x.js"></script><p>본문</p>', '<script></script><p>본문</p>',
            '<details name="g" open><summary>요약1</summary>보이는 문구</details>'
            '<details name="g" open><summary>요약2</summary>닫힌 문구</details>',
            '<input type="text" type="hidden" value="보이는 입력값"><p>본문</p>',
            '<p style="letter-spacing:-0.99em">숨김</p>', '<p style="font-size:10px;letter-spacing:-9.9px">숨김</p>',
            '<p style="word-spacing:-0.99em">숨김</p>', '<p style="word-spacing:-2px">숨김</p>', '<p style="-webkit-text-stroke-width:4.9px">숨김</p>',
        ]
        for body in bodies:
            with self.subTest(body=body), self.assertRaisesRegex(ValueError, "^시청 공지 본문 영역에 .*숨김"):
                parse_board_notice(_notice(body=body), board="city", notice_id="203043")

    def test_tokenizer_boundaries_follow_the_browser_in_every_python_version(self):
        """3.13.5·3.14.6에서 결과가 같아야 한다. 원문 텍스트 요소·종료 태그·CDATA 경계를 고정했다.

        3.12는 지원 대상이 아니다. `;` 없는 개체가 붙은 속성 값(`&ampx=`)을 3.13 이상·브라우저와 다르게 푼다.
        """
        def description(page):
            return parse_board_notice(page, board="city", notice_id="203043")["fields"]["description"]

        footer = '<script>footer()</script>'
        with self.assertRaises(ValueError):  # `</ script>`는 종료 태그가 아니라 스크립트가 하단까지 이어진다.
            description(_notice(body='<p>본문</p><script>x</ script><p>숨김</p>') + footer)
        # 3.13.5는 `</script foo>`를 끝으로 보지 않아 뒤따르는 본문을 삼켰다.
        self.assertEqual(description('<script>x</script foo>' + _notice()), "합성 본문")
        # `/>`가 붙어도 script는 열린 채로 다음 `</script>`까지 이어진다.
        self.assertEqual(description('<script src="a.js"/>' + _notice(body='<p>숨김</p>') + '</script>'
                                     + _notice(body='<p>뒤</p>')),
                         "뒤")
        self.assertEqual(description(_notice(body='<p>앞</p></ div><p>뒤</p>')), "앞\n뒤")
        self.assertEqual(description(_notice(body='<p title="a"class="b">본문</p>')), "본문")
        self.assertEqual(description(_notice(body='<p style="display:inline !important; opacity:0.5">본문</p>')), "본문")
        old_script = '<script><!-- document.write(\'<script src=x><\\/script>\'); //--></script>'
        self.assertEqual(description(old_script + _notice(body='<p>본문</p>')), "본문")
        for prefix in ('<title>제목 <!-- a --!></title>', '<textarea><!--</textarea>', '<iframe><!--></iframe>',
                       '<noembed><div class="bod_view"><div class="view_cont">가짜</div></div></noembed>'):
            with self.subTest(prefix=prefix):
                self.assertEqual(description(prefix + _notice()), "합성 본문")
        for page in ('<script><!--<script></script>--><p>숨김</p></script>' + _notice(),
                     '<!--><p>앞</p>-->' + _notice(), '<![CDATA[ > ' + _notice(body='<p>A</p>') + ' ]]>',
                     _notice(body='<p>앞</p></p title="a>b">'), _notice(body='<p class=a/>본문</p>'),
                     _notice(body='<plaintext>숨김'), _notice() + '<p',
                     '<svg><style>' + _notice(body='<p>진짜 본문</p>') + '</style></svg>' + _notice(body='<p>가짜</p>'),
                     '<svg><title><!--</title>' + _notice() + '--></svg>', '<math><style><!--</style></math>' + _notice(),
                     '<svg><foreignObject><div></div></foreignObject><style><!--</style></svg>' + _notice(),
                     '<svg></math><style><!--</style>' + _notice(), '<math></svg><style><!--</style>' + _notice(),
                     '<svg><foreignObject><div></svg></div></foreignObject><style><!--</style>' + _notice(),
                     '<math><mi></svg></mi><style><!--</style>' + _notice(),
                     '<svg><template/></svg>' + _notice(body='<p>진짜</p>') + '</template>' + _notice(body='<p>가짜</p>'),
                     _notice() + '<?x<b', _notice() + '<!x<b', _notice() + '<!DOCTYPE x<b',
                     '<svg><foreignObject><style/>' + _notice(body='<p>숨김</p>') + '</style></foreignObject></svg>'
                     + _notice(body='<p>뒤</p>'),
                     _notice(body='<details title="x"\xa0open><summary>요약</summary><p>숨김</p></details>'),
                     _notice(body='<p class="a"\u3000title="b">본문</p>'),
                     _notice(body='<img alt="x"\xa0src="/common/imgView.do"><p>본문</p>')):
            with self.subTest(page=page[:60]), \
                    self.assertRaisesRegex(ValueError, "^시청 공지 페이지에 브라우저와 해석이 갈리는"):
                description(page)

    def test_script_escape_scan_is_linear(self):
        started = time.monotonic()
        with self.assertRaisesRegex(ValueError, "숨김"):
            parse_board_notice(_notice(body='<p style="color:a' + ' ' * 80000 + 'b">x</p>'), board="city",
                               notice_id="203043")
        self.assertLess(time.monotonic() - started, 2)
        deep = '<script>var yh = {"a": ' + '[' * 100000 + ']' * 100000 + '};</script>'
        with self.assertRaisesRegex(ValueError, "페이지 설정"):
            parse_board_media(deep + _notice(), board="city", notice_id="203043")
        started = time.monotonic()
        attrs = ' '.join(f'data-a{n}="1"' for n in range(40000))
        self.assertEqual(parse_board_notice(_notice(body=f'<p {attrs}>본문</p>'), board="city",
                                            notice_id="203043")["fields"]["description"], "본문")
        self.assertLess(time.monotonic() - started, 3)  # 속성 중복 검사가 속성 수에 비례해야 한다.
        for unit in ('<!--', '<!---->', '<!-- -->'):
            script = '<script>' + unit * 80000 + '</script>'
            started = time.monotonic()
            with self.subTest(unit=unit):
                self.assertEqual(parse_board_notice(script + _notice(), board="city", notice_id="203043")["title"],
                                 "합성 시청 공지")
                self.assertLess(time.monotonic() - started, 2)

    def test_library_notice_is_unchanged(self):
        record = parse_library_notice(_notice(view=None), notice_id="203043")
        self.assertEqual(record["source"], "library_notice")
        self.assertEqual(record["official_url"],
                         "https://www.anseong.go.kr/library/bbs/view.do?bIdx=203043&mId=0401010000&ptIdx=16")
        with self.assertRaisesRegex(ValueError, "^도서관 공지 "):
            parse_library_notice(_notice("1", view=None), notice_id="203043")


if __name__ == "__main__":
    unittest.main()
