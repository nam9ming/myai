"""브라우저(HTML5)와 Python 3.13·3.14가 같은 경계로 읽는 HTML만 받는 공용 파서 기반.

표준 `html.parser`는 패치 버전마다 주석 종료, 원문 텍스트 요소, 종료 태그, 선언, 속성 구분자를 다르게 읽는다.
이 차이 때문에 같은 원본이 버전마다 다른 결과를 내거나, 화면에 없는 글을 본문으로 받거나 보이는 글을 버릴 수 있다.
`PinnedHTMLParser`는 그 경계를 브라우저 규칙으로 고정하고, 두 해석이 갈릴 수 있는 표기는 문서 어디서든 거부한다.
문서는 한 번에 `feed`한 뒤 `close`해야 한다(닫히지 않은 표기를 문서 끝으로 본다).

하위 클래스는 `handle_starttag`·`handle_data`를 재정의할 때 먼저 `super()`를 부른다. 시작 태그를 보고하지 않으면
`parse_starttag`가 거부하므로, 검사를 빠뜨린 하위 클래스도 조용히 통과하지 않는다. 오류 문구는 `markup_error`로 바꾼다.
"""

import re
from html.parser import HTMLParser

# 따옴표 밖의 유니코드 공백(\xa0 등)은 Python 3.13.5만 속성 구분자로 읽어 받지 않는다(속성 사이 공백은 따옴표 뒤에서만 생략 가능).
STRICT_START_TAG = re.compile(
    r'<[a-zA-Z][^\s/>]*'
    r'(?:(?:[\t\n\f\r ]+|(?<=["\']))[^\s"\'<>/=`]+'
    r'(?:[\t\n\f\r ]*=[\t\n\f\r ]*(?:"[^"]*"|\'[^\']*\'|[^\s"\'=<>`/]+(?=[\t\n\f\r >])))?)*'
    r'[\t\n\f\r ]*/?>')
# svg·math 안(외부 콘텐츠)에서는 브라우저가 style·title 등을 원문 텍스트로 읽지 않는다.
FOREIGN_TAGS = ('svg', 'math')
# 브라우저가 내용을 원문 텍스트로 읽는 요소. Python 3.13.5는 script·style만, 3.14는 일부만 그렇게 읽어 결과가 달랐다
# (noscript는 스크립트를 켠 브라우저 기준).
RAW_TEXT_TAGS = ('script', 'style', 'xmp', 'iframe', 'noembed', 'noframes', 'noscript', 'title', 'textarea')
_SCRIPT_OPEN = re.compile(r'<script[\t\n\f\r />]', re.I | re.A)


def ends_double_escaped(data: str) -> bool:
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


