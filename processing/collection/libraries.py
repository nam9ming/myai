import csv
from datetime import date
from html.parser import HTMLParser
from io import StringIO
import json
import re
from types import MappingProxyType

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
_HIDDEN_ERROR = '{} 본문 영역에 화면 표시를 확정할 수 없는 숨김·미확인 표기가 있습니다.'
_MARKUP_ERROR = '{} 페이지에 브라우저와 해석이 갈리는 태그·주석·스크립트 표기가 있습니다.'
# 본문 영역은 아래 허용 목록만 받는다. 2026-11-27 실제 본문 128쪽에서 쓰인 태그·속성·스타일을 바탕으로,
# 화면에 그대로 보이는 일반 문서 요소만 더했다. 목록 밖 표기는 숨김 여부를 추정하지 않고 거부한다.
_BODY_TAGS = frozenset('a abbr address article aside b bdi bdo big blockquote br caption center cite code col colgroup '
                       'dd del details dfn div dl dt em figcaption figure font footer form h1 h2 h3 h4 h5 h6 header '
                       'hr i img input ins kbd label li main mark nav ol p pre q s samp script section small span '
                       'strike strong sub summary sup table tbody td tfoot th thead tr tt u ul var wbr'.split())
_BODY_ATTRS = frozenset('abbr action align alt bgcolor border cellpadding cellspacing cite class color colspan datetime '
                        'dir face headers height href id lang method name onclick open rel reversed rowspan scope size '
                        'span src start style summary target title type valign value width'.split())
# 크기·여백 속성은 숫자만 받는다(0이나 큰 값은 그림·글자를 감추거나 밀어낸다). 실제 그림 크기는 500 이상이었다.
_SIZE_ATTR = re.compile(r'[1-9]\d{1,3}|(?:[1-9]\d|100)%')
_SPACING_ATTR = re.compile(r'\d{1,2}')
# 브라우저와 Python 버전이 모두 같게 읽는 시작 태그 문법만 받는다(속성 사이 공백은 따옴표 뒤에서만 생략 가능).
# 따옴표 밖의 유니코드 공백(\xa0 등)은 Python 3.13.5만 속성 구분자로 읽어 받지 않는다.
_STRICT_START_TAG = re.compile(
    r'<[a-zA-Z][^\s/>]*'
    r'(?:(?:[\t\n\f\r ]+|(?<=["\']))[^\s"\'<>/=`]+'
    r'(?:[\t\n\f\r ]*=[\t\n\f\r ]*(?:"[^"]*"|\'[^\']*\'|[^\s"\'=<>`/]+(?=[\t\n\f\r >])))?)*'
    r'[\t\n\f\r ]*/?>')
# 본문 안 script는 실제 본문에 있던 첨부 파일용 외부 스크립트만 받는다. 실행 결과는 해석하지 않는다.
_BODY_SCRIPT = re.compile(r'(?:/edu)?/(?:dwr/(?:interface/EgovFileMngDwr|engine|util)|common/js/common/EgovFileUtils)\.js')
# svg·math 안(외부 콘텐츠)에서는 브라우저가 style·title 등을 원문 텍스트로 읽지 않는다.
_FOREIGN_TAGS = ('svg', 'math')
# _NoticeParser.CDATA_CONTENT_ELEMENTS: 브라우저가 내용을 원문 텍스트로 읽는 요소. Python 3.13.5는 script·style만,
# 3.14는 일부만 그렇게 읽어 결과가 달랐다(noscript는 스크립트를 켠 브라우저 기준).
_RAW_TEXT_TAGS = ('script', 'style', 'xmp', 'iframe', 'noembed', 'noframes', 'noscript', 'title', 'textarea')
_SCRIPT_OPEN = re.compile(r'<script[\t\n\f\r />]', re.I | re.A)

