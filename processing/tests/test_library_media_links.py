import unittest

from processing.collection.libraries import parse_library_media, parse_library_notice
from processing.tests.test_library_collection import _notice


ATTACH_ID = 'a' * 64
FILE_SN = 'b' * 32
IMAGE_PATH = f'/common/imgView.do?attachId={ATTACH_ID}&amp;fileSn={FILE_SN}&amp;mode=origin'
ORIGIN = 'https://www.anseong.go.kr'
ATTACHMENT = f'{ORIGIN}/cmm/fms/FileDown.do?atchFileId={ATTACH_ID}&fileSn={FILE_SN}'


def _link(label, serial=FILE_SN):
    return f"""<a href="#" onclick="fn_egov_downFile('{ATTACH_ID}','{serial}'); return false;">{label}</a>"""


class LibraryMediaLinksTest(unittest.TestCase):
    def test_image_and_attachment_preserve_first_seen_order_and_labels(self):
        page = _notice(
            f'<p>일부 정보는 안내 이미지를 참조하세요.</p><img src="{IMAGE_PATH}" alt=" 안내  이미지 ">',
            attachments=_link('운영 일정.HWPX <span>[63.9 KByte]</span>') + _link('반복 링크.hwp')
            + """<a href="#" class="btn_preview" onclick="fn_egov_preview('sample'); return false;">바로 보기</a>"""
            + _link('신청 안내.hwp [4 KByte]', 'c' * 32),
        )
        self.assertEqual(parse_library_media(page, notice_id='77'), [
            {'kind': 'image', 'source_url': ORIGIN + IMAGE_PATH.replace('&amp;', '&'),
             'label': '안내 이미지', 'format': None},
            {'kind': 'attachment', 'source_url': ATTACHMENT,
             'label': '운영 일정.HWPX [63.9 KByte]', 'format': 'hwpx'},
            {'kind': 'attachment', 'source_url': ATTACHMENT.replace(FILE_SN, 'c' * 32),
             'label': '신청 안내.hwp [4 KByte]', 'format': 'hwp'},
        ])

    def test_discovery_reads_media_only_notices_but_plain_parser_still_rejects(self):
        for page, kind in (
            (_notice(f'<img src="{IMAGE_PATH}">'), 'image'),
            (_notice('', attachments=_link('공지.pdf')), 'attachment'),
        ):
            with self.subTest(kind=kind):
                self.assertEqual(parse_library_media(page, notice_id='77')[0]['kind'], kind)
                with self.assertRaisesRegex(ValueError, '본문 텍스트'):
                    parse_library_notice(page, notice_id='77')

    def test_unknown_paths_and_scripts_stay_review_candidates(self):
        page = _notice(
            f'<img src="//invalid.example/a.png" src="{IMAGE_PATH}">'
            f'<img src="{IMAGE_PATH}&amp;return=https://invalid.example/" alt="외부 배너">',
            attachments='<a href="https://invalid.example/file.jpg">포스터.JPG</a>'
            + _link('안내.xlsx').replace('return false;', 'unrecognizedAction(); return false;'),
        )
        self.assertEqual(parse_library_media(page, notice_id='77'), [
            {'kind': 'image', 'source_url': None, 'label': None, 'format': None},
            {'kind': 'image', 'source_url': None, 'label': '외부 배너', 'format': None},
            {'kind': 'attachment', 'source_url': None, 'label': '포스터.JPG', 'format': 'jpeg'},
            {'kind': 'attachment', 'source_url': None, 'label': '안내.xlsx', 'format': None},
        ])

    def test_ignores_hidden_escaped_and_out_of_scope_markup(self):
        img = f'<img src="{IMAGE_PATH}">'
        link = _link('샘플.pdf')
        page = img + _notice(
            f'<template>{img}</template><script>{img}</script><div hidden>{img}</div>'
            '<p>&lt;img src="/external"&gt;</p>'
            f'<dl class="view_file"><dd>{link}</dd></dl>',
            attachments=f'<template>{link}</template><span hidden>{link}</span>',
        ) + link
        self.assertEqual(parse_library_media(page, notice_id='77'), [])

    def test_reuses_notice_identity_and_structure_validation(self):
        for html, notice_id in (
            ('<input name="bIdx" value="77"><img src="/external">', '77'),
            (_notice('<img src="/external">'), '78'),
            (_notice('').replace('샘플도서관 운영 변경 안내', ''), '77'),
            (_notice('', attachments=_link(_link('겹친 링크.pdf'))), '77'),
        ):
            with self.subTest(html=html, notice_id=notice_id), self.assertRaises(ValueError):
                parse_library_media(html, notice_id=notice_id)

    def test_refuses_to_silently_drop_excess_candidates(self):
        page = _notice('<img alt="샘플 포스터">' * 40)
        self.assertEqual(len(parse_library_media(page, notice_id='77')), 40)
        with self.assertRaisesRegex(ValueError, '40개'):
            parse_library_media(_notice('<img alt="샘플 포스터">' * 41), notice_id='77')

    def test_duplicate_identity_and_container_attributes_are_ambiguous(self):
        page = _notice(f'<img src="{IMAGE_PATH}">', attachments=_link('샘플.pdf'))
        for old, replacement in (
            ('name="bIdx"', 'name="hidden" name="bIdx"'),
            ('value="77"', 'value="78" value="77"'),
            ('class="bod_view"', 'class="other" class="bod_view"'),
            ('class="view_cont"', 'class="view_cont" class="other"'),
            ('class="view_file"', 'class="other" class="view_file"'),
        ):
            with self.subTest(attribute=old):
                self.assertIn(old, page)
                with self.assertRaisesRegex(ValueError, '속성이 중복'):
                    parse_library_media(page.replace(old, replacement), notice_id='77')

    def test_long_label_uses_only_the_final_file_suffix(self):
        label = 'archive.pdf[' * 10_000 + 'notice.HWPX [8 KByte]'
        result = parse_library_media(_notice('', attachments=_link(label)), notice_id='77')
        self.assertEqual(result[0]['format'], 'hwpx')
