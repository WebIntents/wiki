# encoding=utf-8

import logging
import os
import traceback
import urllib

from django.utils import simplejson
from google.appengine.api import users
from google.appengine.ext import webapp

import access
import model
import settings
import util
import view


class NotFound(Exception):
    pass


class Forbidden(Exception):
    pass


class BadRequest(Exception):
    pass


class RequestHandler(webapp.RequestHandler):
    def reply(self, content, content_type='text/plain', status=200, save_as=None):
        self.response.headers['Content-Type'] = content_type + '; charset=utf-8'
        if save_as:
            self.response.headers['Content-Disposition'] = 'attachment; filename="%s"' % save_as
        self.response.out.write(content)

    def dump_request(self):
        for k in self.request.arguments():
            logging.debug('%s = %s' % (k, self.request.get(k)))

    def check_open_wiki(self):
        if not access.can_see_most_pages(users.get_current_user(), users.is_current_user_admin()):
            raise Forbidden

    def show_error_page(self, status_code):
        defaults = {
            400: 'Bad request.',
            403: 'Access denied, try logging in.',
            500: 'Something bad happened.',
        }
        page = model.WikiContent.get_error_page(status_code, defaults.get(status_code))
        self.reply(view.view_page(page, user=users.get_current_user(), is_admin=users.is_current_user_admin()), 'text/html')

    def handle_exception(self, e, debug_mode):
        if type(e) == BadRequest:
            self.show_error_page(400)
        elif type(e) == Forbidden:
            self.show_error_page(403)
        elif type(e) == NotFound:
            self.show_error_page(404)
        elif debug_mode:
            return webapp.RequestHandler.handle_exception(self, e, debug_mode)
        else:
            logging.error(e)
            logging.error(traceback.format_exc(e))
            self.show_error_page(500)


class PageHandler(RequestHandler):
    def get(self, page_name):
        self.show_page(urllib.unquote(page_name).decode('utf-8'))

    def show_page(self, title):
        if title.startswith('w/'):
            raise Exception('No such page.')
        if not access.can_read_page(title, users.get_current_user(), users.is_current_user_admin()):
            raise Forbidden
        title = title.replace('_', ' ')
        page = model.WikiContent.get_by_title(title)
        self.reply(view.view_page(page, user=users.get_current_user(), is_admin=users.is_current_user_admin()), 'text/html')


class StartPageHandler(PageHandler):
    def get(self):
        self.show_page(settings.get_start_page_name())


class EditHandler(RequestHandler):
    def get(self):
        title = self.request.get('page')
        if not title:
            raise BadRequest
        page = model.WikiContent.get_by_title(title)
        user = users.get_current_user()
        is_admin = users.is_current_user_admin()
        if not access.can_edit_page(title, user, is_admin):
            raise Forbidden
        if not page.is_saved():
            page.load_template(user, is_admin)
        self.reply(view.edit_page(page), 'text/html')

    def post(self):
        title = urllib.unquote(str(self.request.get('name'))).decode('utf-8')
        user = users.get_current_user()
        if not access.can_edit_page(title, user, users.is_current_user_admin()):
            raise Forbidden
        page = model.WikiContent.get_by_title(title)
        page.update(body=self.request.get('body'), author=user, delete=self.request.get('delete'))
        self.redirect('/' + urllib.quote(page.title.encode('utf-8').replace(' ', '_')))


class IndexHandler(RequestHandler):
    def get(self):
        self.reply(view.list_pages(self.get_data()), 'text/html')

    def get_data(self):
        self.check_open_wiki()
        return model.WikiContent.get_all()


class IndexFeedHandler(IndexHandler):
    def get(self):
        self.reply(view.list_pages_feed(self.get_data()), 'application/atom+xml')

    def get_data(self):
        self.check_open_wiki()
        return model.WikiContent.get_recently_added()


class PagesFeedHandler(IndexFeedHandler):
    def get_data(self):
        self.check_open_wiki()
        return model.WikiContent.get_recent_by_label(self.request.get('label'))


class PageHistoryHandler(RequestHandler):
    def get(self):
        title = self.request.get('page')
        if not access.can_read_page(title, users.get_current_user(), users.is_current_user_admin()):
            raise Forbidden
        page = model.WikiContent.get_by_title(title)
        self.reply(view.show_page_history(title, page.get_history()), 'text/html')


class RobotsHandler(RequestHandler):
    def get(self):
        content = "Sitemap: %s/sitemap.xml\n" % util.get_base_url()
        content += "User-agent: *\n"
        content += "Disallow: /gae-wiki-static/\n"
        content += "Disallow: /w/\n"
        self.reply(content, 'text/plain')


class SitemapHandler(RequestHandler):
    def get(self):
        self.check_open_wiki()
        pages = model.WikiContent.get_publicly_readable()
        self.reply(view.get_sitemap(pages), 'text/xml')


class ChangesHandler(RequestHandler):
    def get(self):
        self.reply(view.get_change_list(model.WikiContent.get_changes()), 'text/html')


class ChangesFeedHandler(RequestHandler):
    def get(self):
        self.reply(view.get_change_feed(model.WikiContent.get_changes()), 'text/xml')


