import csv
from datetime import date
from html.parser import HTMLParser
from io import StringIO
import re

from . import official_url
from .official_web import OFFICIAL_ORIGIN, board as board_info, board_detail_url, detail_url


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


_LIBRARY_VIEW = '/library/bbs/view.do?ptIdx=16&mId=0401010000'


class _NoticeParser(HTMLParser):
    """`view_action`은 본문 영역 밖 `form#viewForm`의 게시판 주소다. 다른 게시판의 HTML을 같은 구조라는 이유로 받지 않는다."""

    def __init__(self, label='도서관 공지', view_action=_LIBRARY_VIEW, require_view=False, title_class=None,
                 context_path=''):
        super().__init__()
        self.label = label
        self.title_class = title_class
        self.context_path = context_path
        self.title_format_changed = False
        # 본문 영역 밖 최상위 <script>의 내용. 페이지 설정(contextPath)은 여기서만 읽는다.
        self.scripts = []
        self.script = None
        self.view_action = view_action
        self.require_view = require_view
        self.view_actions = []
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
        names = [name for name, _ in attrs]
        view_form = tag == 'form' and ('id', 'viewForm') in attrs
        attrs = dict(attrs)
        classes = (attrs.get('class') or '').split()
        if not self.tags:
            if tag == 'script' and not self.hidden_depth:
                self.script = []
            if tag in _HIDDEN_TAGS:
                self.hidden_depth += 1
            if self.hidden_depth:
                return
            if view_form:
                if names.count('id') != 1 or names.count('action') != 1:
                    raise ValueError(self.label + ' 상세 폼의 HTML 속성이 중복되었습니다.')
                self.view_actions.append(attrs.get('action'))
            if tag == 'input' and attrs.get('name') == 'bIdx':
                self.notice_ids.add(attrs.get('value'))
            if tag == 'div' and 'bod_view' in classes:
                if self.found_board:
                    raise ValueError(self.label + ' 본문 영역이 중복되었습니다.')
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
                if self.title_class:
                    # 게시판 대조 오류가 먼저 보이도록 파싱이 끝난 뒤에 알린다.
                    self.title_format_changed = True
                else:
                    section = 'title'
            elif self.title_class and len(self.tags) == 1 and tag == 'div' and self.title_class in classes:
                section = 'title'
            elif len(self.tags) == 1 and tag == 'div' and 'view_cont' in classes:
                section = 'description'
            elif self.tags == ['div', 'div', 'ul'] and tag == 'li' and 'view_date' in classes:
                section = 'published_date'
            if section:
                if section in self.parts:
                    raise ValueError(self.label + ' 필드가 중복되었습니다.')
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
            if tag == 'script' and self.script is not None and not self.hidden_depth:
                self.scripts.append(''.join(self.script))
                self.script = None
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
            raise ValueError(self.label + ' HTML 구조가 올바르지 않습니다.')
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
        if self.script is not None and not self.tags and self.hidden_depth == 1:
            self.script.append(data)
        if self.section and not self.hidden_depth:
            self.parts[self.section].append(data)


_MEDIA_LIMIT = 40
_IMAGE_PATH = re.compile(r'/common/imgView\.do\?attachId=[0-9a-f]{64}&fileSn=[0-9a-f]{32}&mode=origin')
_DOWNLOAD = re.compile(r"fn_egov_downFile\('([0-9a-f]{64})',[ \t]*'([0-9a-f]{32})'\);[ \t]*return false;")
_ATTACHMENT_FORMATS = {'pdf', 'hwp', 'hwpx', 'png', 'jpg', 'jpeg'}


class _MediaParser(_NoticeParser):
    def __init__(self, label='도서관 공지', **board):
        super().__init__(label, **board)
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
            raise ValueError(self.label + '의 이미지·첨부 후보가 40개를 초과했습니다.')
        self.media.append({'kind': kind, 'source_url': url, 'label': label, 'format': format_name})

    def handle_starttag(self, tag, attrs):
        names = [name for name, _ in attrs]
        if not self.hidden_depth and not self.explicit_hidden_depth:
            if (not self.tags and tag == 'input' and ('name', 'bIdx') in attrs
                    and (names.count('name') > 1 or names.count('value') > 1)):
                raise ValueError(self.label + ' 번호의 HTML 속성이 중복되었습니다.')
            classes = {'bod_view'} if not self.tags else {'view_cont', 'view_file', self.title_class} - {None}
            if (len(self.tags) <= 1 and tag in ('div', 'dl') and names.count('class') > 1
                    and any(name == 'class' and classes.intersection((value or '').split()) for name, value in attrs)):
                raise ValueError(self.label + ' 영역의 HTML 속성이 중복되었습니다.')
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
            raise ValueError(self.label + '의 첨부 링크가 중첩되었습니다.')
        if not (values.get('href') or script):
            return
        url = None
        if values.get('href') == '#' and names.count('href') == names.count('onclick') == 1:
            match = _DOWNLOAD.fullmatch(script)
            if match:
                url = (f'{OFFICIAL_ORIGIN}{self.context_path}/cmm/fms/FileDown.do'
                       f'?atchFileId={match[1]}&fileSn={match[2]}')
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
        raise ValueError(parser.label + ' HTML 형식이 올바르지 않습니다.')
    if not isinstance(notice_id, str) or not re.fullmatch(r'[1-9][0-9]*', notice_id):
        raise ValueError(parser.label + ' 번호가 올바르지 않습니다.')
    parser.feed(text)
    parser.close()
    if parser.tags or not parser.found_board:
        raise ValueError(parser.label + ' 본문 영역을 확인할 수 없습니다.')
    if not parser.notice_ids:
        raise ValueError(parser.label + ' HTML에 게시물 번호가 없습니다.')
    if parser.notice_ids != {notice_id}:
        raise ValueError(parser.label + ' HTML의 번호가 요청과 일치하지 않습니다.')
    views = parser.view_actions
    if len(views) > 1 or (views and views[0] != parser.view_action) or (parser.require_view and not views):
        raise ValueError(parser.label + ' HTML의 게시판이 요청과 일치하지 않습니다.')
    if parser.title_format_changed:
        raise ValueError(parser.label + ' 제목 영역의 형식이 바뀌었습니다.')
    title = ' '.join(''.join(parser.parts.get('title', [])).split())
    if not title:
        raise ValueError(parser.label + ' 제목이 없습니다.')
    return title


