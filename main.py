#!/usr/bin/env python
# -*- coding: utf-8 -*-
# vim: set ts=2 sts=2 sw=2 et:
#
# Copyright 2008 Google Inc. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

__author__ = 'appengine-support@google.com'

"""Main application file for Wiki example.

Includes:
BaseRequestHandler - Base class to handle requests
MainHandler - Handles request to TLD
ViewHandler - Handles request to view any wiki entry
EditHandler - Handles request to edit any wiki entry
SaveHandler - Handles request to save any wiki entry
UserProfileHandler - Handles request to view any user profile
EditUserProfileHandler - Handles request to edit current user profile
GetUserPhotoHandler - Serves a users image
SendAdminEmail - Handles request to send the admins email
"""

__author__ = 'appengine-support@google.com'

# Python Imports
import os
import sys
import re
import urllib
import urlparse
import wsgiref.handlers
import xml.dom.minidom
import logging

# Google App Engine Imports
from google.appengine.api import images
from google.appengine.api import mail
from google.appengine.api import memcache
from google.appengine.api import users
from google.appengine.api import urlfetch
from google.appengine.ext import webapp
from google.appengine.ext.webapp import template

# Wiki Imports
from markdown import markdown
from wiki_model import WikiContent
from wiki_model import WikiRevision
from wiki_model import WikiUser

# Set the debug level
_DEBUG = True
_ADMIN_EMAIL='justin.forest@gmail.com'
_SETTINGS = {
  'title': 'gaewiki demo',
  'interwiki': {
    'google': 'http://www.google.ru/search?sourceid=chrome&ie=UTF-8&q=%s',
    'wp': 'http://en.wikipedia.org/wiki/Special:Search?search=%s',
    'wpru': 'http://ru.wikipedia.org/wiki/Special:Search?search=%s',
  },
  'welcome': 'welcome',
  'open': True,
}

# Regular expression for a wiki word.  Wiki words are all letters
# As well as camel case.  For example: WikiWord
_WIKI_WORD = re.compile('\[\[([^]|]+\|)?([^]]+)\]\]')

class BaseRequestHandler(webapp.RequestHandler):
  """Base request handler extends webapp.Request handler

     It defines the generate method, which renders a Django template
     in response to a web request
  """

  def getStartPage(self):
    return '/' + _SETTINGS['welcome']

  def getWikiContent(self, page_title):
    return WikiContent.gql('WHERE title = :1', self.get_page_name(page_title)).get()

  def getPageRevision(self, page_name, revision=None):
    page = self.getWikiContent(page_name)
    if revision:
      return WikiRevision.gql('WHERE wiki_page = :1 AND version_number = :2', page, int(revision)).get()
    return WikiRevision.gql('WHERE wiki_page = :1 ORDER BY version_number DESC', page).get()

  def get_page_name(self, page_title):
    if type(page_title) == type(str()):
      page_title = urllib.unquote(page_title).decode('utf8')
      logging.info('%s decoded' % page_title)
    return page_title.lower().replace(' ', '_')

  def checkUserAllowed(self, admin=False):
    if users.is_current_user_admin():
      return True
    elif _SETTINGS['open']:
      return True
    current_user = users.get_current_user()
    if not current_user:
      logging.info(self.redirect(users.create_login_url(self.request.url)))
    elif users.is_current_user_admin():
      return True
    else:
      self.error(403)
      self.generate('403.html')
    return False

  def get_current_user(self, back=None):
    if back is None:
      back = self.request.url
    current_user = users.get_current_user()
    if not current_user:
      logging.info(self.redirect(users.create_login_url(back)))
    logging.info(current_user)
    self.error(403)
    return current_user

  def get_wiki_user(self, create=False, back=None):
    current_user = self.get_current_user(back)
    wiki_user = WikiUser.gql('WHERE wiki_user = :1', current_user).get()
    if not wiki_user and create:
      wiki_user = WikiUser(wiki_user=current_user)
      wiki_user.put()
    return wiki_user

  def wikify(self, text):
    text, count = _WIKI_WORD.subn(self.wikify_one, text)
    text = markdown.markdown(text)
    return text

  def wikify_one(self, pat):
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
      logging.info(page_title)
      logging.info(parts)
      if parts[0] in _SETTINGS['interwiki']:
        return '<a class="iw iw-%s" href="%s" target="_blank">%s</a>' % (parts[0], _SETTINGS['interwiki'][parts[0]].replace('%s', urllib.quote(parts[1])), page_title)

    page_name = page_name.lower().replace(' ', '_')
    page = self.getWikiContent(page_name)
    if page:
      return '<a class="int" href="%s">%s</a>' % (page_name, page_title)
    else:
      return '<a class="int missing" href="%s?edit=1">%s</a>' % (page_name, page_title)

  def generateRss(self, template_name, template_values={}):
    template_values['self'] = self.request.url
    url = urlparse.urlparse(self.request.url)
    template_values['base'] = url[0] + '://' + url[1]
    self.response.headers['Content-Type'] = 'text/xml'
    return self.generate(template_name, template_values)

  def generate(self, template_name, template_values={}):
    """Generate takes renders and HTML template along with values
       passed to that template

       Args:
         template_name: A string that represents the name of the HTML template
         template_values: A dictionary that associates objects with a string
           assigned to that object to call in the HTML template.  The defualt
           is an empty dictionary.
    """
    # We check if there is a current user and generate a login or logout URL
    user = users.get_current_user()

    if user:
      log_in_out_url = users.create_logout_url(self.getStartPage())
    else:
      log_in_out_url = users.create_login_url(self.request.path)

    template_values['settings'] = _SETTINGS

    # We'll display the user name if available and the URL on all pages
    values = {'user': user, 'log_in_out_url': log_in_out_url, 'editing': self.request.get('edit'), 'is_admin': users.is_current_user_admin() }
    values.update(template_values)

    # Construct the path to the template
    directory = os.path.dirname(__file__)
    path = os.path.join(directory, 'templates', template_name)

    # Respond to the request by rendering the template
    self.response.out.write(template.render(path, values, debug=_DEBUG))