class BackLinksHandler(RequestHandler):
    def get(self):
        title = self.request.get('page')
        if not access.can_read_page(title, users.get_current_user(), users.is_current_user_admin()):
            raise Forbidden
        page = model.WikiContent.get_by_title(title)
        self.reply(view.get_backlinks(page, page.get_backlinks()), 'text/html')


class UsersHandler(RequestHandler):
    def get(self):
        if not users.is_current_user_admin():
            raise Forbidden
        # self.check_open_wiki()
        self.reply(view.get_users(model.WikiUser.get_all()), 'text/html')


class DataExportHandler(RequestHandler):
    def get(self):
        if not users.is_current_user_admin():
            raise Forbidden
        pages = dict([(p.title, {
            'author': p.author and p.author.wiki_user.email(),
            'updated': p.updated.strftime('%Y-%m-%d %H:%M:%S'),
            'body': p.body,
        }) for p in model.WikiContent.get_all()])
        self.reply(simplejson.dumps(pages), 'application/json', save_as='gae-wiki.json')


class DataImportHandler(RequestHandler):
    def get(self):
        if not users.is_current_user_admin():
            raise Forbidden
        self.reply(view.get_import_form(), 'text/html')

    def post(self):
        if not users.is_current_user_admin():
            raise Forbidden
        merge = self.request.get('merge') != ''

        loaded = simplejson.loads(self.request.get('file'))
        for title, content in loaded.items():
            page = model.WikiContent.get_by_title(title)
            page.update(content['body'], content['author'] and users.User(content['author']))


class InterwikiHandler(RequestHandler):
    def get(self):
        iw = settings.get_interwikis()
        self.reply(view.show_interwikis(iw), 'text/html')


class ProfileHandler(RequestHandler):
    """Implements personal profile pages."""
    def get(self):
        user = users.get_current_user()
        if user is None:
            raise Forbidden
        wiki_user = model.WikiUser.get_or_create(user)
        self.reply(view.show_profile(wiki_user), 'text/html')

    def post(self):
        user = users.get_current_user()
        if user is None:
            raise Forbidden
        wiki_user = model.WikiUser.get_or_create(user)
        wiki_user.nickname = self.request.get('nickname')
        wiki_user.public_email = self.request.get('email')
        wiki_user.put()
        self.redirect('/w/profile')


class GeotaggedPagesFeedHandler(IndexFeedHandler):
    """Returns data for the /w/pages/geotagged.rss feed.  Supports the 'label'
    argument."""
    def get_data(self):
        self.check_open_wiki()
        return model.WikiContent.find_geotagged(label=self.request.get('label', None))


class GeotaggedPagesJsonHandler(RequestHandler):
    def get(self):
        self.check_open_wiki()
        label = self.request.get('label', None)
        pages = model.WikiContent.find_geotagged(label=label)
        self.reply(view.show_pages_map_data(pages), 'text/javascript')


class PageMapHandler(RequestHandler):
    """Returns a page that displays a Google Map."""
    def get(self):
        self.reply(view.show_page_map(self.request.get('label', None)), 'text/html')


class MapHandler(RequestHandler):
    """Shows a page on the map and allows editors move the pointer."""
    def get(self):
        page_name = self.request.get('page')
        if not page_name:
            raise NotFound('Page not found.')

        page = model.WikiContent.get_by_title(page_name)
        if page is None:
            raise NotFound('Page not found.')

        self.reply(view.show_single_page_map(page), 'text/html')

    def post(self):
        """Processes requests to move the pointer.  Expects arguments
        'page_name' and 'll'."""
        page = model.WikiContent.get_by_title(self.request.get('page_name'))
        if page is None:
            raise NotFound('Page not found.')
        if access.can_edit_page(page.title, users.get_current_user(), users.is_current_user_admin()):
            geo = self.request.get('lat') + ',' + self.request.get('lng')
            page.set_property('geo', geo)
            page.put()
        response = [ l.strip() for l in page.get_property('geo').split(',') ]
        self.reply(simplejson.dumps(response), 'application/json')


handlers = [
    ('/', StartPageHandler),
    ('/robots\.txt$', RobotsHandler),
    ('/sitemap\.xml$', SitemapHandler),
    ('/w/backlinks$', BackLinksHandler),
    ('/w/changes$', ChangesHandler),
    ('/w/changes\.rss$', ChangesFeedHandler),
    ('/w/data/export$', DataExportHandler),
    ('/w/data/import$', DataImportHandler),
    ('/w/edit$', EditHandler),
    ('/w/history$', PageHistoryHandler),
    ('/w/index$', IndexHandler),
    ('/w/index\.rss$', IndexFeedHandler),
    ('/w/interwiki$', InterwikiHandler),
    ('/w/map', MapHandler),
    ('/w/pages\.rss', PagesFeedHandler),
    ('/w/pages/geotagged\.rss', GeotaggedPagesFeedHandler),
    ('/w/pages/geotagged\.js', GeotaggedPagesJsonHandler),
    ('/w/pages/map', PageMapHandler),
    ('/w/profile', ProfileHandler),
    ('/w/users$', UsersHandler),
    ('/(.+)$', PageHandler),
]
