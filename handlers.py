# -*- coding: utf-8 -*-
#
# Copyright 2008 Google Inc. All Rights Reserved.
#
# Licensed under the GNU General Public License, Version 3.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.gnu.org/licenses/gpl.html
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

__author__ = 'justin.forest@gmail.com'

# Python imports.
import datetime
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
from django.utils import simplejson

# Site imports.
import filters
import markdown
import model

# Some hard-coded settings.
WIKI_WORD_PATTERN = re.compile('\[\[([^]|]+\|)?([^]]+)\]\]')
SETTINGS_PAGE_NAME = 'gaewiki:settings'


def pagesort(pages):
    return sorted(pages, cmp=lambda a, b: cmp(a.title.lower(), b.title.lower()))


def get_page_template(title):
    template = '# PAGE_TITLE\n\n**PAGE_TITLE** is ...'
    user = users.get_current_user()

    template_names = ['gaewiki:anon page template']
    if user is not None:
        template_names.insert(0, 'gaewiki:user page template')
    if users.is_current_user_admin():
        template_names.insert(0, 'gaewiki:admin page template')

    for template_name in template_names:
        page = model.WikiContent.gql('WHERE title = :1', template_name).get()
        if page is not None:
            logging.debug('Loaded template from %s' % template_name)
            template = page.body.replace(template_name, 'PAGE_TITLE')
            break

    if user is not None:
        template = template.replace('USER_EMAIL', user.email())

    return template.replace('PAGE_TITLE', title)


