# encoding=utf-8

import datetime
import logging

from google.appengine.api import users
from google.appengine.ext import db

import settings
import util


class WikiUser(db.Model):
    wiki_user = db.UserProperty()
    joined = db.DateTimeProperty(auto_now_add=True)
    wiki_user_picture = db.BlobProperty()
    user_feed = db.StringProperty()

    @classmethod
    def get_all(cls):
        return cls.all().order('wiki_user').fetch(1000)

    @classmethod
    def get_or_create(cls, user):
        if user is None:
            return None
        wiki_user = cls.gql('WHERE wiki_user = :1', user).get()
        if wiki_user is None:
            wiki_user = cls(wiki_user=user)
            wiki_user.put()
        return wiki_user


class WikiContent(db.Model):
    """Stores current versions of pages."""
    title = db.StringProperty(required=True)
    body = db.TextProperty(required=False)
    author = db.ReferenceProperty(WikiUser)
    updated = db.DateTimeProperty(auto_now_add=True)
    pread = db.BooleanProperty()
    # The name of the page that this one redirects to.
    redirect = db.StringProperty()
    # Labels used by this page.
    labels = db.StringListProperty()
    # Pages that this one links to.
    links = db.StringListProperty()

    def put(self):
        """Adds the gaewiki:parent: labels transparently."""
        labels = [l for l in self.labels if not l.startswith('gaewiki:parent:')]
        if '/' in self.title:
            parts = self.title.split('/')[:-1]
            while parts:
                label = 'gaewiki:parent:' + '/'.join(parts)
                labels.append(label)
                parts.pop()
                break # remove to add recursion
        self.labels = labels
        db.Model.put(self)

    def backup(self):
        """Archives the current page revision."""
        logging.debug(u'Backing up page "%s"' % self.title)
        archive = WikiRevision(title=self.title, revision_body=self.body, author=self.author, created=self.updated)
        archive.put()

    def update(self, body, author, delete):
        if self.title == 'gaewiki:settings':
            settings.flush()
        if self.is_saved():
            self.backup()
            if delete:
                logging.debug(u'Deleting page "%s"' % self.title)
                self.delete()
                return

        logging.debug(u'Updating page "%s"' % self.title)

        self.body = body
        self.author = WikiUser.get_or_create(author)
        self.updated = datetime.datetime.now()

        options = util.parse_page(self.body)
        self.redirect = options.get('redirect')
        self.pread = options.get('public') == 'yes' and options.get('private') != 'yes'
        self.labels = options.get('labels', [])

        # TODO: rename
        # TODO: cross-link

        self.put()

    def get_history(self):
        return WikiRevision.gql('WHERE title = :1 ORDER BY created DESC', self.title).fetch(100)

    def get_backlinks(self):
        return WikiContent.gql('WHERE links = :1', self.title).fetch(1000)

    def load_template(self, user, is_admin):
        template = '# PAGE_TITLE\n\n**PAGE_TITLE** is ...'
        template_names = ['gaewiki:anon page template']
        if user is not None:
            template_names.insert(0, 'gaewiki:user page template')
        if users.is_current_user_admin():
            template_names.insert(0, 'gaewiki:admin page template')
        for template_name in template_names:
            page = WikiContent.gql('WHERE title = :1', template_name).get()
            if page is not None:
                logging.debug('Loaded template from %s' % template_name)
                template = page.body.replace(template_name, 'PAGE_TITLE')
                break
        if user is not None:
            template = template.replace('USER_EMAIL', user.email())
        self.body = template.replace('PAGE_TITLE', self.title)

    @classmethod
    def get_by_title(cls, title):
        """Finds and loads the page by its title, creates a new one if nothing
        could be found."""
        page = cls.gql('WHERE title = :1', title).get()
        if page is None:
            page = cls(title=title)
        return page

    @classmethod
    def get_by_label(cls, label):
        """Returns a list of pages that have the specified label."""
        return cls.gql('WHERE labels = :1 ORDER BY title', label).fetch(100)

    @classmethod
    def get_publicly_readable(cls):
        if settings.get('open-reading') == 'yes':
            pages = cls.all()
        else:
            pages = cls.gql('WHERE pread = :1', True).fetch(1000)
        return sorted(pages, key=lambda p: p.title.lower())

    @classmethod
    def get_all(cls):
        return sorted(cls.all().order('title').fetch(1000), key=lambda p: p.title.lower())

    @classmethod
    def get_changes(cls):
        if settings.get('open-reading') == 'yes':
            pages = cls.all().order('-updated').fetch(20)
        else:
            pages = cls.gql('WHERE pread = :1 ORDER BY -updated', True).fetch(20)
        return pages


class WikiRevision(db.Model):
    """
    Stores older revisions of pages.
    """
    title = db.StringProperty()
    wiki_page = db.ReferenceProperty(WikiContent)
    revision_body = db.TextProperty(required=True)
    author = db.ReferenceProperty(WikiUser)
    created = db.DateTimeProperty(auto_now_add=True)
    pread = db.BooleanProperty()