_CONTEXT_PATH = re.compile(r'"contextPath"\s*:\s*"([^"]*)"')


def _media(text: str, notice_id: str, parser: '_MediaParser') -> list[dict]:
    """첨부 주소는 페이지 스크립트의 contextPath로 만들어지므로 선언값이 게시판과 다르면 받지 않는다.

    루트가 아닌 사이트 경로를 쓰는 게시판은 그 선언이 정확히 한 번 있어야 주소를 만든다.
    """
    _parse_notice(text, notice_id, parser)
    declared = [value for script in parser.scripts for value in _CONTEXT_PATH.findall(script)]
    if (any(value != parser.context_path for value in declared)
            or (parser.context_path and len(declared) != 1)):
        raise ValueError(parser.label + ' 페이지의 사이트 경로가 게시판과 일치하지 않습니다.')
    return parser.media


def parse_library_media(text: str, *, notice_id: str) -> list[dict]:
    """공식 도서관 상세의 이미지와 첨부 후보를 확인한다."""
    return _media(text, notice_id, _MediaParser())


def _board_options(board: str) -> dict:
    info = board_info(board)
    return {'label': info.label, 'view_action': f'{info.prefix}/view.do?ptIdx={info.pt_idx}&mId={info.menu}',
            'require_view': True, 'title_class': info.title_class, 'context_path': info.context_path}


def parse_board_media(text: str, *, board: str, notice_id: str) -> list[dict]:
    """같은 게시판 구조를 쓰는 시청·안성배움e 공지 상세의 이미지와 첨부 후보를 확인한다."""
    parser = _MediaParser(**_board_options(board))
    board_detail_url(board, notice_id)  # HTML을 읽기 전에 18자리 번호 한도를 확인한다.
    return _media(text, notice_id, parser)


def parse_library_notice(text: str, *, notice_id: str) -> dict:
    """안성시 도서관 상세의 본문 텍스트와 게시일만 준비한다."""
    return _notice_record(_NoticeParser(), text, notice_id, 'library_notice', lambda: detail_url('living', notice_id))


# parse_board_notice나 공유하는 _NoticeParser·_notice_record의 출력 또는 허용 규칙이 바뀌면 함께 올린다.
# v2: 시청 상세의 viewForm 게시판 주소를 필수로 대조한다.
# v2 유지: 안성배움e 추가는 새 게시판 설정만 더하며 시청 결과와 허용 규칙은 그대로다.
# 버전은 모든 게시판이 함께 쓰므로 한 게시판의 규칙을 바꿔도 다른 게시판 기록을 다시 수집해야 한다.
BOARD_PARSER_VERSION = 'board-notice-parser-v2'


def parse_board_notice(text: str, *, board: str, notice_id: str) -> dict:
    """같은 게시판 구조를 쓰는 시청·안성배움e 공지 상세의 본문 텍스트와 게시일만 준비한다."""
    source = board_info(board).source
    url = board_detail_url(board, notice_id)
    return _notice_record(_NoticeParser(**_board_options(board)), text, notice_id, source, lambda: url)


def _notice_record(parser: _NoticeParser, text: str, notice_id: str, source: str, url) -> dict:
    title = _parse_notice(text, notice_id, parser)
    lines = [' '.join(line.split()) for line in ''.join(parser.parts.get('description', [])).splitlines()]
    body = '\n'.join(line for line in lines if line)
    if not body:
        detail = ' 이미지·첨부를 확인해 주세요.' if parser.review_flags else ''
        raise ValueError(parser.label + ' 본문 텍스트가 없습니다.' + detail)
    fields = {'description': body}
    published = ' '.join(''.join(parser.parts.get('published_date', [])).split())
    if match := re.fullmatch(r'등록일\s*:\s*(\d{4}-\d{2}-\d{2})', published):
        try:
            fields['published_date'] = date.fromisoformat(match[1]).isoformat()
        except ValueError:
            pass
    result = {
        'source': source,
        'external_id': notice_id,
        'title': title,
        'official_url': url(),
        'fields': fields,
    }
    if parser.review_flags:
        result['review_flags'] = sorted(parser.review_flags)
    return result
