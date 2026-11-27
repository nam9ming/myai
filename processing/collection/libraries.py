import csv
from datetime import date
from html.parser import HTMLParser
from io import StringIO
import re

from . import official_url
from .official_web import OFFICIAL_ORIGIN, detail_url


_LOCATION_COLUMNS = ('시도명', '시군구명', '도서관명')
_FIELDS = {
    '소재지도로명주소': 'address',
    '휴관일': 'closed_days',
    '평일운영시작시각': 'weekday_open',
    '평일운영종료시각': 'weekday_close',
    '토요일운영시작시각': 'saturday_open',
    '토요일운영종료시각': 'saturday_close',
    '공휴일운영시작시각': 'holiday_open',
    '공휴일운영종료시각': 'holiday_close',
    '운영기관명': 'operator',
}
_VOID_TAGS = frozenset('area base br col embed hr img input link meta param source track wbr'.split())
_BLOCK_TAGS = frozenset('br div h1 h2 h3 h4 h5 h6 li p table tr'.split())
_HIDDEN_TAGS = frozenset(('script', 'style', 'template'))
_CELLS = {'td', 'th'}
_TABLE_SECTIONS = {'thead', 'tbody', 'tfoot'}
_PARAGRAPH_BREAKS = frozenset('address article aside blockquote div dl fieldset footer form '
                              'h1 h2 h3 h4 h5 h6 header hr menu nav ol p pre section table ul'.split())


def parse_library_csv(text: str) -> list[dict]:
    """전국도서관표준데이터에서 안성시의 운영 기준을 읽는다."""
    if not isinstance(text, str) or '\x00' in text:
        raise ValueError('도서관 CSV 형식이 올바르지 않습니다.')
    try:
        rows = csv.reader(StringIO(text.removeprefix('\ufeff'), newline=''), strict=True)
        header = [value.strip() for value in next(rows, [])]
        if not set(_LOCATION_COLUMNS).issubset(header) or '' in header or len(set(header)) != len(header):
            raise ValueError('도서관 CSV 머리글이 올바르지 않습니다.')
        items = []
        for number, values in enumerate((row for row in rows if row), start=1):
            if len(values) != len(header):
                raise ValueError('도서관 CSV 행의 열 개수가 올바르지 않습니다.')
            row = dict(zip(header, (value.strip() for value in values)))
            if (row['시도명'], row['시군구명']) != ('경기도', '안성시'):
                continue
            if not row['도서관명']:
                raise ValueError('안성시 도서관 이름이 비어 있습니다.')
            items.append({
                'source': 'library_portal',
                'external_id': None,
                'source_record': number,
                'title': row['도서관명'],
                'official_url': official_url(row.get('홈페이지주소', '')),
                'fields': {name: row[column] for column, name in _FIELDS.items() if row.get(column)},
            })
        return items
    except csv.Error:
        raise ValueError('도서관 CSV 형식이 올바르지 않습니다.') from None


