# vim: set ts=4 sts=4 sw=4 et fileencoding=utf-8:

# Python imports.
import urllib
import logging

# GAE imports.
from google.appengine.ext import webapp

register = webapp.template.create_template_register()

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
    if type(value) == unicode:
        value = value.encode('utf-8')
    elif type(value) != str:
        value = str(value)
    return '/' + urllib.quote(value.replace(' ', '_'))

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
