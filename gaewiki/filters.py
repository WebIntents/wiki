# encoding=utf-8

import logging
import re
import urllib

from google.appengine.dist import use_library
use_library('django', '0.96')

from google.appengine.ext.webapp import template

from markdown import markdown as markdown_parser

import util


register = template.create_template_register()


@register.filter
def uurlencode(value):
    if type(value) == unicode:
        value = value.encode('utf-8')
    try:
        if type(value) != str:
            raise Exception('got \"%s\" instead of a string.' % value.__class__.__name__)
        return urllib.quote(value)
    except Exception, e:
        logging.error('Error in the uurlencode filter: %s' % e)
        return ''


@register.filter
def pageurl(value):
    return util.pageurl(value)


@register.filter
def labelurl(value):
    if type(value) == unicode:
        value = value.encode('utf-8')
    elif type(value) != str:
        value = str(value)
    return '/Label:' + urllib.quote(value.replace(' ', '_'))


@register.filter
def hostname(value):
    host = value.split('/')[2]
    if host.startswith('www.'):
        host = host[4:]
    return host


@register.filter
def nonestr(value):
    if value is None:
        return ''
    return value


@register.filter
def markdown(text):
    return markdown_parser(text)


@register.filter
def wikify(text):
    props = util.parse_page(text)
    return markdown_parser(props['text'])
