# -*- coding: utf-8 -*-
#
# Public domain.

__author__ = 'justin.forest@gmail.com'

# Python imports.
import logging
import os
import re
import urllib
import urlparse
import wsgiref.handlers
import xml.dom.minidom

# Google App Engine imports.
from google.appengine.api import images
from google.appengine.api import mail
from google.appengine.api import memcache
from google.appengine.api import users
from google.appengine.api import urlfetch
from google.appengine.api import xmpp
from google.appengine.ext import webapp
from google.appengine.ext.webapp import template

# Site imports.
from markdown.markdown import markdown
import model
import config
import filters


def parse_page_options(text):
    """
    Parses special fields in page header.  The header is separated by a line
    with 3 dashes.  It contains lines of the "key: value" form, which define
    page options.

    Returns a dictionary with such options.  Page text is available as option
    named "text".
    """
    if type(text) != unicode:
        raise TypeError('parse_page_options() expects Unicode text, not "%s".' % text.__class__.__name__)
    options = dict()
    text = text.replace('\r\n', '\n') # fix different EOL types
    parts = text.split(u'\n---\n', 1)
    if len(parts) > 1:
        for line in parts[0].split('\n'):
            if not line.startswith('#'):
                kv = line.split(':', 1)
                if len(kv) == 2:
                    k = kv[0].strip()
                    v = kv[1].strip()
                    if k.endswith('s'):
                        v = re.split('[\s,]+', v)
                    options[k] = v
    options['text'] = parts[-1]
    return options


def get_settings(key=None, default_value=''):
    """
    Loads settings from the datastore, page specified in config.py,
    SETTINGS_PAGE_NAME.  If the page does not exist, some reasonable defaults
    are applied and saved.
    """
    page = model.WikiContent.gql('WHERE title = :1', config.SETTINGS_PAGE_NAME).get()
    if page is None:
        page = model.WikiContent(title=config.SETTINGS_PAGE_NAME)
        page.body = u'\n'.join([
            "title: My Wiki",
            "start_page: Welcome",
            "admin_email: nobody@example.com",
            "sidebar: gaewiki:sidebar",
            "footer_page: gaewiki:footer",
            "open-reading: yes",
            "open-editing: no",
            "editors: user1@example.com, user2@example.com",
            "interwiki-google: http://www.google.ru/search?sourceid=chrome&ie=UTF-8&q=%s",
            "interwiki-wp: http://en.wikipedia.org/wiki/Special:Search?search=%s",
        ]) + '\n---\n# %s\n\nEdit me.' % config.SETTINGS_PAGE_NAME
        page.put()
    settings = parse_page_options(unicode(page.body))
    if key is None:
        return settings
    if settings.has_key(key):
        return settings[key]
    return default_value


def is_current_user_a_reader():
    if users.is_current_user_admin():
        logging.debug('Reading allowed: admin.')
        return True
    settings = get_settings()
    if settings.has_key('open-reading') and settings['open-reading'] == 'yes':
        logging.debug('Reading allowed: open-reading is set.')
        return True
    user = users.get_current_user()
    if user is None:
        logging.debug('Anoymous reading forbidden.')
        return False
    allowed = []
    if settings.has_key('readers'):
        allowed += settings['readers']
    if settings.has_key('editors'):
        allowed += settings['editors']
    if user.email() in allowed:
        logging.debug('Reading allowed for %s.' % user.email())
        return True
    logging.debug('Disallowing reading for %s.' % user.email())
    return False


def can_read(page=None):
    """
    Checks whether current user can read a page.  He can if he's an admin, the
    wiki is open for reading or if his email address is in the list of readers.
    """
    if page is not None and page.pread:
        logging.debug('Reading allowed: public page.')
        return True
    if users.is_current_user_admin():
        logging.debug('Reading allowed: user is admin.')
        return True
    settings = get_settings()
    if settings.has_key('open-reading') and settings['open-reading'] == 'yes':
        logging.debug('Reading allowed: open.')
        return True
    user = users.get_current_user()
    if user is None:
        logging.debug('Reading forbidden: not logged in.')
        return False
    if settings.has_key('readers'):
        if user.email() in settings['readers']:
            logging.debug('Reading allowed: %s is a reader.' % user.email())
            return True
    logging.debug('Reading forbidden: by default.')
    return False


def can_edit(page=None):
    """
    Checks whether current user can edit a page.  He can if he's an admin, the
    wiki is open for editing or if his email address is in the list of editors.
    """
    if users.is_current_user_admin():
        logging.debug('Editing allowed: user is admin.')
        return True
    settings = get_settings()
    if settings.has_key('open-editing') and settings['open-editing'] == 'yes':
        logging.debug('Editing allowed: open.')
        return True
    user = users.get_current_user()
    if user is None:
        logging.debug('Editing forbidden: not logged in.')
        return False
    if settings.has_key('editors'):
        if user.email() in settings['editors']:
            logging.debug('Editing allowed: %s is an editor.' % user.email())
            return True
    logging.debug('Editing forbidden: by default.')
    return False