class PinnedHTMLParser(HTMLParser):
    CDATA_CONTENT_ELEMENTS = RAW_TEXT_TAGS
    RCDATA_CONTENT_ELEMENTS = ()

    def __init__(self):
        super().__init__()
        self.foreign_depth = 0
        self.tag_reported = False

    def markup_error(self) -> ValueError:
        return ValueError('HTML에 브라우저와 해석이 갈리는 태그·주석·스크립트 표기가 있습니다.')

    def parse_starttag(self, i):
        self.tag_reported = False
        k = super().parse_starttag(i)
        if k < 0 or not self.tag_reported:
            # 닫히지 않았거나 Python이 글자로 넘긴 시작 태그다. 브라우저는 태그로 읽으므로 받지 않는다.
            raise self.markup_error()
        return k

    def parse_endtag(self, i):
        """종료 태그를 브라우저처럼 읽는다. `</ x>`는 무시되는 가짜 주석이고, 원문 텍스트 요소는 여기서 끝난다."""
        rawdata = self.rawdata
        end = rawdata.find('>', i + 2)
        if end < 0 or '"' in rawdata[i:end] or "'" in rawdata[i:end]:
            raise self.markup_error()
        if self.cdata_elem is not None:
            # set_cdata_mode의 패턴이 `</이름` 뒤 구분 문자까지 확인했다.
            tag = self.cdata_elem
            self.clear_cdata_mode()
        else:
            match = re.match(r'</([a-zA-Z][^\t\n\f\r />]*)', rawdata[i:end])
            if match is None:
                return end + 1
            tag = match.group(1).lower()
            if tag == 'br':
                # 브라우저는 `</br>`을 `<br>`로 읽어 줄을 바꾸고, Python은 종료 태그로 넘긴다. 실제 원본에 없어 받지 않는다.
                raise self.markup_error()
        self.handle_endtag(tag)
        return end + 1

    def set_cdata_mode(self, elem, **options):
        super().set_cdata_mode(elem, **options)
        # 원문 텍스트는 브라우저처럼 `</이름` 뒤에 공백·`/`·`>`가 올 때만 끝난다(3.13.5는 `</ 이름`에서도 끝냈다).
        self.interesting = re.compile(r'</%s(?=[\t\n\f\r />])' % re.escape(self.cdata_elem), re.I | re.A)

    def parse_pi(self, i):
        if self.rawdata.find('>', i + 2) < 0:
            # 닫히지 않은 `<?`는 3.13.5는 글자로, 3.14는 문서 끝까지의 처리 지시로 읽었다.
            raise self.markup_error()
        return super().parse_pi(i)

    def parse_html_declaration(self, i):
        end = self.rawdata.find('>', i + 2)
        # 따옴표가 든 선언(`<!DOCTYPE html PUBLIC "x>`)은 브라우저가 닫는 따옴표까지 읽어 경계가 갈린다.
        # HTML 문서에서 브라우저는 `<![CDATA[`를 첫 `>`에서 끝나는 가짜 주석으로 읽고, Python은 `]]>`까지 삼킨다.
        # 닫히지 않은 `<!`도 Python 버전마다 글자 또는 문서 끝까지의 선언으로 달리 읽는다.
        if self.rawdata.startswith('<![', i) or end < 0 or '"' in self.rawdata[i:end] or "'" in self.rawdata[i:end]:
            raise self.markup_error()
        return super().parse_html_declaration(i)

    def parse_comment(self, i, report=True):
        """주석 종료 규칙을 Python 패치 버전과 무관하게 `-->`로 고정한다.

        3.13.5는 `--\\s*>`, 3.14는 `--!?>`(없으면 `<!-->`·`<!--->`)에서 닫아 같은 HTML의 결과가 달랐다. 브라우저와 해석이 갈리는
        `<!-->`·`<!--->`·`--!>`와 닫히지 않은 주석(문서를 한 번에 넣으므로 문서 끝까지 이어진다)은 문서 어디서든 거부한다.
        """
        rawdata = self.rawdata
        end = rawdata.find('-->', i + 4)
        if end < 0 or rawdata.startswith(('>', '->'), i + 4) or '--!>' in rawdata[i + 4:end]:
            raise self.markup_error()
        if report:
            self.handle_comment(rawdata[i + 4:end])
        return end + 3

    def handle_startendtag(self, tag, attrs):
        # HTML에서 브라우저는 빈 요소가 아닌 태그의 `/>`를 무시하고, 원문 텍스트 요소도 여기서 내용 읽기를 시작한다.
        # svg·math 안과 `<svg/>`·`<math/>` 자신은 `/>`에서 닫힌다.
        foreign = self.foreign_depth
        self.handle_starttag(tag, attrs)
        if tag in FOREIGN_TAGS:
            self.foreign_depth -= 1
        elif tag in self.CDATA_CONTENT_ELEMENTS:
            if foreign:
                # foreignObject 같은 통합 지점에서는 브라우저가 `/>`를 무시하고 원문 텍스트를 시작한다. 위치를 가리지 않고 거부한다.
                raise self.markup_error()
            self.set_cdata_mode(tag)

    def handle_starttag(self, tag, attrs):
        self.tag_reported = True
        if tag == 'plaintext' or not STRICT_START_TAG.fullmatch(self.get_starttag_text() or ''):
            raise self.markup_error()
        if tag in FOREIGN_TAGS:
            # shortcut: 브라우저가 svg를 닫는 규칙(탈출 태그, 무시되는 `</svg>`)은 따라 하지 않고 종료 태그에서도 깊이를
            # 줄이지 않는다. 한 번 열리면 문서 끝까지 외래 콘텐츠로 볼 뿐이라 원문 텍스트·template 거부만 늘어난다.
            self.foreign_depth += 1
        elif tag == 'template' and self.foreign_depth:
            # svg·math 안의 template은 HTML template이 아니라 내용을 숨기지 않는다. 숨김 깊이를 셀 수 없어 받지 않는다.
            raise self.markup_error()

    def handle_data(self, data):
        if self.cdata_elem == 'script' and ends_double_escaped(data):
            raise self.markup_error()
        if self.cdata_elem and self.foreign_depth and '<' in data:
            # 브라우저는 svg·math 안의 이 내용을 태그·주석으로 읽는다. 글자만 있을 때는 두 해석이 같다.
            raise self.markup_error()
