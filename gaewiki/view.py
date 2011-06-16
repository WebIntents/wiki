# encoding=utf-8

import logging
import os

from google.appengine.dist import use_library
use_library('django', '0.96')

from google.appengine.api import users
from google.appengine.ext import webapp
from google.appengine.ext.webapp import template

import access
import model
import settings
import util


def render(template_name, data):
    filename = os.path.join(os.path.dirname(__file__), 'templates', template_name)
    if not os.path.exists(filename):
        raise Exception('Template %s not found.' % template_name)
    if 'user' not in data:
        data['user'] = model.WikiUser.get_or_create(users.get_current_user())
    if data['user']:
        data['log_out_url'] = users.create_logout_url(os.environ['PATH_INFO'])
    else:
        data['log_in_url'] = users.create_login_url(os.environ['PATH_INFO'])
    if 'is_admin' not in data:
        data['is_admin'] = users.is_current_user_admin()
    if 'sidebar' not in data:
        data['sidebar'] = get_sidebar()
    if 'footer' not in data:
        data['footer'] = get_footer()
    if 'settings' not in data:
        data['settings'] = settings.get_all()
    if 'base' not in data:
        data['base'] = util.get_base_url()
    return template.render(filename, data)


def get_sidebar():
    page_name = settings.get('sidebar', 'gaewiki:sidebar')
    page = model.WikiContent.get_by_title(page_name)
    if page.is_saved():
        body = page.body
    else:
        body = u'<a href="/"><img src="/gae-wiki-static/logo-186.png" width="186" alt="logo" height="167"/></a>\n\nThis is a good place for a brief introduction to your wiki, a logo and such things.\n\n[Edit this text](/w/edit?page=%s)' % page_name
    return body


def get_footer():
    page_name = settings.get('footer', 'gaewiki:footer')
    page = model.WikiContent.get_by_title(page_name)
    if page.is_saved():
        body = page.body
    else:
        body = u'This wiki is built with [GAEWiki](http://gaewiki.googlecode.com/).'
    return body


def view_page(page, user=None, is_admin=False):
    data = {
        'page': page,
        'is_admin': is_admin,
        'can_edit': access.can_edit_page(page.title, user, is_admin),
        'page_labels': page.get_property('labels', []),
    }

    logging.debug(u'Viewing page "%s"' % data['page'].title)
    return render('view_page.html', data)


def edit_page(page):
    logging.debug(u'Editing page "%s"' % page.title)
    return render('edit_page.html', {
        'page': page,
    })


def list_pages(pages):
    logging.debug(u'Listing %u pages.' % len(pages))
    return render('index.html', {
        'pages': pages,
    })


def list_pages_feed(pages):
    logging.debug(u'Listing %u pages.' % len(pages))
    return render('index.rss', {
        'pages': pages,
    })


def show_page_history(title, revisions):
    return render('history.html', {
        'page_title': title,
        'revisions': revisions,
    })


def get_sitemap(pages):
    return render('sitemap.xml', {
        'pages': pages,
    })


def get_change_list(pages):
    return render('changes.html', {
        'pages': pages,
    })


def get_change_feed(pages):
    return render('changes.rss', {
        'pages': pages,
    })


def get_backlinks(page, links):
    return render('backlinks.html', {
        'page_title': page.title,
        'page_links': links,
    })


def get_users(users):
    return render('users.html', {
        'users': users,
    })


def get_import_form():
    return render('import.html', { })


def show_interwikis(iw):
    return render('interwiki.html', {
        'interwiki': iw,
    })


def show_profile(wiki_user):
    return render('profile.html', {
        'user': wiki_user,
    })
