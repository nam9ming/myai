import unittest

from processing.collection.html_tokens import PinnedHTMLParser


class _Text(PinnedHTMLParser):
    def __init__(self):
        super().__init__()
        self.text = []

    def handle_data(self, data):
        super().handle_data(data)
        if self.cdata_elem is None:
            self.text.append(data)


def _read(html: str) -> str:
    parser = _Text()
    parser.feed(html)
    parser.close()
    return ''.join(parser.text)


class PinnedHTMLParserTest(unittest.TestCase):
    def test_reads_plain_markup_like_a_browser(self):
        self.assertEqual(_read('<!DOCTYPE html><p class="a"title="b">앞</p><!-- 메모 --><script>x</script>뒤'), '앞뒤')
        # `</ x>`는 무시되는 가짜 주석이고 원문 텍스트는 `</script`+구분자에서만 끝난다.
        self.assertEqual(_read('<p>앞</ p><script>a</scriptx>b</script>뒤'), '앞뒤')

    def test_rejects_forms_python_versions_or_browsers_read_differently(self):
        for html in ('<!--><p>x</p>-->', '<!-- a --!>', '<!-- 끝나지 않는 주석', '<![CDATA[x]]>', '<p></p title=">">',
                     '<!DOCTYPE html PUBLIC "x>', '<?x', '<p class="a"\xa0id="b">x</p>', '<plaintext>x',
                     '<script><!--<script></script>--></script>', '<svg><style><!--</style></svg>', '<svg><template>',
                     '<svg><foreignObject><style/></foreignObject></svg>', '<p'):
            with self.subTest(html=html), self.assertRaisesRegex(ValueError, '해석이 갈리는'):
                _read(html)

    def test_subclass_that_skips_super_cannot_silently_accept_tags(self):
        class Forgetful(PinnedHTMLParser):
            def handle_starttag(self, tag, attrs):
                pass

        with self.assertRaisesRegex(ValueError, '해석이 갈리는'):
            Forgetful().feed('<p>x</p>')


if __name__ == '__main__':
    unittest.main()