_NUMBER = r'(?:\d+(?:\.\d+)?|\.\d+)'
_DIMENSION = re.compile(rf'(-?)({_NUMBER})(px|pt|em|rem|%)?')
_HEX_COLOR = re.compile(r'#(?:[0-9a-f]{3}|[0-9a-f]{6})')
_COLOR_WORD = re.compile(r'[a-z]+')
_RGB = re.compile(r'rgba?\(\s*\d{1,3}\s*,\s*\d{1,3}\s*,\s*\d{1,3}\s*(?:,\s*(?:\d*\.\d+|\d+)\s*)?\)')
_KEYWORD = re.compile(r'[a-z][a-z-]*')
_BORDER_STYLES = frozenset('none solid dashed dotted double groove ridge inset outset'.split())
_DISPLAY_VALUES = frozenset('inline inline-block block flex inline-flex list-item table table-row table-cell'.split())
_FONT_SIZE_WORDS = frozenset('xx-small x-small small medium large x-large xx-large smaller larger inherit'.split())
_FONT_WEIGHTS = frozenset(['normal', 'bold', 'bolder', 'lighter', 'inherit'] + [str(n) for n in range(100, 1000, 100)])
# 단위별 하한(이상)과 허용 음수 크기(미만). 단위 없는 값은 '' 키로 다룬다.
_NON_NEGATIVE = {'': 0}
_SPACING = {'px': 3, 'pt': 3, 'em': 0.2, 'rem': 0.2}
_WORD_SPACING = {'px': 1, 'pt': 1}
_SPACING_MAXIMUM = {'px': 20, 'pt': 20, 'em': 1, 'rem': 1}
_INDENT = {'px': 100, 'pt': 100, 'em': 5, 'rem': 5}
_SIZE_MINIMUM = {'px': 10, 'pt': 10, 'em': 1, 'rem': 1, '%': 10}
_LINE_HEIGHT_MINIMUM = {'': 0.5, 'px': 5, 'pt': 5, 'em': 0.5, 'rem': 0.5, '%': 50}
_FONT_SIZE_MINIMUM = {'px': 4, 'pt': 4, 'em': 0.3, 'rem': 0.3, '%': 30}
# 큰 양수 이동·여백으로 글자를 화면 밖으로 밀어내는 경우도 받지 않는다.
_MAXIMUM = {'': 10, 'px': 1000, 'pt': 1000, 'em': 50, 'rem': 50, '%': 101}


def _dimensions(value: str, minimum: dict, negative: dict | None = None, keywords=(), count=4,
                maximum: dict = _MAXIMUM) -> bool:
    """공백으로 나뉜 길이 값을 확인한다.

    양수(와 0)는 `minimum`의 단위별 하한 이상·`maximum` 미만, 음수는 `negative`의 단위별 크기 미만만 받는다.
    단위 없는 0은 0px로 본다. 단위 없는 그 밖의 수는 `minimum`에 '' 키가 있을 때만 받는다.
    """
    tokens = value.split()
    if not 1 <= len(tokens) <= count:
        return False
    for token in tokens:
        if token in keywords:
            continue
        match = _DIMENSION.fullmatch(token)
        if not match:
            return False
        sign, number, unit = match.groups()
        number, unit = float(number), unit or ''
        if unit == '' and '' not in minimum:
            if number:
                return False
            unit = 'px'
        if number >= maximum.get(unit, 0):
            return False
        if sign and number:
            if number >= (negative or {}).get(unit, 0):
                return False
        elif unit not in minimum or number < minimum[unit]:
            return False
    return True


def _color(value: str, transparent=False) -> bool:
    """글자색은 3·6자리 16진수와 색 이름만 받는다. `transparent`가 참이면(배경·테두리) 투명과 rgb()/rgba()도 받는다."""
    if value in ('transparent', 'currentcolor'):
        return transparent
    if transparent and _RGB.fullmatch(value):
        return True
    return bool(_HEX_COLOR.fullmatch(value) or _COLOR_WORD.fullmatch(value))


def _keyword(value: str) -> bool:
    return bool(_KEYWORD.fullmatch(value))


