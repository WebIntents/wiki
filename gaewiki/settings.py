# encoding=utf-8

import model
import util

from google.appengine.api import memcache


SETTINGS_PAGE_NAME = 'gaewiki:settings'

DEFAULT_SETTINGS = """wiki_title: Web Intents 
start_page: Welcome
admin_email: paulkinlan@google.com 
sidebar: gaewiki:sidebar
footer: gaewiki:footer
open-reading: yes
open-editing: no
editors: gaba@google.com, gbillock@google.com, kormoroske@google.com, paul.kinlan@gmail.com, paulkinlan@google.com, scottrowe@google.com, scr@google.com,
markdown-extensions: def_list, fenced_code, toc, tables, codehilite
interwiki-google: http://www.google.ru/search?q=%s
interwiki-wp: http://en.wikipedia.org/wiki/Special:Search?search=%s
extra_styles: /gae-wiki-static/html.css, /gae-wiki-static/style.css
timezone: UTC
---
# gaewiki:settings

Edit me."""


def get_host_page():
    """Returns the page that hosts the settings."""
    page = model.WikiContent.gql('WHERE title = :1', SETTINGS_PAGE_NAME).get()
    if page is None:
        page = model.WikiContent(title=SETTINGS_PAGE_NAME, body=DEFAULT_SETTINGS)
        page.put()
    return page


def get_all():
    settings = memcache.get('gaewiki:settings')
    if settings is None:
        settings = util.parse_page(get_host_page().body)
        memcache.set('gaewiki:settings', settings)
    return settings


def get(key, default_value=None):
    return get_all().get(key, default_value)


def check_and_flush(page):
    """Empties settings cache if the host page is updated."""
    if page.title == SETTINGS_PAGE_NAME:
        memcache.delete('gaewiki:settings')


def change(upd):
    """Modifies current settings with the contents of the upd dictionary."""
    current = dict(get_all())
    current.update(upd)
    header = util.pack_page_header(current)
    page = get_host_page()
    page.body = header + u'\n---\n' + current['text']
    page.put()


def get_start_page_name():
    return get('start_page', 'Welcome')


def get_interwikis():
    iw = [(k[10:], v) for k, v in get_all().items() if k.startswith('interwiki-')]
    return sorted(iw, key=lambda iw: iw[0])