class MainHandler(BaseRequestHandler):
  """The MainHandler extends the base request handler, and handles all
     requests to the url http://wikiapp.appspot.com/
  """

  def get(self):
    """When we request the base page, we direct users to the StartPage
    """
    self.redirect(self.getStartPage())


class ViewRevisionListHandler(BaseRequestHandler):

    def get(self, page_title):
        entry = WikiContent.gql('WHERE title = :1', page_title).get()

        if entry:
            revisions = WikiRevision.all()
            # Render the template view_revisionlist.html, which extends base.html
            self.generate('view_revisionlist.html', template_values={'page_title': page_title,
                                                        'revisions': revisions,
                                                       })


class ViewDiffHandler(BaseRequestHandler):

    def get(self, page_title, first_revision, second_revision):
        entry = WikiContent.gql('WHERE title = :1', page_title).get()

        if entry:
            first_revision = WikiRevision.gql('WHERE wiki_page =  :1 '
                                              'AND version_number = :2', entry, int(first_revision)).get()
            second_revision = WikiRevision.gql('WHERE wiki_page =  :1 '
                                              'AND version_number = :2', entry, int(second_revision)).get()

            import diff
            body = diff.textDiff(first_revision.revision_body, second_revision.revision_body)

            self.generate('view_diff.html', template_values={'page_title': page_title,
                                                             'body': body,
                                                             })