_BOX = {'px': 0, 'pt': 0, 'em': 0, 'rem': 0, '%': 0}
_STYLE_RULES = {
    **dict.fromkeys(('padding', 'padding-top', 'padding-right', 'padding-bottom', 'padding-left', 'border-radius'),
                    lambda v: _dimensions(v, _BOX)),
    **dict.fromkeys(('margin', 'margin-top', 'margin-right', 'margin-bottom', 'margin-left'),
                    lambda v: _dimensions(v, _BOX, _INDENT, keywords=('auto',))),
    # 간격은 실제 값(글자 -1.4pt~0, 낱말 0px) 가까이만 받는다. 큰 음수는 글자를 한 자리에 겹친다.
    'letter-spacing': lambda v: v == 'normal' or _dimensions(v, _BOX, _SPACING, count=1, maximum=_SPACING_MAXIMUM),
    'word-spacing': lambda v: v == 'normal' or _dimensions(v, _BOX, _WORD_SPACING, count=1, maximum=_SPACING_MAXIMUM),
    'text-indent': lambda v: _dimensions(v, _BOX, _INDENT, count=1, maximum=_INDENT),
    **dict.fromkeys(('width', 'height', 'max-width', 'max-height'),
                    lambda v: v in ('auto', 'none') or _dimensions(v, _SIZE_MINIMUM, count=1)),
    'line-height': lambda v: v == 'normal' or _dimensions(v, _LINE_HEIGHT_MINIMUM, count=1,
                                                          maximum={**_MAXIMUM, '%': 1000}),
    'font-size': lambda v: v in _FONT_SIZE_WORDS or _dimensions(v, _FONT_SIZE_MINIMUM, count=1),
    'font-weight': lambda v: v in _FONT_WEIGHTS,
    'color': _color,
    'background-color': lambda v: _color(v, transparent=True),
    **dict.fromkeys(('border', 'border-top', 'border-right', 'border-bottom', 'border-left'),
                    lambda v: 1 <= len(v.split()) <= 3 and all(
                        t in _BORDER_STYLES or _color(t, transparent=True) or _dimensions(t, _BOX, count=1)
                        for t in v.split())),
    'display': lambda v: v in _DISPLAY_VALUES,
    'opacity': lambda v: bool(re.fullmatch(_NUMBER, v)) and 0.5 <= float(v) <= 1,
    'overflow': lambda v: v in ('visible', 'auto', 'hidden'),
    '-webkit-text-stroke-width': lambda v: _dimensions(v, {'px': 0}, count=1, maximum={'px': 1}),
    **dict.fromkeys(('orphans', 'widows'), lambda v: v.isascii() and v.isdigit()),
    # 글꼴 이름은 함수·이스케이프 없이 글자만 받는다.
    'font-family': lambda v: bool(re.fullmatch(r'[\w\s\'",.-]+', v)),
    # 아래 속성은 값이 낱말 하나일 때만 받는다. 낱말 값으로는 글자를 감추지 못한다.
    **dict.fromkeys(('text-align', 'vertical-align', 'font-style', 'font-variant-ligatures', 'font-variant-caps',
                     'font-variant-numeric', 'font-variant-east-asian', 'font-variant-alternates',
                     'font-variant-position', 'font-variant-emoji', 'font-feature-settings', 'font-kerning',
                     'font-optical-sizing', 'font-variation-settings', 'font-language-override', 'font-size-adjust',
                     'font-stretch', 'text-transform', 'white-space', 'word-break', '-ms-word-break', 'float',
                     'box-sizing', 'cursor', 'justify-content', 'align-items', 'text-autospace',
                     'text-decoration-color', 'text-decoration-style', 'text-decoration-thickness'), _keyword),
}


def _style_allowed(style: str) -> bool:
    """인라인 스타일을 선언 단위로 읽어 허용 속성·값 형태만 받는다.

    shortcut: 허용한 값끼리의 조합(글자색과 배경색이 같음, 고정 크기 상자의 넘침 잘림 등)은 해석하지 않는다.
    """
    if '/*' in style or '\\' in style:
        return False
    seen = set()
    for declaration in style.split(';'):
        if not declaration.strip():
            continue
        name, colon, value = declaration.partition(':')
        name = name.strip().lower()
        value = value.strip().lower()
        head, bang, tail = value.rpartition('!')
        if bang and tail.strip() == 'important':  # 정규식 `\s*!`는 긴 공백에서 제곱 시간이 걸린다.
            value = head.rstrip()
        if not colon or not value or '!' in value or name in seen:
            return False
        seen.add(name)
        if name.startswith('mso-'):
            # Word가 남기는 mso-* 속성은 브라우저가 해석하지 않는다.
            if '(' in value:
                return False
            continue
        rule = _STYLE_RULES.get(name)
        if rule is None or not rule(value):
            return False
    return True


