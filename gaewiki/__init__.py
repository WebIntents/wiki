# encoding=utf-8

import os
import sys
import wsgiref.handlers

from google.appengine.dist import use_library
use_library('django', '1.2')

from google.appengine.ext import webapp
from google.appengine.ext.webapp import template
from google.appengine.ext.webapp.util import run_wsgi_app

import handlers


application = webapp.WSGIApplication(handlers.handlers)


def main():
    run_wsgi_app(application)


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(__file__))
    template.register_template_library('templatetags.filters')

    main()
