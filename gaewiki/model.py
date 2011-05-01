# encoding=utf-8

from google.appengine.ext import db


class WikiUser(db.Model):
    wiki_user = db.UserProperty()
    joined = db.DateTimeProperty(auto_now_add=True)
    wiki_user_picture = db.BlobProperty()
    user_feed = db.StringProperty()


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
        "Adds the gaewiki:parent: labels transparently."
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


def get_by_key(key):
    """Loads an entity by its string key."""
    return db.get(db.Key(key))