def _unsafe_body_tag(tag: str, attrs: dict, names: list[str]) -> bool:
    """본문 영역의 태그·속성·스타일이 허용 목록 밖이면 숨김 범위를 추정하지 않고 거부한다.

    속성이 중복되면 이 파서는 마지막 값을, 브라우저는 첫 값을 쓰므로 중복 자체를 거부한다.
    src·href 중복은 매체 파서가 주소를 확정하지 않는 검토 후보로 따로 처리한다.
    """
    return (tag not in _BODY_TAGS or any(names.count(name) > 1 for name in set(names) - {'src', 'href'})
            or any(name in attrs and not _SIZE_ATTR.fullmatch(attrs[name] or '') for name in ('width', 'height'))
            or any(name in attrs and not _SPACING_ATTR.fullmatch(attrs[name] or '')
                   for name in ('cellpadding', 'cellspacing', 'border'))
            or any(name not in _BODY_ATTRS and not name.startswith('data-') for name in names)
            or (tag == 'details' and 'open' not in attrs)
            # 같은 name의 details는 하나만 열린다. 실제 본문의 name은 form·input에만 있었다.
            or ('name' in attrs and tag not in ('a', 'form', 'input'))
            or (tag == 'script' and (names != ['src'] or not _BODY_SCRIPT.fullmatch(attrs['src'] or '')))
            or (tag == 'input' and (attrs.get('type') or '').lower() != 'hidden')
            or not _style_allowed(attrs.get('style') or ''))


def _ends_double_escaped(data: str) -> bool:
    """브라우저의 script 이스케이프 상태를 따라가, Python이 끝낸 `</script` 앞에서 이중 이스케이프 중인지 본다.

    이중 이스케이프(`<!--` 뒤 `<script`) 안의 `</script>`에서 브라우저는 스크립트를 끝내지 않아 뒤따르는 HTML을 숨긴다.
    """
    state, i = 'data', 0
    while True:
        if state == 'data':
            i = data.find('<!--', i)
            if i < 0:
                return False
            state, i = 'escaped', i + 2  # `<!-->`처럼 `<!--`의 `--`도 이스케이프 종료에 쓰인다.
            continue
        end = data.find('-->', i)
        if state == 'escaped':
            match = _SCRIPT_OPEN.search(data, i, end if end >= 0 else len(data))
            if match:
                state, i = 'double', match.end()
                continue
        if end < 0:
            return state == 'double'
        state, i = 'data', end + 3