class HTTPException(Exception):
    code = 500

    def __init__(self, *args):
        self.title = self.__class__.__name__
        if args: self.title = args[0]

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
    # Cache control, can be overridden in subclasses.
    cache_page = False
    cache_data = True
    # Default template used by generate().
    template = 'base.html'
    # Default content type for generate().
    content_type = 'text/html'

    def __init__(self, *args, **kwargs):
        self.settings = self.__load_settings()
        return super(BaseRequestHandler, self).__init__(*args, **kwargs)

    def handle_exception(self, e, debug_mode):
        if not issubclass(e.__class__, HTTPException):
            return webapp.RequestHandler.handle_exception(self, e, debug_mode)

        if e.code == 401:
            self.redirect(users.create_login_url(self.request.url))
        else:
            self.error(e.code)
            template_values = {
                'settings': self.get_settings(),
                'code': e.code,
                'title': e.title,
                'message': e.message,
            }
            if e.code == 403:
                template_values['sidebar'] = None
                template_values['footer'] = None
            self.generate('error.html', template_values)

    def getStartPage(self):
        return filters.pageurl(self.get_setting('start_page', 'Welcome'))

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

        template_values['settings'] = self.get_settings()

        # We'll display the user name if available and the URL on all pages
        values = {
            'user': user,
            'log_in_out_url': log_in_out_url,
            'is_admin': users.is_current_user_admin(),
        }
        if 'sidebar' not in values:
            values['sidebar'] = self._get_sidebar()
        if 'footer' not in values:
            values['footer'] = self._get_footer()
        url = urlparse.urlparse(self.request.url)
        values['base'] = url[0] + '://' + url[1]
        values['settings_page'] = SETTINGS_PAGE_NAME
        values.update(template_values)

        # logging.debug('Rendering %s with %s' % (self.request.path, values))

        # Construct the path to the template
        directory = os.path.dirname(__file__)
        path = os.path.join(directory, 'templates', template_name)

        result = template.render(path, values)
        if ret:
            return result

        # Respond to the request by rendering the template
        self.response.out.write(result)

    def get_settings(self):
        return self.settings

    def get_setting(self, name, default=None):
        return name in self.settings and self.settings[name] or default

    def __load_settings(self):
        """
        Loads settings from the datastore, page specified in SETTINGS_PAGE_NAME.
        If the page does not exist, some reasonable defaults are applied and saved.
        """
        page = model.WikiContent.gql('WHERE title = :1', SETTINGS_PAGE_NAME).get()
        if page is None:
            page = model.WikiContent(title=SETTINGS_PAGE_NAME)
            page.body = u'\n'.join([
                "title: My Wiki",
                "start_page: Welcome",
                "admin_email: nobody@example.com",
                "sidebar: gaewiki:sidebar",
                "footer: gaewiki:footer",
                "open-reading: yes",
                "open-editing: no",
                "editors: user1@example.com, user2@example.com",
                "interwiki-google: http://www.google.ru/search?sourceid=chrome&ie=UTF-8&q=%s",
                "interwiki-wp: http://en.wikipedia.org/wiki/Special:Search?search=%s",
            ]) + '\n---\n# %s\n\nEdit me.' % SETTINGS_PAGE_NAME
            page.put()
        return self.parse_page_options(page.body)

    def can_read(self, page=None, options=None):
        """
        Checks whether current user can read a page.  He can if he's an admin, the
        wiki is open for reading or if his email address is in the list of readers.
        """
        if (page and page.pread) or (options and options['public_page']):
            logging.debug('Reading allowed: public page.')
            return True
        if users.is_current_user_admin():
            logging.debug('Reading allowed: user is admin.')
            return True
        if self.get_setting('open-reading') == 'yes':
            logging.debug('Reading allowed: open.')
            return True
        user = users.get_current_user()
        if user is None:
            logging.debug('Reading forbidden: not logged in.')
            return False
        if user.email() in self.get_setting('readers', []):
            logging.debug('Reading allowed: %s is a reader.' % user.email())
            return True
        logging.debug('Reading forbidden: by default.')
        return False

    def can_edit(self, page=None):
        """
        Checks whether current user can edit a page.  He can if he's an admin, the
        wiki is open for editing or if his email address is in the list of editors.
        """
        if users.is_current_user_admin():
            logging.debug('Editing allowed: user is admin.')
            return True
        if self.get_setting('open-editing') == 'yes' and not self.is_page_locked(page):
            logging.debug('Editing allowed: open.')
            return True
        user = users.get_current_user()
        if user is None:
            logging.debug('Editing forbidden: not logged in.')
            return False
        if user.email() in self.get_setting('editors', []):
            logging.debug('Editing allowed: %s is an editor.' % user.email())
            return True
        logging.debug('Editing forbidden: by default.')
        return False

    def parse_page_options(self, text):
        """
        Parses special fields in page header.  The header is separated by a
        line with 3 dashes.  It contains lines of the "key: value" form, which
        define page options.

        Returns a dictionary with such options.  Page text is available as
        option named "text".
        """
        test = unicode(text)
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
                            v = re.split(',\s*', v)
                        options[k] = v
        options['text'] = parts[-1]
        return options

    def is_page_locked(self, page):
        "Checks whether the page's locked property is set to yes."
        if type(page) == model.WikiContent:
            page = {'page_options':self.parse_page_options(page.body or '')}
        if type(page) != dict:
            logging.debug(type(page))
            return False
        if 'page_options' not in page:
            return False
        if 'locked' not in page['page_options']:
            return False
        return page['page_options']['locked'] == 'yes'

    def get(self, *args):
        """
        Adds transparent caching to GET request handlers.  Real work is done by
        the _real_get() method.  Uses the URL as the cache key.  Cache hits and
        misses are logged to the DEBUG facility.
        """
        if not hasattr(self, '_real_get'):
            logging.error('Class %s does not define the _real_get() method, sending 501.' % self.__class__.__name__)
            self.error(501)
        else:
            cache_key = 'page#' + self._get_cache_key()
            cached = memcache.get(cache_key)
            use_cache = True
            if not self.cache_page:
                use_cache = False
                logging.debug('Cache MIS for \"%s\": disabled by class %s' % (cache_key, self.__class__.__name__))
            if use_cache and type(cached) != tuple:
                use_cache = False
                logging.debug('Cache MIS for \"%s\"' % cache_key)
            if use_cache and users.is_current_user_admin() and 'nocache' in self.request.arguments():
                logging.debug('Cache IGN for \"%s\": requested by admin' % cache_key)
                use_cache = False
            if not use_cache:
                self._real_get(*args)
                cached = (self.response.headers, self.response.out, )
                memcache.set(cache_key, cached)
            else:
                logging.debug('Cache HIT for \"%s\"' % cache_key)
            self.response.headers = cached[0]
            self.response.out = cached[1]

    def _get_cache_key(self):
        return self.request.path

    def _real_get(self, *args):
        """
        Calls the _get_data() method, which must return a dictionary to be used
        with render().  The dictionary must contain only simple data, not
        objects or models, otherwise caching will break up.
        """
        if not hasattr(self, '_get_data'):
            logging.error('Class %s does not define the _get_data() method, sending 501.' % self.__class__.__name__)
            self.error(501)
        else:
            cache_key = 'data#' + self._get_cache_key()
            data = memcache.get(cache_key)
            use_cache = True
            if type(data) != dict:
                use_cache = False
                logging.debug('Cache MIS for "%s"' % cache_key)
            elif not self.cache_data:
                use_cache = False
                logging.debug('Cache IGN for "%s": disabled by class %s.' % (cache_key, self.__class__.__name__))
            if users.is_current_user_admin() and 'nocache' in self.request.arguments():
                use_cache = False
                logging.debug('Cache IGN for "%s": requested by admin.' % (cache_key))
            if not use_cache:
                data = self._get_data(*args)
                if type(data) != dict:
                    logging.warning('%s._get_data() returned something other than a dictionary (%s), not caching.' % (self.__class__.__name__, data.__class__.__name__))
                else:
                    memcache.set(cache_key, data)
            else:
                logging.debug('Cache HIT for "%s"' % cache_key)
                # logging.debug(data)
            self._check_access(data)
            self.generate(self.template, data)

    def _check_access(self, data):
        pass

    def _get_data(self, *args):
        """
        Default data provider for dummy classes that only have a static template.
        """
        return {}

    def _get_sidebar(self):
        page_name = self.get_setting('sidebar', 'gaewiki:sidebar')
        return self._get_page_contents(page_name, u'<a href="/"><img src="/static/logo-186.png" width="186" alt="logo" height="167"/></a>\n\nThis is a good place for a brief introduction to your wiki, a logo and such things.\n\n[Edit this text](/w/edit?page=%s)' % page_name)

    def _get_footer(self):
        page_name = self.get_setting('footer', 'gaewiki:footer')
        return self._get_page_contents(page_name, u'This wiki is built with [GAEWiki](http://gaewiki.googlecode.com/).')

    def _get_page_contents(self, page_title, default_body=None):
        page = model.WikiContent.gql('WHERE title = :1', page_title).get()
        if page is None and default_body is not None:
            page = model.WikiContent(title=page_title, body=(u'# %s\n\n' % page_title) + default_body)
            page.put()
        if page is not None:
            options = self.parse_page_options(page.body)
            text = self.wikify(options['text'], page_title)
            text = re.sub('<h1>.*</h1>\s*', '', text) # remove the header
            return text.strip()

    def _get_linked_page_names(self, text):
        """
        Returns names of pages that text links to.
        """
        names = []
        for ref, tit in WIKI_WORD_PATTERN.findall(text):
            if not ref:
                ref = tit
            else:
                ref = ref.strip('|')
            ref = ref.strip()
            if ref not in names:
                names.append(ref)
        return sorted(names)

    def _flush_cache(self, page_name):
        """
        Removes a page from both page and data cache.
        """
        page_url = filters.pageurl(page_name)
        logging.debug('Cache DEL data#' + page_url)
        memcache.delete('data#' + page_url)
        logging.debug('Cache DEL page#' + page_url)
        memcache.delete('page#' + page_url)

    def wikify(self, text, page_title=None):
        """
        Covnerts Markdown text into HTML.  Supports interwikis.
        """
        text, count = WIKI_WORD_PATTERN.subn(lambda x: self.__wikify_one(x, page_title), text)
        text = markdown.markdown(text, self.get_setting('markdown-extensions', [])).strip()
        text = re.sub(r'\.  ', '.&nbsp; ', text)
        text = re.sub(u' (—|--) ', u'&nbsp;— ', text)
        return text

    def __wikify_one(self, pat, real_page_title):
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
                    return self.list_pages_by_label(parts[1])
                if parts[0] == 'ListChildren':
                    return self.list_pages_by_label('gaewiki:parent:' + (parts[1] or real_page_title))
                iwlink = self.get_setting(u'interwiki-' + parts[0])
                if iwlink:
                    return '<a class="iw iw-%s" href="%s" target="_blank">%s</a>' % (parts[0], iwlink.replace('%s', urllib.quote(parts[1].encode('utf-8'))), page_title)

        return '<a class="int" href="%s">%s</a>' % (filters.pageurl(page_name), page_title)

    def list_pages_by_label(self, label):
        logging.debug('Inserting a list of pages labelled with "%s".' % label)
        pages = model.WikiContent.gql('WHERE labels = :1 ORDER BY title', label).fetch(100)
        text = u'\n'.join(['- <a class="int" href="%s">%s</a>' % (filters.pageurl(p.title), p.title) for p in pagesort(pages)])
        return text