class ViewHandler(BaseRequestHandler):
  """This class defines the request handler that handles all requests to the
     URL http://wikiapp.appspot.com/view/*
  """

  def get_page_content(self, page_title, revision_number=1):
    """When memcache lookup fails, we want to query the information from
       the datastore and return it.  If the data isn't in the data store,
       simply return empty strings
    """
    # Find the wiki entry
    entry = WikiContent.gql('WHERE title = :1', self.get_page_name(page_title)).get()

    if entry:
      # Retrieve the current version
      if revision_number is not None:
          requested_version = WikiRevision.gql('WHERE wiki_page =  :1 '
                                               'AND version_number = :2', entry, int(revision_number)).get()
      else:
          requested_version = WikiRevision.gql('WHERE wiki_page =  :1 '
                                               'ORDER BY version_number DESC', entry).get()
      # Define the body, version number, author email, author nickname
      # and revision date
      body = requested_version.revision_body
      version = requested_version.version_number
      author_email = urllib.quote(requested_version.author.wiki_user.email())
      author_nickname = requested_version.author.wiki_user.nickname()
      version_date = requested_version.created
      # Replace all wiki words with links to those wiki pages
      wiki_body = self.wikify(body)
    else:
      # These things do not exist
      wiki_body = ''
      author_email = ''
      author_nickname = ''
      version = ''
      version_date = ''

    return [wiki_body, author_email, author_nickname, version, version_date]

  def get_content(self, page_title, revision_number):
    """Checks memcache for the page.  If the page exists in memcache, it
       returns the information.  If not, it calls get_page_content, gets the
       page content from the datastore and sets the memcache with that info
    """
    page_content = self.get_page_content(page_title, revision_number)

    return page_content

  def post(self, page_title):
    wiki_user = self.get_wiki_user(True, '/' + page_title + '?edit=1')
    current_user = wiki_user.wiki_user
    logging.info(current_user)

    # get the user entered content in the form
    body = self.request.get('body')

    # Find the entry, if it exists
    entry = self.getWikiContent(page_title)

    # Generate the version number based on the entries previous existence
    if entry:
      latest_version = WikiRevision.gql('WHERE wiki_page = :content ORDER BY version_number DESC', content=entry).get()
      if latest_version:
        version_number = latest_version.version_number + 1
      else:
        version_number = 1
    else:
      version_number = 1
      entry = WikiContent(title=self.get_page_name(page_title))
      entry.put()

    # Create a version for this entry
    version = WikiRevision(version_number=version_number,
                           revision_body=body, author=wiki_user,
                           wiki_page=entry)
    version.put()

    # above, memcache sets the following:
    # return [wiki_body, author_email, author_nickname, version, version_date]
    content = [markdown.markdown(body), current_user.email(), 
               current_user.nickname(), version_number, version.created]
    memcache.set(page_title, content, 600)

    # After the entry has been saved, direct the user back to view the page
    self.redirect('/' + page_title)

  def get(self, page_name):
    if not self.checkUserAllowed():
      return
    if self.request.get("edit"):
      return self.get_edit(page_name)
    elif self.request.get("history"):
        return self.get_history(page_name)
    else:
      return self.get_view(page_name)

  def get_view(self, page_name):
    revision_number = None
    if self.request.get('r'):
      revision_number = int(self.request.get('r'))
    wiki_body, author_email, author_nickname, version, version_date = self.get_content(page_name, revision_number)

    self.generate('view.html', template_values={
      'page_name': page_name,
      'page_title': self.get_page_name(page_name),
      'body': wiki_body,
      'author': author_nickname,
      'author_email': author_email,
      'version': version,
      'version_date': version_date})

  def get_edit(self, page_name):
    self.get_current_user(self.request.url)
    logging.info(self.getPageRevision(page_name, self.request.get('r')))
    self.generate('edit.html', template_values={
      'page_name': page_name,
      'page_title': self.get_page_name(page_name),
      'current_version': self.getPageRevision(page_name, self.request.get('r')),
    })

  def get_history(self, page_name):
    page = self.getWikiContent(page_name)
    if not page:
      self.error(404)
    else:
      history = WikiRevision.gql('WHERE wiki_page = :1 ORDER BY version_number DESC', page).fetch(100)
      self.generate('history.html', template_values = { 'page_name': page_name, 'page_title': page.title, 'revisions': history })

class EditHandler(BaseRequestHandler):
  """When we receive an HTTP Get request to edit pages, we pull that
     page from the datastore and allow the user to edit.  If the page does 
     not exist we pass empty arguments to the template and the template 
     allows the user to create the page
  """
  def get(self, page_title):
    # We require that the user be signed in to edit a page
    current_user = users.get_current_user()

    if not current_user:
      self.redirect(users.create_login_url('/edit/' + page_title))

    # Get the entry along with the current version
    entry = WikiContent.gql('WHERE title = :1', page_title).get()

    current_version = WikiRevision.gql('WHERE wiki_page = :1 '
                                       'ORDER BY version_number DESC', entry).get()

    # Generate edit template, which posts to the save handler
    self.generate('edit.html',
                  template_values={'page_name': page_title,
                                   'page_title': urllib.unquote(page_title).decode('utf-8'),
                                   'current_version': current_version})


