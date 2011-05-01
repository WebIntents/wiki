# encoding=utf-8

import unittest

from google.appengine.ext import testbed

import access
import settings
import util


class TestCase(unittest.TestCase):
    def setUp(self):
        self.testbed = testbed.Testbed()
        self.testbed.activate()
        self.testbed.init_datastore_v3_stub()

    def tearDown(self):
        self.testbed.deactivate()


class PackPageHeader(TestCase):
    """Tests whether page haders can be built correctly."""
    def runTest(self):
        header = util.pack_page_header({
            'simple': 'foo',
            'list': ['foo', 'bar'],
            'text': 'must be ignored',
        })
        self.assertEquals('list: foo, bar\nsimple: foo', header)


class SettingsChange(TestCase):
    """Makes sure that the settings can be changed, since many other tests rely
    on that."""
    def runTest(self):
        self.assertEquals(None, settings.get('no-such-value'))
        settings.change({ 'no-such-value': 'yes' })
        self.assertEquals('yes', settings.get('no-such-value'))


class WhiteListedPage(TestCase):
    def runTest(self):
        self.assertEquals(False, access.is_page_whitelisted('Welcome'))


def run_tests():
    suite = unittest.TestSuite()
    suite.addTest(PackPageHeader())
    suite.addTest(SettingsChange())
    suite.addTest(WhiteListedPage())
    unittest.TextTestRunner().run(suite)


if __name__ == '__main__':
    run_tests()
