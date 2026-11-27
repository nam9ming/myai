import unittest

from processing.collection.libraries import parse_library_csv, parse_library_notice


def _notice(body, *, registered='2026-11-06', attachments=''):
    return f'''
    <input type="hidden" name="bIdx" value="77">
    <div class="bod_wrap">
      <div class="bod_view">
        <h4>샘플도서관 운영 변경 안내</h4>
        <div class="view_info"><ul>
          <li class="view_date"><span>등록일</span> : {registered}</li>
        </ul></div>
        <div class="view_cont"><div class="mT10"><div class="view_cont">{body}</div></div></div>
        <dl class="view_file"><dd>{attachments}</dd></dl>
      </div>
    </div>
    <p>게시판 버튼 설명</p>
    '''


class LibraryCollectionTest(unittest.TestCase):
    def test_csv_filters_exact_region_and_preserves_original_hours(self):
        text = (
            '\ufeff도서관명,시도명,시군구명,소재지도로명주소,휴관일,평일운영시작시각,'
            '토요일운영종료시각,공휴일운영시작시각,홈페이지주소\r\n'
            '샘플도서관,경기도,안성시,경기도 안성시 가상로 1,월요일,09:00,,00:00,https://example.invalid/library\r\n'
            '동명도서관,타시도,안성시,가상로 2,화요일,09:00,,00:00,\r\n'
            '인접도서관,경기도,안성시 인근,가상로 3,수요일,00:00,,00:00,\r\n'
        )
        self.assertEqual(parse_library_csv(text), [{
            'source': 'library_portal',
            'external_id': None,
            'source_record': 1,
            'title': '샘플도서관',
            'official_url': 'https://example.invalid/library',
            'fields': {'address': '경기도 안성시 가상로 1', 'closed_days': '월요일',
                       'weekday_open': '09:00', 'holiday_open': '00:00'},
        }])

    def test_csv_leaves_unusable_links_empty(self):
        for url in ('', '상세 링크', 'javascript:alert(1)', 'https://user:pass@example.invalid'):
            with self.subTest(url=url):
                data = f'시도명,시군구명,도서관명,홈페이지주소\n경기도,안성시,샘플도서관,{url}'
                self.assertIsNone(parse_library_csv(data)[0]['official_url'])

    def test_csv_rejects_malformed_input(self):
        for data in (
            '시도명,도서관명\n경기도,샘플도서관',
            '시도명,시군구명,도서관명,시도명',
            '시도명,시군구명,도서관명\n경기도,안성시',
            '시도명,시군구명,도서관명\n경기도,안성시,',
            '시도명,시군구명,도서관명\n경기도,안성시,샘플\x00도서관',
            '시도명,시군구명,도서관명\n경기도,안성시,"샘플',
        ):
            with self.subTest(data=data), self.assertRaises(ValueError):
                parse_library_csv(data)

    def test_notice_reads_text_and_posting_date_from_known_sections(self):
        html = _notice(
            '<p>자료실 이용 안내</p><br><p>11월 9일: <strong>임시 휴관</strong> &amp; 정기 점검</p>'
            '<script src="/dwr/engine.js"></script>',
        )
        for hidden in ('<script>스크립트는 본문이 아닙니다</script>', '<template><p>숨긴 본문</p></template>'):
            with self.subTest(hidden=hidden), self.assertRaisesRegex(ValueError, '숨김'):
                parse_library_notice(_notice('<p>본문</p>' + hidden), notice_id='77')
        self.assertEqual(parse_library_notice(html, notice_id='77'), {
            'source': 'library_notice',
            'external_id': '77',
            'title': '샘플도서관 운영 변경 안내',
            'official_url': 'https://www.anseong.go.kr/library/bbs/view.do?bIdx=77&mId=0401010000&ptIdx=16',
            'fields': {'description': '자료실 이용 안내\n11월 9일: 임시 휴관 & 정기 점검',
                       'published_date': '2026-11-06'},
        })

    def test_notice_keeps_mixed_body_and_flags_media(self):
        html = _notice(
            '<p>운영 변경은 첨부 및 안내문을 확인해 주세요.</p><img alt="포스터 문구">',
            attachments='<a href="/download">합성 안내문 HWPX</a>',
        )
        record = parse_library_notice(html, notice_id='77')
        self.assertEqual(record['review_flags'], ['attachment', 'inline_image'])
        self.assertEqual(record['fields']['description'], '운영 변경은 첨부 및 안내문을 확인해 주세요.')

    def test_notice_reads_table_and_list_with_optional_end_tags(self):
        html = _notice('<p>임시 운영<table><tbody><tr><td>휴관일<td>9일</table>'
                       '<ul><li>자료실<li>열람실</ul>')
        result = parse_library_notice(html, notice_id='77')
        self.assertEqual(result['fields']['description'], '임시 운영\n휴관일 9일\n자료실\n열람실')

    def test_notice_keeps_date_absent_when_unreliable(self):
        for date in ('2026-02-30', '11월 초', ''):
            with self.subTest(date=date):
                record = parse_library_notice(_notice('<p>시간은 원문 참조</p>', registered=date), notice_id='77')
                self.assertEqual(record['fields'], {'description': '시간은 원문 참조'})

    def test_notice_rejects_nontext_bodies(self):
        for html in (
            _notice('<img src="/poster.png" alt="현장 공지">'),
            _notice('', attachments='<a href="/download">합성 안내문</a>'),
        ):
            with self.subTest(html=html), self.assertRaisesRegex(ValueError, '본문 텍스트.*이미지·첨부'):
                parse_library_notice(html, notice_id='77')

    def test_notice_rejects_unknown_layout_and_mismatched_identity(self):
        for html, notice_id in (
            ('<h4>게시판 조회 실패</h4><p>페이지 없음</p>', '77'),
            ('<template>' + _notice('<p>임시 영역</p>') + '</template>', '77'),
            (_notice('<p>자료실 이용 안내</p>'), '78'),
            (_notice('<p>자료실 이용 안내</p>').replace('name="bIdx"', 'name="other"'), '77'),
            (_notice('<p>자료실 이용 안내</p>'), '77&ptIdx=2'),
            (_notice('<strong>다른 파서가 복구해야 하는 본문</div>'), '77'),
        ):
            with self.subTest(notice_id=notice_id), self.assertRaises(ValueError):
                parse_library_notice(html, notice_id=notice_id)
