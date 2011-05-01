# encoding=utf-8

import unittest

from google.appengine.ext import testbed

import access
import model
import settings
import util


class TestCase(unittest.TestCase):
    """Base class for all tests, initializes the datastore testbed (in-memory
    storage)."""
    def setUp(self):
        self.testbed = testbed.Testbed()
        self.testbed.activate()
        self.testbed.init_datastore_v3_stub()

    def tearDown(self):
        self.testbed.deactivate()

    def test_page_packing(self):
        """Tests whether page haders can be built correctly."""
        header = util.pack_page_header({
            'simple': 'foo',
            'list': ['foo', 'bar'],
            'text': 'must be ignored',
        })
        self.assertEquals('list: foo, bar\nsimple: foo', header)

    def test_page_parser(self):
        """Makes sure we can parse pages correctly."""
        args = util.parse_page('key: value\nkeys: one, two\n#ignore: me\n---\nhello, world.')
        self.assertEquals(3, len(args))
        self.assertEquals(args.get('key'), 'value')
        self.assertEquals(args.get('keys'), ['one', 'two'])
        self.assertEquals(args.get('text'), 'hello, world.')

    def test_page_url(self):
        """Makes sure we can build correct page URLs."""
        self.assertEquals('/foo', util.pageurl('foo'))
        self.assertEquals('/foo_bar', util.pageurl('foo bar'))
        self.assertEquals('/foo%2C_bar%21', util.pageurl('foo, bar!'))
        self.assertEquals('/%D0%BF%D1%80%D0%BE%D0%B2%D0%B5%D1%80%D0%BA%D0%B0', util.pageurl(u'проверка'))

    def test_wikify(self):
        checks = [
            ('foo bar', 'foo bar'),
            # Basic linking.
            ('[[foo bar]]', '<a class="int" href="/foo_bar">foo bar</a>'),
            ('[[foo|bar]]', '<a class="int" href="/foo">bar</a>'),
            # Interwiki linking.
            ('[[google:hello]]', u'<a class="iw iw-google" href="http://www.google.ru/search?q=hello" target="_blank">hello</a>'),
            ('[[missing:hello]]', '<a class="int" href="/missing%3Ahello">hello</a>'),
            # Check the typography features.
            ('foo. bar', 'foo. bar'),
            ('foo.  bar', 'foo.&nbsp; bar'),
            (u'foo  —  bar', u'foo&nbsp;— bar'),
            (u'foo  --  bar', u'foo&nbsp;— bar'),
        ]
        for got, wanted in checks:
            self.assertEquals(util.wikify(got), wanted)

    def test_page_creation(self):
        self.assertEquals(len(model.WikiContent.get_all()), 0)
        model.WikiContent(title='foo').put()
        self.assertEquals(len(model.WikiContent.get_all()), 1)

    def test_labelled_page_creation(self):
        self.assertEquals(len(model.WikiContent.get_all()), 0)

        page = model.WikiContent(title='foo')
        page.put()

        self.assertEquals(len(model.WikiContent.get_all()), 1)
        self.assertEquals(len(model.WikiContent.get_by_label('foo')), 0)

        page.body = 'labels: foo, bar\n---\n# foo'
        page.put()

        self.assertEquals(len(model.WikiContent.get_all()), 1)
        self.assertEquals(len(model.WikiContent.get_by_label('foo')), 1)

    def test_page_listing(self):
        self.assertEquals(util.wikify('[[List:foo]]'), '')
        model.WikiContent(title='bar', body='labels: foo\n---\n# bar\n\nHello, world.').put()
        model.WikiContent(title='baz', body='labels: foo\n---\n# baz\n\nHello, world.').put()
        self.assertEquals(util.wikify('[[List:foo]]'), u'- <a class="int" href="/bar">bar</a>\n- <a class="int" href="/baz">baz</a>')

    def test_settings_changing(self):
        self.assertEquals(None, settings.get('no-such-value'))
        settings.change({ 'no-such-value': 'yes' })
        self.assertEquals('yes', settings.get('no-such-value'))

    def test_white_listing(self):
        self.assertEquals(False, access.is_page_whitelisted('Welcome'))


def run_tests():
    suite = unittest.TestSuite()
    for method in dir(TestCase):
        if method.startswith('test_'):
            suite.addTest(TestCase(method))
    unittest.TextTestRunner().run(suite)


if __name__ == '__main__':
    run_tests()
