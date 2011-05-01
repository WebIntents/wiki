# encoding=utf-8

import datetime
import logging

import model
import settings
import util


def get_start_page_name():
    return 'Welcome'


def get_page_by_name(title):
    page = model.WikiContent.gql('WHERE title = :1', title).get()
    if page is None:
        page = model.WikiContent(title=title)
    return page


def get_page_template(title, user, is_admin):
    template = '# PAGE_TITLE\n\n**PAGE_TITLE** is ...'

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

    page = model.WikiContent(title=title)
    page.body = template.replace('PAGE_TITLE', title)
    return page


def get_all_pages():
    return sorted(model.WikiContent.all().order('title').fetch(1000), key=lambda p: p.title.lower())


def get_by_label(label):
    return model.WikiContent.gql('WHERE labels = :1 ORDER BY title', label).fetch(100)


def get_open_pages():
    if settings.get('open-reading') == 'yes':
        pages = model.WikiContent.all()
    else:
        pages = model.WikiContent.gql('WHERE pread = :1', True).fetch(1000)
    return sorted(pages, key=lambda p: p.title.lower())


def get_page_history(title):
    return model.WikiRevision.gql('WHERE title = :1 ORDER BY created DESC', title).fetch(100)


def get_changes():
    if settings.get('open-reading') == 'yes':
        pages = model.WikiContent.all().order('-updated').fetch(20)
    else:
        pages = model.wikiContent.gql('WHERE pread = :1 ORDER BY -updated', True).fetch(20)
    return pages


def get_backlinks(title):
    pages = model.WikiContent.gql('WHERE links = :1', title).fetch(1000)
    return get_page_by_name(title), pages


def get_users():
    return model.WikiUser.all().order('wiki_user').fetch(1000)


def get_wiki_user(user):
    if user is None:
        return None
    wiki_user = model.WikiUser.gql('WHERE wiki_user = :1', user).get()
    if wiki_user is None:
        wiki_user = model.WikiUser(wiki_user=user)
        wiki_user.put()
    return wiki_user


def backup_page(page):
    """Archives the current page revision."""
    logging.debug(u'Backing up page "%s"' % page.title)
    archive = model.WikiRevision(title=page.title, revision_body=page.body, author=page.author, created=page.updated)
    archive.put()


def update_page(title, body, author, delete):
    if title == 'gaewiki:settings':
        settings.flush()
    page = get_page_by_name(title)
    if page.is_saved():
        backup_page(page)
        if delete:
            logging.debug(u'Deleting page "%s"' % title)
            page.delete()
            return

    logging.debug(u'Updating page "%s"' % title)

    page.body = body
    page.author = get_wiki_user(author)
    page.updated = datetime.datetime.now()

    options = util.parse_page(page.body)
    page.redirect = options.get('redirect')
    page.pread = options.get('public') == 'yes' and options.get('private') != 'yes'
    page.labels = options.get('labels', [])

    # TODO: rename
    # TODO: cross-link

    page.put()


def get_interwikis():
    iw = [(k[10:], v) for k, v in settings.get_all().items() if k.startswith('interwiki-')]
    return sorted(iw, key=lambda iw: iw[0])