class PageHandler(BaseRequestHandler):
    template = 'view.html'

    """
    Renders and displays the requested page.
    """
    def _get_data(self, page_name):
        return self._get_page(urllib.unquote(page_name).decode('utf-8').replace('_', ' '))

    def _check_access(self, data):
        can_read = self.get_setting('open-reading') == 'yes'
        if 'public' in data['page_options'] and data['page_options']['public'] == 'yes':
            logging.debug('Reading allowed: wiki settings.')
            can_read = True
        if 'private' in data['page_options'] and data['page_options']['private'] == 'yes':
            logging.debug('Reading allowed: page settings.')
            can_read = False
        if can_read:
            return
        user = users.get_current_user()
        if user is None:
            logging.debug('Reading disallowed: not logged in.')
            raise ForbiddenException(u'You must be logged in to view this page.')
        if user.email() in self.get_setting('readers', []):
            logging.debug('Reading allowed: user is a reader.')
            return
        if user.email() in self.get_setting('editors', []):
            logging.debug('Reading allowed: user is an editor.')
            return
        if users.is_current_user_admin():
            logging.debug('Reading allowed: user is an admin.')
            return
        raise ForbiddenException(u'Reading disallowed: no access.')

    def _get_page(self, title, loop=10):
        """
        Returns information about the page as a dictionary with keys:
        page_title, page_exists, page_options, page_text.  If the page was
        redirected, the original name is available as page_source.
        """
        result = {
            'page_title': title,
            'page_exists': True,
            'page_revision': self.request.get('r'),
            'page_options': {},
            'public_page': self.get_setting('open-reading') == 'yes',
        }

        text, author, updated = self.__get_page_text(title)

        if text is None:
            result['page_exists'] = None

        else:
            options = self.parse_page_options(text)
            result['page_options'] = options
            result['page_text'] = self.wikify(options['text'], title)
            result['page_updated'] = updated

            if author:
                result['page_author'] = author.wiki_user.nickname()
                result['page_author_email'] = author.wiki_user.email()

            if result['public_page'] and 'private' in options and options['private'] == 'yes':
                result['public_page'] = False
            elif not result['public_page'] and 'public' in options and options['public'] == 'yes':
                result['public_page'] = True

        result['can_edit'] = self.can_edit(result)
        return result

    def __get_page_text(self, page_title, loop=10):
        """Returns page text.
        
        Supports the `r` GET parameter, which is treated as the exact revision
        id.  Supports redirects, if there's no `noredir` GET parameter.
        """
        logging.debug(self.request.path)
        if self.request.get('r'):
            rev = model.get_by_key(self.request.get('r'))
            return (rev.revision_body, rev.author, rev.created)

        else:
            page = model.WikiContent.gql('WHERE title = :1', page_title).get()
            if page is None:
                return (None, None, None)

            if not self.request.get('noredir'):
                options = self.parse_page_options(page.body)
                while 'redirect' in options and options['redirect'] and loop > 0:
                    next_page = model.WikiContent.gql('WHERE title = :1', options['redirect']).get()
                    if next_page is None:
                        logging.debug('Broken redirect from %s' % title)
                        break
                    page = next_page
                    options = self.parse_page_options(page.body)
                    loop -= 1

            return (page.body, page.author, page.updated)

    def _get_cache_key(self):
        key = self.request.path
        rev = self.request.get('r')
        if rev:
            key += '#' + rev
        return key


