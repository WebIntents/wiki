# encoding=utf-8

import logging
import os
import sys
import wsgiref.handlers

from google.appengine.dist import use_library
use_library('django', '1.2')

from google.appengine.ext import webapp
from google.appengine.ext.webapp import template

import handlers

if __name__ == '__main__':
    debug = os.environ['SERVER_SOFTWARE'].startswith('Development/')
    if debug:
        logging.getLogger().setLevel(logging.DEBUG)

    sys.path.insert(0, os.path.dirname(__file__))
    template.register_template_library('templatetags.filters')

    wsgiref.handlers.CGIHandler().run(webapp.WSGIApplication(handlers.handlers, debug=debug))