def wikify(text):
    """
    Covnerts Markdown text into HTML.  Supports interwikis.
    """
    text, count = re.compile(config.WIKI_WORD_PATTERN).subn(_wikify_one, text)
    text = markdown(text).strip()
    return text


def _wikify_one(pat):
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
        parts = page_name.split(':', 2)
        if page_name == page_title:
            page_title = parts[1]
        iwlink = get_settings(u'interwiki-' + parts[0])
        if iwlink:
            return '<a class="iw iw-%s" href="%s" target="_blank">%s</a>' % (parts[0], iwlink.replace('%s', urllib.quote(parts[1].encode('utf-8'))), page_title)
        else:
            return '<a title="Unsupported interwiki was used (%s)." class="iw-broken">%s</a>' % (urllib.quote(parts[0]), page_title)

    return '<a class="int" href="%s">%s</a>' % (filters.pageurl(page_name), page_title)


class HTTPException(Exception):
    code = 500

    def __init__(self, *args):
        self.title = self.__class__.__name__
        if args:
            self.title = args[0]

class UnauthorizedException(HTTPException):
    code = 401

class ForbiddenException(HTTPException):
    code = 403

class NotFoundException(HTTPException):
    code = 404


class BaseRequestHandler(webapp.RequestHandler):
    """
    Base request handler extends webapp.Request handler

    It defines the generate method, which renders a Django template
    in response to a web request
    """

    def handle_exception(self, e, debug_mode):
        if not issubclass(e.__class__, HTTPException):
            return webapp.RequestHandler.handle_exception(self, e, debug_mode)

        if e.code == 401:
            self.redirect(users.create_login_url(self.request.url))
        else:
            self.error(e.code)
            self.generate('error.html', template_values={
                'settings': get_settings(),
                'code': e.code,
                'title': e.title,
                'message': e.message,
            })

    def getStartPage(self):
        return filters.pageurl(get_settings('start_page', 'Welcome'))

    def notifyUser(self, address, message):
        sent = False
        if xmpp.get_presence(address):
            status_code = xmpp.send_message(address, message)
            sent = (status_code != xmpp.NO_ERROR)

    def get_page_cache_key(self, page_name, revision_number=None):
        key = '/' + page_name
        if revision_number:
            key += '?r=' + str(revision_number)
        return key

    def get_page_name(self, page_title):
        if type(page_title) == type(str()):
            page_title = urllib.unquote(page_title).decode('utf8')
        return page_title.lower().replace(' ', '_')

    def get_current_user(self, back=None):
        if back is None:
            back = self.request.url
        current_user = users.get_current_user()
        if not current_user:
            raise UnauthorizedException()
        return current_user

    def get_wiki_user(self, create=False, back=None):
        current_user = self.get_current_user(back)
        wiki_user = model.WikiUser.gql('WHERE wiki_user = :1', current_user).get()
        if not wiki_user and create:
            wiki_user = model.WikiUser(wiki_user=current_user)
            wiki_user.put()
        return wiki_user

    def generateRss(self, template_name, template_values={}):
        template_values['self'] = self.request.url
        url = urlparse.urlparse(self.request.url)
        template_values['base'] = url[0] + '://' + url[1]
        self.response.headers['Content-Type'] = 'text/xml'
        return self.generate(template_name, template_values)

    def generate(self, template_name, template_values={}, ret=False):
        """
        Generate takes renders and HTML template along with values passed to
        that template

        template_name is a string that represents the name of the HTML
        template.  template_values is a dictionary that associates objects with
        a string assigned to that object to call in the HTML template.  The
        defualt is an empty dictionary.
        """
        # We check if there is a current user and generate a login or logout URL
        user = users.get_current_user()

        if user:
            log_in_out_url = users.create_logout_url(self.request.path)
        else:
            log_in_out_url = users.create_login_url(self.request.path)

        template_values['settings'] = get_settings()

        # We'll display the user name if available and the URL on all pages
        values = {
            'user': user,
            'log_in_out_url': log_in_out_url,
            'is_admin': users.is_current_user_admin(),
        }
        values['sidebar'] = self._get_sidebar()
        values['footer'] = self._get_footer()
        url = urlparse.urlparse(self.request.url)
        values['base'] = url[0] + '://' + url[1]
        values['settings_page'] = config.SETTINGS_PAGE_NAME
        values.update(template_values)

        logging.debug('Rendering %s with %s' % (self.request.path, values))

        # Construct the path to the template
        directory = os.path.dirname(__file__)
        path = os.path.join(directory, 'templates', template_name)

        result = template.render(path, values)
        if ret:
            return result

        # Respond to the request by rendering the template
        self.response.out.write(result)

    def _get_sidebar(self):
        page_name = get_settings('sidebar', 'gaewiki:sidebar')
        return self._get_page_contents(page_name, u'<a href="/"><img src="/static/logo.png" width="186" alt="logo" height="167"/></a>\n\nThis is a good place for a brief introduction to your wiki, a logo and such things.\n\n[Edit this text](/w/edit?page=%s)' % page_name)

    def _get_footer(self):
        page_name = get_settings('footer', 'gaewiki:footer')
        return self._get_page_contents(page_name, u'This wiki is built with [GAEWiki](http://gaewiki.googlecode.com/).')

    def _get_page_contents(self, page_title, default_body=None):
        page = model.WikiContent.gql('WHERE title = :1', page_title).get()
        if page is None and default_body is not None:
            page = model.WikiContent(title=page_title, body=(u'# %s\n\n' % page_title) + default_body)
            page.put()
        if page is not None:
            options = parse_page_options(unicode(page.body))
            text = wikify(options['text'])
            text = re.sub('<h1>.*</h1>\s*', '', text) # remove the header
            return text.strip()