class StartPageHandler(PageHandler):
    """
    Shows the main page (named in the settings).
    """
    def get(self):
        return PageHandler.get(self, urllib.quote(self.get_setting('start_page', 'Welcome').encode('utf-8')))

    def _get_cache_key(self):
        return '/' + urllib.quote(self.get_setting('start_page', 'Welcome').encode('utf-8'))


class HistoryHandler(BaseRequestHandler):
    """
    Lists revisions of a page.
    """
    def get(self):
        page_title = self.request.get('page')
        self._check_access(page_title)
        history = model.WikiRevision.gql('WHERE title = :1 ORDER BY created DESC', page_title).fetch(100)
        self.generate('history.html', { 'page_title': page_title, 'revisions': history })

    def _check_access(self, page_name):
        allowed = None
        page = model.WikiContent.gql('WHERE title = :1', page_name).get()
        if not self.can_read(page):
            raise ForbiddenException(u'You are not allowed to view this page\'s history.')


class EditHandler(BaseRequestHandler):
    """
    Shows the page editor.
    """
    def get(self):
        page = self._load_page(self.request.get('page', 'Some Page'))
        if not page.is_saved():
            page.body = get_page_template(page.title)
        self.generate('edit.html', {
            'page': page,
        })

    def post(self):
        page = self._load_page(urllib.unquote(str(self.request.get('name'))).decode('utf-8'))
        old_title = page.title
        old_labels = page.labels

        # Save in the archive.
        if page.is_saved():
            backup = model.WikiRevision(title=page.title, revision_body=page.body, author=page.author, created=page.updated)
        else:
            backup = None

        if self.request.get('delete'):
            if page.is_saved():
                page.delete()
                if backup:
                    backup.put()
        else:
            page.body = self.request.get('body')
            page.author = self.get_wiki_user(create=True)
            page.links = self._get_linked_page_names(page.body)
            page.updated = datetime.datetime.now()
            logging.debug('%s links to: %s' % (page.title, page.links))

            options = self.parse_page_options(page.body)
            if 'redirect' in options:
                page.redirect = options['redirect']
            else:
                page.redirect = None
            if 'public' in options and options['public'] == 'yes':
                page.pread = True
            elif 'private' in options and options['private'] == 'yes':
                page.pread = False
            if 'labels' in options:
                page.labels = options['labels']
            else:
                page.labels = []
            # We only need the header, so we don't use extensions here.
            r = re.search('<h1>(.*)</h1>', markdown.markdown(options['text']))
            if r:
                page.title = r.group(1).strip()

            if backup and backup.revision_body != page.body:
                backup.put()
            page.put()

        self._flush_cache(page.title)
        self._flush_cache(old_title)

        # Flush labels cache
        for label in list(set(old_labels + page.labels)):
            self._flush_cache(u'Label:' + label)

        self.redirect(filters.pageurl(page.title))

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
        message = None
        allowed = self.can_edit(page)
        if page.title == SETTINGS_PAGE_NAME:
            allowed = users.is_current_user_admin()

        if not users.is_current_user_admin():
            whitelist = self.get_setting('page-whitelist')
            if whitelist:
                if re.search(whitelist, page.title) is None:
                    logging.debug(u'Page "%s" is not whitelisted: %s' % (page.title, whitelist))
                    allowed = False

            blacklist = self.get_setting('page-blacklist')
            if blacklist:
                if re.search(blacklist, page.title) is not None:
                    logging.debug(u'Page "%s" is blacklisted: %s' % (page.title, blacklist))
                    allowed = False

        if '/' in page.title and not page.is_saved() and not users.is_current_user_admin():
            if self.get_setting('parents-must-exist') == 'yes':
                parent_title = '/'.join(page.title.split('/')[:-1])
                parent = model.WikiContent.gql('WHERE title = :1', parent_title).get()
                if parent is None:
                    logging.debug(u'Page %s has not parent.' % page.title)
                    allowed = False
                    message = u'You are not allowed to create this page because the parent page (%s) does not exist.' % parent_title

        if not allowed:
            if users.get_current_user() is None:
                message = message or u'You are not allowed to edit this page. Try logging in.'
            else:
                message = message or u'You are not allowed to edit this page.'
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
        if not self.can_read():
            raise ForbiddenException(u'You are not allowed to see this page.')
        self.generate('index.html', {
            'pages': pagesort(model.WikiContent.all().order('title').fetch(1000)),
        })


