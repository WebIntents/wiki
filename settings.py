# -*- coding: utf-8 -*-
# vim: set ts=2 sts=2 sw=2 et:

import logging
from google.appengine.api import memcache
from google.appengine.ext import db

class WikiSettings(db.Model):
  title = db.StringProperty()
  start_page = db.StringProperty()
  admin_email = db.StringProperty()
  # publicly readable
  pread = db.BooleanProperty(True)
  # publicly writable
  pwrite = db.BooleanProperty(False)
  # page footer
  footer = db.StringProperty()

class Settings(object):
  def __init__(self):
    self.data = memcache.get('#settings#')
    if not self.data:
      self.data = self.read()
      if not self.data.key():
        defaults = self.defaults()
        for k in defaults:
          if not getattr(self.data, k):
            setattr(self.data, k, defaults[k])
      memcache.set('#settings#', self.data)

  def defaults(self):
    return {
      'title': 'GAEWiki Demo',
      'start_page': 'welcome',
      'admin_email': 'nobody@example.com',
      'footer': None,
      'pread': True,
      'pwrite': False,
    }

  def read(self):
    tmp = WikiSettings.all().fetch(1)
    if len(tmp):
      return tmp[0]
    else:
      return WikiSettings()

  def dict(self):
    d = {}
    defaults = self.defaults()
    for k in defaults:
      d[k] = getattr(self.data, k)
    return d

  def importFormData(self, r):
    for k in self.defaults():
      if k in ('pread', 'pwrite'):
        nv = bool(r.get(k))
      else:
        nv = r.get(k)
      if nv != getattr(self.data, k):
        logging.info('%s := %s' % (k, nv))
        setattr(self.data, k, nv)
    self.save()

  def save(self):
    memcache.set('#settings#', self.data)
    self.data.put()

  def get(self, k):
    return getattr(self.data, k)