class PageHandler(BaseRequestHandler):
    """
    Renders and displays the requested page.
    """
    def get(self, page_name):
        vars = self._get_page(urllib.unquote(page_name).decode('utf-8').replace('_', ' '))
        self.generate('view.html', vars)

    def _get_page(self, title, loop=10):
        """
        Returns information about the page as a dictionary with keys:
        page_title, page_exists, page_options, page_text.  If the page was
        redirected, the original name is available as page_source.
        """
        page = model.WikiContent.gql('WHERE title = :1', title).get()
        if page is None:
            page = model.WikiContent(title=title)
        result = {}
        while page.redirect and loop and not 'noredir' in self.request.arguments():
            if not result.has_key('page_source'):
                result['page_source'] = page.title
            logging.info('Redirecting from "%s" to "%s"' % (page.title, page.redirect))
            page = model.WikiContent.gql('WHERE title = :1', page.redirect).get() or model.WikiContent(title=page.redirect)
            loop -= 1

        if not can_read(page):
            raise ForbiddenException(u'You are not allowed to view this page.')

        result.update({
            'page_title': page.title,
            'page_exists': page.is_saved(),
            'page_options': {},
            'can_edit': can_edit(page),
            'public_page': get_settings('open-reading') == 'yes' or page.pread,
        })
        if page.author:
            result['page_author'] = page.author.wiki_user
        if page.updated:
            result['page_updated'] = page.updated
        if page.is_saved():
            result['page_key'] = str(page.key())
            result['page_options'] = parse_page_options(unicode(page.body))
        if result['page_options'].has_key('text'):
            result['page_text'] = wikify(result['page_options']['text'])
        return result


class StartPageHandler(PageHandler):
    """
    Shows the main page (named in the settings).
    """
    def get(self):
        vars = self._get_page(get_settings('start_page', 'Welcome'))
        self.generate('view.html', vars)


class HistoryHandler(BaseRequestHandler):
    """
    Lists revisions of a page.
    """
    def get(self):
        page_title = self.request.get('page').decode('utf-8')
        self._check_access(page_title)
        history = model.WikiRevision.gql('WHERE title = :1 ORDER BY version_number DESC', page_title).fetch(100)
        self.generate('history.html', { 'page_title': page_title, 'revisions': history })

    def _check_access(self, page_name):
        allowed = None
        page = model.WikiContent.gql('WHERE title = :1', page_name).get()
        if not can_read(page):
            raise ForbiddenException(u'You are not allowed to view this page\'s history.')


class EditHandler(BaseRequestHandler):
    """
    Shows the page editor.
    """
    def get(self):
        page = self._load_page(self.request.get('page', 'Some Page'))
        self.generate('edit.html', {
            'page': page,
        })

    def post(self):
        page = self._load_page(urllib.unquote(str(self.request.get('name'))).decode('utf-8'))

        # Save in the archive.
        if page.is_saved():
            model.WikiRevision(title=page.title, revision_body=page.body, author=page.author, created=page.updated).put()

        if self.request.get('delete'):
            if page.is_saved():
                page.delete()
        else:
            page.body = self.request.get('body')
            page.author = self.get_wiki_user()

            options = parse_page_options(unicode(page.body))
            if options.has_key('redirect'):
                page.redirect = options['redirect']
            if options.has_key('public') and options['public'] == 'yes':
                page.pread = True
            elif options.has_key('private') and options['private'] == 'yes':
                page.pread = False
            r = re.search('<h1>(.*)</h1>', markdown(options['text']))
            if r:
                page.title = r.group(1).strip()

            page.put()
        self.redirect('/' + urllib.quote(page.title.replace(' ', '_').encode('utf-8')))

    def _load_page(self, page_title):
        """
        Loads the page by name and checks whether the current user can edit it
        (if not, an exception is raised).
        """
        page = model.WikiContent.gql('WHERE title = :1', page_title).get() or model.WikiContent(title=page_title)
        self._check_access(page)
        return page

    def _check_access(self, page):
        """
        Raises an exception if the current user can't edit this page.
        """
        allowed = can_edit(page)
        if page.title == config.SETTINGS_PAGE_NAME:
            allowed = users.is_current_user_admin()
        if not allowed:
            if users.get_current_user() is None:
                message = u'You are not allowed to edit this page. Try logging in.'
            else:
                message = u'You are not allowed to edit this page.'
            raise ForbiddenException(message)