class _NoticeParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags = []
        self.found_board = False
        self.notice_ids = set()
        self.parts = {}
        self.section = None
        self.section_depth = 0
        self.hidden_depth = 0
        self.attachment_open = False
        self.review_flags = set()

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = (attrs.get('class') or '').split()
        if not self.tags:
            if tag in _HIDDEN_TAGS:
                self.hidden_depth += 1
            if self.hidden_depth:
                return
            if tag == 'input' and attrs.get('name') == 'bIdx':
                self.notice_ids.add(attrs.get('value'))
            if tag == 'div' and 'bod_view' in classes:
                if self.found_board:
                    raise ValueError('도서관 공지 본문 영역이 중복되었습니다.')
                self.found_board = True
                self.tags.append(tag)
            return

        if self.section == 'description' and not self.hidden_depth:
            optional = {
                'li': {'li'},
                'dt': {'dt', 'dd'},
                'dd': {'dt', 'dd'},
                'td': _CELLS,
                'th': _CELLS,
                'tr': _CELLS | {'tr'},
            }.get(tag, set())
            if tag in _TABLE_SECTIONS:
                optional = _CELLS | _TABLE_SECTIONS | {'tr'}
            if tag in _PARAGRAPH_BREAKS or optional:
                self.close_optional(optional | {'p'})

        if not self.hidden_depth:
            if len(self.tags) == 1 and tag == 'dl' and 'view_file' in classes:
                self.attachment_open = True
            elif self.attachment_open and tag == 'a' and (attrs.get('href') or attrs.get('onclick')):
                self.review_flags.add('attachment')
        if self.section is None and not self.hidden_depth:
            section = None
            if len(self.tags) == 1 and tag == 'h4':
                section = 'title'
            elif len(self.tags) == 1 and tag == 'div' and 'view_cont' in classes:
                section = 'description'
            elif self.tags == ['div', 'div', 'ul'] and tag == 'li' and 'view_date' in classes:
                section = 'published_date'
            if section:
                if section in self.parts:
                    raise ValueError('도서관 공지 필드가 중복되었습니다.')
                self.section = section
                self.section_depth = len(self.tags) + 1
                self.parts[section] = []

        if self.section == 'description' and tag in _BLOCK_TAGS and not self.hidden_depth:
            self.parts[self.section].append('\n')
        if self.section == 'description' and tag == 'img' and not self.hidden_depth:
            self.review_flags.add('inline_image')
        if tag not in _VOID_TAGS:
            self.tags.append(tag)
            if tag in _HIDDEN_TAGS:
                self.hidden_depth += 1

    def handle_endtag(self, tag):
        if not self.tags:
            if self.hidden_depth and tag in _HIDDEN_TAGS:
                self.hidden_depth -= 1
            return
        if tag in _VOID_TAGS:
            return
        if self.section == 'description' and not self.hidden_depth:
            optional = {'p'}
            if tag in ('ul', 'ol', 'menu'):
                optional.add('li')
            if tag == 'dl':
                optional.update(('dt', 'dd'))
            if tag in _TABLE_SECTIONS | {'tr', 'table'}:
                optional.update(_CELLS)
            if tag in _TABLE_SECTIONS | {'table'}:
                optional.add('tr')
            if tag == 'table':
                optional.update(_TABLE_SECTIONS)
            if self.tags[-1] != tag:
                self.close_optional(optional - {tag})
        if self.tags[-1] != tag:
            raise ValueError('도서관 공지 HTML 구조가 올바르지 않습니다.')
        if tag == 'dl' and len(self.tags) == 2:
            self.attachment_open = False
        if tag in _HIDDEN_TAGS:
            self.hidden_depth -= 1
        if self.section:
            if self.section == 'description' and tag in _BLOCK_TAGS and not self.hidden_depth:
                self.parts[self.section].append('\n')
            if tag in ('td', 'th') and not self.hidden_depth:
                self.parts[self.section].append(' ')
            if len(self.tags) == self.section_depth:
                self.section = None
        self.tags.pop()

    def close_optional(self, tags):
        while self.tags[-1] in tags:
            self.handle_endtag(self.tags[-1])

    def handle_data(self, data):
        if self.section and not self.hidden_depth:
            self.parts[self.section].append(data)


_MEDIA_LIMIT = 40
_IMAGE_PATH = re.compile(r'/common/imgView\.do\?attachId=[0-9a-f]{64}&fileSn=[0-9a-f]{32}&mode=origin')
_DOWNLOAD = re.compile(r"fn_egov_downFile\('([0-9a-f]{64})',[ \t]*'([0-9a-f]{32})'\);[ \t]*return false;")
_ATTACHMENT_FORMATS = {'pdf', 'hwp', 'hwpx', 'png', 'jpg', 'jpeg'}