class SaveHandler(BaseRequestHandler):
  """From the edit page for a wiki article, we post to the SaveHandler
     This creates the the entry and revision for the datastore.  Also,
     we take the data posted, and set it in memcache.
  """

  def post(self, page_title):
    wiki_user = self.get_wiki_user(True, users.create_login_url('/edit/' + page_title))

    # get the user entered content in the form
    body = self.request.get('body')

    # Find the entry, if it exists
    entry = self.getWikiContent(page_title)

    # Generate the version number based on the entries previous existence
    if entry:
      latest_version = WikiRevision.gql('WHERE wiki_page = :content'
                                        ' ORDER BY version_number DESC', content=entry).get()
      version_number = latest_version.version_number + 1
    else:
      version_number = 1
      entry = WikiContent(title=self.get_page_name(page_title))
      entry.put()

    # Create a version for this entry
    version = WikiRevision(version_number=version_number,
                           revision_body=body, author=wiki_user,
                           wiki_page=entry)
    version.put()

    # above, memcache sets the following:
    # return [wiki_body, author_email, author_nickname, version, version_date]
    content = [markdown.markdown(body), current_user.email(), 
               current_user.nickname(), version_number, version.created]
    memcache.set(page_title, content, 600)
    # After the entry has been saved, direct the user back to view the page
    self.redirect('/' + page_title)


class UserProfileHandler(BaseRequestHandler):
  """Allows a user to view another user's profile.  All users are able to
     view this information by requesting http://wikiapp.appspot.com/user/*
  """

  def get(self, user):
    """When requesting the URL, we find out that user's WikiUser information.
       We also retrieve articles written by the user
    """
    # Webob over quotes the request URI, so we have to unquote twice
    unescaped_user = urllib.unquote(urllib.unquote(user))

    # Query for the user information
    wiki_user_object = users.User(unescaped_user)
    wiki_user = WikiUser.gql('WHERE wiki_user = :1', wiki_user_object).get()

    # Retrieve the unique set of articles the user has revised
    # Please note that this doesn't gaurentee that user's revision is
    # live on the wiki page
    article_list = []
    for article in wiki_user.wikirevision_set:
      article_list.append(article.wiki_page.title)
    articles = set(article_list)

    # If the user has specified a feed, fetch it
    feed_content = ''
    feed_titles = []
    if wiki_user.user_feed:
      feed = urlfetch.fetch(wiki_user.user_feed)
      # If the fetch is a success, get the blog article titles
      if feed.status_code == 200:
        feed_content = feed.content
        xml_content = xml.dom.minidom.parseString(feed_content)
        for title in xml_content.getElementsByTagName('title'):
          feed_titles.append(title.childNodes[0].nodeValue)
    # Generate the user profile
    self.generate('user.html', template_values={'queried_user': wiki_user,
                                                'articles': articles,
                                                'titles': feed_titles})

class EditUserProfileHandler(BaseRequestHandler):
  """This allows a user to edit his or her wiki profile.  The user can upload
     a picture and set a feed URL for personal data
  """
  def get(self, user):
    # Get the user information
    unescaped_user = urllib.unquote(user)
    wiki_user_object = users.User(unescaped_user)
    # Only that user can edit his or her profile
    if users.get_current_user() != wiki_user_object:
      self.redirect(self.getStartPage())

    wiki_user = WikiUser.gql('WHERE wiki_user = :1', wiki_user_object).get()
    if not wiki_user:
      wiki_user = WikiUser(wiki_user=wiki_user_object)
      wiki_user.put()

    article_list = []
    for article in wiki_user.wikirevision_set:
      article_list.append(article.wiki_page.title)
    articles = set(article_list)
    self.generate('edit_user.html', template_values={'queried_user': wiki_user,
                                                     'articles': articles})

  def post(self, user):
    # Get the user information
    unescaped_user = urllib.unquote(user)
    wiki_user_object = users.User(unescaped_user)
    # Only that user can edit his or her profile
    if users.get_current_user() != wiki_user_object:
      self.redirect(self.getStartPage())

    wiki_user = WikiUser.gql('WHERE wiki_user = :1', wiki_user_object).get()

    user_photo = self.request.get('user_picture')
    if user_photo:
      raw_photo = images.Image(user_photo)
      raw_photo.resize(width=256, height=256)
      raw_photo.im_feeling_lucky()
      wiki_user.wiki_user_picture = raw_photo.execute_transforms(output_encoding=images.PNG)
    feed_url = self.request.get('feed_url')
    if feed_url:
      wiki_user.user_feed = feed_url

    wiki_user.put()


    self.redirect('/user/%s' % user)