class UsersHandler(BaseRequestHandler):
    """
    Lists known users.
    """
    def get(self):
        users = model.WikiUser.all().order('wiki_user').fetch(1000)
        self.generate('users.html', { 'users': users })


class IndexHandler(BaseRequestHandler):
    """
    Shows the list of all pages.
    """
    def get(self):
        if not can_read():
            raise ForbiddenException(u'You are not allowed to see this page.')
        self.generate('index.html', {
            'pages': sorted(model.WikiContent.all().order('title').fetch(1000), cmp=lambda a, b: cmp(a.title.lower(), b.title.lower())),
        })


class IndexFeedHandler(BaseRequestHandler):
    def get(self):
        if not can_read():
            raise ForbiddenException('You are not allowed to see this page.')
        plist = {}
        for revision in model.WikiRevision.gql('ORDER BY created DESC').fetch(1000):
            page = revision.wiki_page.title
            if page not in plist:
                plist[page] = { 'name': page, 'title': self.get_page_name(page), 'created': revision.created, 'author': revision.author }
        self.generateRss('index.rss', template_values = {
            'items': [plist[page] for page in plist],
        });


class ChangesHandler(BaseRequestHandler):
    def get(self):
        if not can_read():
            raise ForbiddenException('You are not allowed to see this page.')
        self.generate('changes.html', {
            'pages': model.WikiContent.gql('ORDER BY updated DESC').fetch(20),
        })


class ChangesFeedHandler(BaseRequestHandler):
    def get(self):
        if not can_read():
            raise ForbiddenException('You are not allowed to see this page.')
        self.generateRss('changes.rss', {
            'pages': model.WikiContent.gql('ORDER BY updated DESC').fetch(20),
        })


class RobotsHandler(BaseRequestHandler):
  def get(self):
    content = "Sitemap: http://%s/sitemap.xml\n" % (self.request.environ['HTTP_HOST'])

    content += "User-agent: *\n"
    content += "Disallow: /static/\n"
    content += "Disallow: /w/\n"

    self.response.headers['Content-Type'] = 'text/plain'
    self.response.out.write(content)


class SitemapHandler(BaseRequestHandler):
    def get(self):
        content = "<?xml version=\"1.0\" encoding=\"utf-8\"?>\n"
        content += "<urlset xmlns=\"http://www.sitemaps.org/schemas/sitemap/0.9\">\n"

        show_all = get_settings('open-reading') == 'yes'
        host = self.request.environ['HTTP_HOST']

        for page in model.WikiContent.all().order('-updated').fetch(1000):
            if show_all or page.pread:
                line = "<url><loc>http://%s%s</loc>" % (host, filters.pageurl(page.title))
                if page.updated:
                    line += "<lastmod>%s</lastmod>" % (page.updated.strftime('%Y-%m-%d'))
                line += "</url>\n"
                content += line
        content += "</urlset>\n"

        self.response.headers['Content-Type'] = 'text/xml'
        self.response.out.write(content)


def main():
    debug = config.DEBUG or os.environ.get('SERVER_SOFTWARE').startswith('Development/')
    if debug:
        logging.getLogger().setLevel(logging.DEBUG)
    webapp.template.register_template_library('filters')
    wsgiref.handlers.CGIHandler().run(webapp.WSGIApplication([
      ('/', StartPageHandler),
      ('/w/changes$', ChangesHandler),
      ('/w/changes\.rss$', ChangesFeedHandler),
      ('/w/edit$', EditHandler),
      ('/w/history$', HistoryHandler),
      ('/w/index$', IndexHandler),
      ('/w/index\.rss$', IndexFeedHandler),
      ('/w/users$', UsersHandler),
      ('/robots\.txt$', RobotsHandler),
      ('/sitemap\.xml$', SitemapHandler),
      ('/(.+)', PageHandler)
    ], debug=debug))

if __name__ == '__main__':
    main()