class _MediaParser(_NoticeParser):
    def __init__(self):
        super().__init__()
        self.media = []
        self.seen_links = set()
        self.anchor = None
        self.explicit_hidden_depth = 0

    def add_media(self, kind, url, label, format_name=None):
        if url is not None:
            if (kind, url) in self.seen_links:
                return
            self.seen_links.add((kind, url))
        if len(self.media) == _MEDIA_LIMIT:
            raise ValueError('도서관 공지의 이미지·첨부 후보가 40개를 초과했습니다.')
        self.media.append({'kind': kind, 'source_url': url, 'label': label, 'format': format_name})

    def handle_starttag(self, tag, attrs):
        names = [name for name, _ in attrs]
        if not self.hidden_depth and not self.explicit_hidden_depth:
            if (not self.tags and tag == 'input' and ('name', 'bIdx') in attrs
                    and (names.count('name') > 1 or names.count('value') > 1)):
                raise ValueError('도서관 공지 번호의 HTML 속성이 중복되었습니다.')
            classes = {'bod_view'} if not self.tags else {'view_cont', 'view_file'}
            if (len(self.tags) <= 1 and tag in ('div', 'dl') and names.count('class') > 1
                    and any(name == 'class' and classes.intersection((value or '').split()) for name, value in attrs)):
                raise ValueError('도서관 공지 영역의 HTML 속성이 중복되었습니다.')
        super().handle_starttag(tag, attrs)
        if self.hidden_depth or self.explicit_hidden_depth or not self.tags:
            return
        values = dict(attrs)
        if 'hidden' in values:
            if tag not in _VOID_TAGS:
                self.explicit_hidden_depth = len(self.tags)
            return

        if tag == 'img' and self.section == 'description':
            source = values.get('src') or ''
            url = OFFICIAL_ORIGIN + source if names.count('src') == 1 and _IMAGE_PATH.fullmatch(source) else None
            label = ' '.join((values.get('alt') or '').split()) or None
            self.add_media('image', url, label)
        if tag != 'a' or not self.attachment_open:
            return
        script = values.get('onclick') or ''
        if 'btn_preview' in (values.get('class') or '').split() and script.startswith('fn_egov_preview('):
            return
        if self.anchor is not None:
            raise ValueError('도서관 공지의 첨부 링크가 중첩되었습니다.')
        if not (values.get('href') or script):
            return
        url = None
        if values.get('href') == '#' and names.count('href') == names.count('onclick') == 1:
            match = _DOWNLOAD.fullmatch(script)
            if match:
                url = f'{OFFICIAL_ORIGIN}/cmm/fms/FileDown.do?atchFileId={match[1]}&fileSn={match[2]}'
        self.anchor = (len(self.tags), url, [])

    def handle_data(self, data):
        super().handle_data(data)
        if self.anchor is not None and not self.hidden_depth and not self.explicit_hidden_depth:
            self.anchor[2].append(data)

    def handle_endtag(self, tag):
        depth = len(self.tags)
        super().handle_endtag(tag)
        if self.explicit_hidden_depth == depth and len(self.tags) < depth:
            self.explicit_hidden_depth = 0
        if tag == 'a' and self.anchor is not None and self.anchor[0] == depth:
            _, url, parts = self.anchor
            self.anchor = None
            label = ' '.join(''.join(parts).split()) or None
            filename = label or ''
            before_size, bracket, _ = filename.rpartition('[')
            if bracket and filename.endswith(']'):
                filename = before_size.rstrip()
            _, dot, extension = filename.rpartition('.')
            extension = extension.lower()
            format_name = extension if dot and extension in _ATTACHMENT_FORMATS else None
            self.add_media('attachment', url, label, 'jpeg' if format_name == 'jpg' else format_name)


def _parse_notice(text: str, notice_id: str, parser: _NoticeParser) -> str:
    if not isinstance(text, str) or '\x00' in text:
        raise ValueError('도서관 공지 HTML 형식이 올바르지 않습니다.')
    if not isinstance(notice_id, str) or not re.fullmatch(r'[1-9][0-9]*', notice_id):
        raise ValueError('도서관 공지 번호가 올바르지 않습니다.')
    parser.feed(text)
    parser.close()
    if parser.tags or not parser.found_board:
        raise ValueError('도서관 공지 본문 영역을 확인할 수 없습니다.')
    if not parser.notice_ids:
        raise ValueError('도서관 공지 HTML에 게시물 번호가 없습니다.')
    if parser.notice_ids != {notice_id}:
        raise ValueError('도서관 공지 HTML의 번호가 요청과 일치하지 않습니다.')
    title = ' '.join(''.join(parser.parts.get('title', [])).split())
    if not title:
        raise ValueError('도서관 공지 제목이 없습니다.')
    return title


def parse_library_media(text: str, *, notice_id: str) -> list[dict]:
    """공식 도서관 상세의 이미지와 첨부 후보를 확인한다."""
    parser = _MediaParser()
    _parse_notice(text, notice_id, parser)
    return parser.media


def parse_library_notice(text: str, *, notice_id: str) -> dict:
    """안성시 도서관 상세의 본문 텍스트와 게시일만 준비한다."""
    parser = _NoticeParser()
    title = _parse_notice(text, notice_id, parser)
    lines = [' '.join(line.split()) for line in ''.join(parser.parts.get('description', [])).splitlines()]
    body = '\n'.join(line for line in lines if line)
    if not body:
        detail = ' 이미지·첨부를 확인해 주세요.' if parser.review_flags else ''
        raise ValueError('도서관 공지 본문 텍스트가 없습니다.' + detail)
    fields = {'description': body}
    published = ' '.join(''.join(parser.parts.get('published_date', [])).split())
    if match := re.fullmatch(r'등록일\s*:\s*(\d{4}-\d{2}-\d{2})', published):
        try:
            fields['published_date'] = date.fromisoformat(match[1]).isoformat()
        except ValueError:
            pass
    result = {
        'source': 'library_notice',
        'external_id': notice_id,
        'title': title,
        'official_url': detail_url('living', notice_id),
        'fields': fields,
    }
    if parser.review_flags:
        result['review_flags'] = sorted(parser.review_flags)
    return result
