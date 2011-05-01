# encoding=utf-8

import unittest

import access

class WhiteListedPage(unittest.TestCase):
    def runTest(self):
        self.assertEquals(True, access.is_page_whitelisted('Welcome'))


def run_tests():
    suite = unittest.TestSuite()
    suite.addTest(WhiteListedPage())
    unittest.TextTestRunner().run(suite)


if __name__ == '__main__':
    run_tests()