class _NoticeParser(HTMLParser):
    """`view_action`은 본문 영역 밖 `form#viewForm`의 게시판 주소다. 다른 게시판의 HTML을 같은 구조라는 이유로 받지 않는다.

    문서는 한 번에 넣는다. 태그·주석·원문 텍스트 요소의 경계는 Python 패치 버전과 무관하게 브라우저(HTML5) 규칙으로
    고정하고, 이 파서가 브라우저와 다르게 읽을 수 있는 표기는 문서 어디서든 거부한다.
    """

    CDATA_CONTENT_ELEMENTS = _RAW_TEXT_TAGS
    RCDATA_CONTENT_ELEMENTS = ()

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
        self.foreign_depth = 0
        self.attachment_open = False
        self.review_flags = set()

    def parse_starttag(self, i):
        self.tag_reported = False
        k = super().parse_starttag(i)
        if k < 0 or not self.tag_reported:
            # 닫히지 않았거나 Python이 글자로 넘긴 시작 태그다. 브라우저는 태그로 읽으므로 받지 않는다.
            raise ValueError(_MARKUP_ERROR.format(self.label))
        return k

    def parse_endtag(self, i):
        """종료 태그를 브라우저처럼 읽는다. `</ x>`는 무시되는 가짜 주석이고, 원문 텍스트 요소는 여기서 끝난다."""
        rawdata = self.rawdata
        end = rawdata.find('>', i + 2)
        if end < 0 or '"' in rawdata[i:end] or "'" in rawdata[i:end]:
            raise ValueError(_MARKUP_ERROR.format(self.label))
        if self.cdata_elem is not None:
            # set_cdata_mode의 패턴이 `</이름` 뒤 구분 문자까지 확인했다.
            tag = self.cdata_elem
            self.clear_cdata_mode()
        else:
            match = re.match(r'</([a-zA-Z][^\t\n\f\r />]*)', rawdata[i:end])
            if match is None:
                return end + 1
            tag = match.group(1).lower()
        self.handle_endtag(tag)
        return end + 1

    def set_cdata_mode(self, elem, **options):
        super().set_cdata_mode(elem, **options)
        # 원문 텍스트는 브라우저처럼 `</이름` 뒤에 공백·`/`·`>`가 올 때만 끝난다(3.13.5는 `</ 이름`에서도 끝냈다).
        self.interesting = re.compile(r'</%s(?=[\t\n\f\r />])' % re.escape(self.cdata_elem), re.I | re.A)

    def parse_pi(self, i):
        if self.rawdata.find('>', i + 2) < 0:
            # 닫히지 않은 `<?`는 3.13.5는 글자로, 3.14는 문서 끝까지의 처리 지시로 읽었다.
            raise ValueError(_MARKUP_ERROR.format(self.label))
        return super().parse_pi(i)

    def parse_html_declaration(self, i):
        if self.rawdata.startswith('<![', i) or self.rawdata.find('>', i + 2) < 0:
            # HTML 문서에서 브라우저는 `<![CDATA[`를 첫 `>`에서 끝나는 가짜 주석으로 읽고, Python은 `]]>`까지 삼킨다.
            # 닫히지 않은 `<!`도 Python 버전마다 글자 또는 문서 끝까지의 선언으로 달리 읽는다.
            raise ValueError(_MARKUP_ERROR.format(self.label))
        return super().parse_html_declaration(i)

    def handle_startendtag(self, tag, attrs):
        # HTML에서 브라우저는 빈 요소가 아닌 태그의 `/>`를 무시하고, 원문 텍스트 요소도 여기서 내용 읽기를 시작한다.
        # svg·math 안과 `<svg/>`·`<math/>` 자신은 `/>`에서 닫힌다.
        foreign = self.foreign_depth
        self.handle_starttag(tag, attrs)
        if tag in _FOREIGN_TAGS:
            self.foreign_depth -= 1
        elif tag in self.CDATA_CONTENT_ELEMENTS:
            if foreign:
                # foreignObject 같은 통합 지점에서는 브라우저가 `/>`를 무시하고 원문 텍스트를 시작한다. 위치를 가리지 않고 거부한다.
                raise ValueError(_MARKUP_ERROR.format(self.label))
            self.set_cdata_mode(tag)

    def handle_starttag(self, tag, attrs):
        self.tag_reported = True
        if tag == 'plaintext' or not _STRICT_START_TAG.fullmatch(self.get_starttag_text() or ''):
            raise ValueError(_MARKUP_ERROR.format(self.label))
        names = [name for name, _ in attrs]
        if tag in _FOREIGN_TAGS:
            # shortcut: 브라우저가 svg를 닫는 규칙(탈출 태그, 무시되는 `</svg>`)은 따라 하지 않고 종료 태그에서도 깊이를
            # 줄이지 않는다. 한 번 열리면 문서 끝까지 외래 콘텐츠로 볼 뿐이라 원문 텍스트·template 거부만 늘어난다.
            self.foreign_depth += 1
        elif tag == 'template' and self.foreign_depth:
            # svg·math 안의 template은 HTML template이 아니라 내용을 숨기지 않는다. 숨김 깊이를 셀 수 없어 받지 않는다.
            raise ValueError(_MARKUP_ERROR.format(self.label))
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
                if _unsafe_body_tag(tag, attrs, names):
                    raise ValueError(_HIDDEN_ERROR.format(self.label))
                self.found_board = True
                self.tags.append(tag)
            return

        if not self.hidden_depth and _unsafe_body_tag(tag, attrs, names):
            raise ValueError(_HIDDEN_ERROR.format(self.label))
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

    def parse_comment(self, i, report=True):
        """주석 종료 규칙을 Python 패치 버전과 무관하게 `-->`로 고정한다.

        3.13.5는 `--\\s*>`, 3.14는 `--!?>`(없으면 `<!-->`·`<!--->`)에서 닫아 같은 HTML의 결과가 달랐다. 브라우저와 해석이 갈리는
        `<!-->`·`<!--->`·`--!>`와 닫히지 않은 주석(문서를 한 번에 넣으므로 문서 끝까지 이어진다)은 문서 어디서든 거부한다.
        """
        rawdata = self.rawdata
        end = rawdata.find('-->', i + 4)
        if end < 0 or rawdata.startswith(('>', '->'), i + 4) or '--!>' in rawdata[i + 4:end]:
            raise ValueError(_MARKUP_ERROR.format(self.label))
        if report:
            self.handle_comment(rawdata[i + 4:end])
        return end + 3

    def handle_data(self, data):
        if self.cdata_elem == 'script' and _ends_double_escaped(data):
            raise ValueError(_MARKUP_ERROR.format(self.label))
        if self.cdata_elem and self.foreign_depth and '<' in data:
            # 브라우저는 svg·math 안의 이 내용을 태그·주석으로 읽는다. 글자만 있을 때는 두 해석이 같다.
            raise ValueError(_MARKUP_ERROR.format(self.label))
        if self.cdata_elem == 'script' and self.tags and data.strip():
            # 본문 안 인라인 스크립트는 읽는 도중 실행되어 뒤따르는 본문을 숨길 수 있다.
            raise ValueError(_HIDDEN_ERROR.format(self.label))
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
        if not self.hidden_depth:
            if (not self.tags and tag == 'input' and ('name', 'bIdx') in attrs
                    and (names.count('name') > 1 or names.count('value') > 1)):
                raise ValueError(self.label + ' 번호의 HTML 속성이 중복되었습니다.')
            classes = {'bod_view'} if not self.tags else {'view_cont', 'view_file', self.title_class} - {None}
            if (len(self.tags) <= 1 and tag in ('div', 'dl') and names.count('class') > 1
                    and any(name == 'class' and classes.intersection((value or '').split()) for name, value in attrs)):
                raise ValueError(self.label + ' 영역의 HTML 속성이 중복되었습니다.')
        # 본문 영역의 hidden 요소는 기반 파서가 거부하므로 여기서 따로 건너뛰지 않는다.
        super().handle_starttag(tag, attrs)
        if self.hidden_depth or not self.tags:
            return
        values = dict(attrs)

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
        if self.anchor is not None and not self.hidden_depth:
            self.anchor[2].append(data)

    def handle_endtag(self, tag):
        depth = len(self.tags)
        super().handle_endtag(tag)
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