class IndexFeedHandler(BaseRequestHandler):
    def get(self):
        if not self.can_read():
            raise ForbiddenException('You are not allowed to see this page.')
        self.generate('index.rss', {
            'pages': model.WikiContent.all().order('-updated').fetch(100)
        })


class ChangesHandler(BaseRequestHandler):
    def get(self):
        if not self.can_read():
            raise ForbiddenException('You are not allowed to see this page.')
        self.generate('changes.html', {
            'pages': model.WikiContent.gql('ORDER BY updated DESC').fetch(20),
        })


class ChangesFeedHandler(BaseRequestHandler):
    def get(self):
        if not self.can_read():
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

        show_all = self.get_setting('open-reading') == 'yes'
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


class BackLinksHandler(BaseRequestHandler):
    def get(self):
        page_title = self.request.get('page')
        page = model.WikiContent.gql('WHERE title = :1', page_title).get()
        if page is None:
            raise NotFoundException(u'No such page.')
        if not self.can_read(page):
            raise ForbiddenException(u'You are not allowed to view this page.')
        links = model.WikiContent.gql('WHERE links = :1', page_title).fetch(100)
        self.generate('backlinks.html', {
            'page_title': page_title,
            'page_links': [p.title for p in pagesort(links)],
        })


class DataExportHandler(BaseRequestHandler):
    def get(self):
        if not users.is_current_user_admin():
            raise ForbiddenException(u'Only admins can access this page.')
        data = {}
        for page in model.WikiContent.all().fetch(1000):
            data[page.title] = {
                'author': page.author and page.author.wiki_user.email() or None,
                'updated': page.updated.strftime('%Y-%m-%d %H:%M:%S'),
                'body': page.body,
            }

        json = simplejson.dumps(data, indent=False)
        self.response.headers['Content-Type'] = 'application/json; charset=utf-8'
        self.response.headers['Content-Disposition'] = 'attachment; filename="gaewiki-backup.json"'
        self.response.out.write(json)


