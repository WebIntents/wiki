# encoding=utf-8

import cgi
import logging
import re
import urllib

import markdown
import model
import settings


def parse_page(page_content):
    options = {}
    parts = re.split('[\r\n]+---[\r\n]+', page_content, 1)
    if len(parts) == 2:
        for line in re.split('[\r\n]+', parts[0]):
            if not line.startswith('#'):
                kv = line.split(':', 1)
                if len(kv) == 2:
                    k = kv[0].strip()
                    v = kv[1].strip()
                    if k.endswith('s'):
                        v = re.split(',\s*', v)
                    options[k] = v
    options['text'] = parts[-1]
    return options


def pageurl(title):
    if type(title) == unicode:
        title = title.encode('utf-8')
    elif type(title) != str:
        title = str(title)
    return '/' + urllib.quote(title.replace(' ', '_'))


def wikify_filter(text):
    props = parse_page(text)
    text = parse_markdown(props['text'])
    if 'display_title' in props:
        new = u'<h1>%s</h1>' % cgi.escape(props['display_title'])
        if not props['display_title'].strip():
            new = ''
        text = re.sub('<h1>(.+)</h1>', new, text)
    return wikify(text)


def parse_markdown(text):
    return markdown.markdown(text, settings.get('markdown-extensions', [])).strip()


WIKI_WORD_PATTERN = re.compile('\[\[([^]|]+\|)?([^]]+)\]\]')

def wikify(text, title=None):
    text, count = WIKI_WORD_PATTERN.subn(lambda x: wikify_one(x, title), text)
    text = re.sub(r'\.  ', '.&nbsp; ', text)
    text = re.sub(u' +(—|--) +', u'&nbsp;— ', text)
    return text

def wikify_one(pat, real_page_title):
    """
    Wikifies one link.
    """
    page_title = pat.group(2)
    if pat.group(1):
        page_name = pat.group(1).rstrip('|')
    else:
        page_name = page_title

    # interwiki
    if ':' in page_name:
        parts = page_name.split(':', 1)
        if ' ' not in parts[0]:
            if page_name == page_title:
                page_title = parts[1]
            if parts[0] == 'List':
                return list_pages_by_label(parts[1])
            if parts[0] == 'ListChildren':
                return list_pages_by_label('gaewiki:parent:' + (parts[1] or real_page_title))
            iwlink = settings.get(u'interwiki-' + parts[0])
            if iwlink:
                return '<a class="iw iw-%s" href="%s" target="_blank">%s</a>' % (parts[0], iwlink.replace('%s', urllib.quote(parts[1].encode('utf-8'))), page_title)

    return '<a class="int" href="%s">%s</a>' % (pageurl(page_name), page_title)


def list_pages_by_label(label):
    pages = model.WikiContent.get_by_label(label)
    text = u'\n'.join(['- <a class="int" href="%s">%s</a>' % (pageurl(p.title), p.title) for p in pages])
    return text


def pack_page_header(headers):
    """Builds a text page header from a dictionary."""
    lines = []
    for k, v in sorted(headers.items(), key=lambda x: x[0]):
        if k != 'text' and v is not None:
            if type(v) == list:
                v = u', '.join(v)
            lines.append(k + u': ' + v)
    return u'\n'.join(lines)


def uurlencode(value):
    if type(value) == unicode:
        value = value.encode('utf-8')
    try:
        if type(value) != str:
            raise Exception('got \"%s\" instead of a string.' % value.__class__.__name__)
        return urllib.quote(value)
    except Exception, e:
        return ''


def get_label_url(value):
    if type(value) == unicode:
        value = value.encode('utf-8')
    elif type(value) != str:
        value = str(value)
    return '/Label:' + urllib.quote(value.replace(' ', '_'))