# 페이지 설정은 `<script>var yh = {...};</script>` 하나로 선언되고 객체는 JSON 형식이다.
_PAGE_CONFIG = re.compile(r'\s*var\s+yh\s*=\s*(\{.*\})\s*;\s*', re.S)


def _unique_object(pairs):
    keys = [key for key, _ in pairs]
    if len(set(keys)) != len(keys):
        raise ValueError('duplicate key')
    return dict(pairs)


def _declared_context_paths(scripts: list[str]) -> list[object]:
    """설정 스크립트 전체가 JSON 객체 대입일 때만 contextPath를 선언으로 본다. 주석·문자열·다른 스크립트는 무시한다."""
    values = []
    for script in scripts:
        match = _PAGE_CONFIG.fullmatch(script)
        if match is None:
            continue
        try:
            config = json.loads(match[1], object_pairs_hook=_unique_object)
        except (ValueError, RecursionError):  # 깊은 중첩은 3.13에서만 RecursionError가 나 선언이 아닌 것으로 같게 다룬다.
            continue
        if isinstance(config, dict) and 'contextPath' in config:
            values.append(config['contextPath'])
    return values


def _media(text: str, notice_id: str, parser: '_MediaParser') -> list[dict]:
    """첨부 주소는 페이지 스크립트의 contextPath로 만들어지므로 선언값이 게시판과 다르면 받지 않는다.

    루트가 아닌 사이트 경로를 쓰는 게시판은 그 선언이 정확히 한 번 있어야 주소를 만든다.
    """
    _parse_notice(text, notice_id, parser)
    declared = _declared_context_paths(parser.scripts)
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


# 게시판별 파서 버전. 그 게시판의 parse_board_notice 출력이나 허용 규칙이 바뀌면 해당 값만 올린다.
# 공유하는 _NoticeParser·_notice_record를 바꾸면 영향을 받는 모든 게시판의 값을 올린다.
# 이력(이전 공유 이름 board-notice-parser): v1 시작, v2 시청 viewForm 필수, 안성배움e 추가.
# v3: 본문 영역(div.bod_view 포함)은 허용 목록의 태그·속성·인라인 스타일만 받고, 문서 전체의 태그·주석·
#     원문 텍스트 경계를 브라우저 규칙으로 고정해 해석이 갈리는 표기를 거부한다.
BOARD_PARSER_VERSIONS = MappingProxyType({
    'city': 'city-notice-parser-v3',
    'edu': 'edu-notice-parser-v3',
})


def board_parser_version(board: str) -> str:
    board_info(board)
    if board not in BOARD_PARSER_VERSIONS:  # 시험이 BOARDS와 키가 같음을 보장하지만 등록 누락을 ValueError로 알린다.
        raise ValueError('게시판의 파서 버전이 등록되지 않았습니다.')
    return BOARD_PARSER_VERSIONS[board]


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