class GetUserPhotoHandler(BaseRequestHandler):
  """This is a class that handles serving the image for a user
     
     The template requests /getphoto/example@test.com and the handler
     retrieves the photo from the datastore, sents the content-type
     and returns the photo
  """

  def get(self, user):
    unescaped_user = urllib.unquote(user)
    wiki_user_object = users.User(unescaped_user)
    # Only that user can edit his or her profile
    if users.get_current_user() != wiki_user_object:
      self.redirect(self.getStartPage())

    wiki_user = WikiUser.gql('WHERE wiki_user = :1', wiki_user_object).get()
    
    if wiki_user.wiki_user_picture:
      self.response.headers['Content-Type'] = 'image/jpg'
      self.response.out.write(wiki_user.wiki_user_picture)


class SendAdminEmail(BaseRequestHandler):
  """Sends the admin email.

     The user must be signed in to send email to the admins
  """
  def get(self):
    # Check to see if the user is signed in
    current_user = users.get_current_user()

    if not current_user:
      self.redirect(users.create_login_url('/sendadminemail'))

    # Generate the email form
    self.generate('admin_email.html')

  def post(self):
    # Check to see if the user is signed in
    current_user = users.get_current_user()

    if not current_user:
      self.redirect(users.create_login_url('/sendadminemail'))

    # Get the email subject and body
    subject = self.request.get('subject')
    body = self.request.get('body')

    # send the email
    mail.send_mail_to_admins(sender=current_user.email(), reply_to=current_user.email(),
                             subject=subject, body=body)

    # Generate the confirmation template
    self.generate('confirm_email.html')

class UsersHandler(BaseRequestHandler):
  def get(self):
    self.checkUserAllowed(True)
    users = WikiUser.all().fetch(1000)
    self.generate('users.html', template_values = { 'users': users })

  def post(self):
    self.checkUserAllowed(True)
    email = self.request.get('email').strip()
    if email and not WikiUser.gql('WHERE wiki_user = :1', users.User(email)).get():
      user = WikiUser(wiki_user=users.User(email))
      user.put()
    self.redirect('/users')

class PageRssHandler(BaseRequestHandler):
  def get(self):
    # self.checkUserAllowed()
    pages = {}
    for revision in WikiRevision.gql('ORDER BY created DESC').fetch(1000):
      page = revision.wiki_page.title
      if page not in pages:
        pages[page] = { 'name': page, 'title': self.get_page_name(page), 'created': revision.created, 'author': revision.author }
    self.generateRss('index-rss.html', template_values = {
      'items': [pages[page] for page in pages],
    });

class IndexHandler(BaseRequestHandler):
  def get(self):
    self.checkUserAllowed()
    self.generate('index.html', template_values={'pages': [page.title for page in WikiContent.gql('ORDER BY title').fetch(1000)] })

class ChangesHandler(BaseRequestHandler):
  def get(self):
    self.checkUserAllowed()
    self.generate('changes.html', template_values={
      'self': self.request.url,
      'changes': [revision for revision in WikiRevision.gql('ORDER BY created DESC').fetch(1000)]})

class ChangesRssHandler(BaseRequestHandler):
  def get(self):
    # self.checkUserAllowed()
    self.generateRss('changes-rss.html', template_values={
      'changes': [revision for revision in WikiRevision.gql('ORDER BY created DESC').fetch(1000)],
    })

class InterwikiHandler(BaseRequestHandler):
  def get(self):
    self.checkUserAllowed()
    items = _SETTINGS['interwiki'].keys()
    items.sort()
    self.generate('interwiki.html', template_values={'iwlist': [{'key': item, 'host': urlparse.urlparse(_SETTINGS['interwiki'][item])[1], 'sample': _SETTINGS['interwiki'][item].replace('%s', 'hello%2C%20world')} for item in items]})

_WIKI_URLS = [('/', MainHandler),
              ('/w/changes', ChangesHandler),
              ('/w/changes.rss', ChangesRssHandler),
              ('/w/index', IndexHandler),
              ('/w/index.rss', PageRssHandler),
              ('/w/interwiki', InterwikiHandler),
              ('/users', UsersHandler),
              ('/(.+)', ViewHandler)
              ]

def main():
  application = webapp.WSGIApplication(_WIKI_URLS, debug=_DEBUG)
  wsgiref.handlers.CGIHandler().run(application)

if __name__ == '__main__':
  main()