class DataImportHandler(BaseRequestHandler):
    template = 'import.html'

    def _get_data(self):
        if not users.is_current_user_admin():
            raise ForbiddenException(u'Only admins can use this page.')
        return {}

    def post(self):
        if not users.is_current_user_admin():
            raise ForbiddenException(u'Only admins can use this page.')
        data = simplejson.loads(self.request.get('file'))
        if type(data) != dict:
            raise Exception('Bad data.')
        merge = self.request.get('merge') != ''
        authors = {}
        for title in data.keys():
            current = model.WikiContent.gql('WHERE title = :1', title).get()
            if current is None:
                # New page.
                current = model.WikiContent(title=title)
            elif merge:
                # We have such page but we're asked to not overwrite it.
                continue

            logging.info(u'Importing page "%s".' % title)
            page = data[title]

            author = None
            if 'author' in page:
                if page['author'] in authors:
                    author = authors[page['author']]
                else:
                    author = model.WikiUser.gql('WHERE wiki_user = :1', users.User(page['author'])).get()
                    if author is None:
                        author = model.WikiUser(wiki_user=users.User(page['author']))
                        author.put()
                    authors[page['author']] = author

            current.body = page['body']
            current.updated = datetime.datetime.strptime(page['updated'], '%Y-%m-%d %H:%M:%S')
            current.author = author

            options = self.parse_page_options(page['body'])
            if 'redirect' in options:
                current.redirect = options['redirect']
            if 'labels' in options:
                current.labels = options['labels']
            current.links = self._get_linked_page_names(page['body'])

            current.put()
        self.redirect('/w/index')


def main():
    debug = os.environ.get('SERVER_SOFTWARE').startswith('Development/')
    if debug:
        logging.getLogger().setLevel(logging.DEBUG)
    webapp.template.register_template_library('filters')
    wsgiref.handlers.CGIHandler().run(webapp.WSGIApplication([
      ('/', StartPageHandler),
      ('/w/backlinks$', BackLinksHandler),
      ('/w/changes$', ChangesHandler),
      ('/w/changes\.rss$', ChangesFeedHandler),
      ('/w/data/export$', DataExportHandler),
      ('/w/data/import$', DataImportHandler),
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
