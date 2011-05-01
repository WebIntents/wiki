# encoding=utf-8

import model
import settings

def is_page_whitelisted(title):
    return False

def is_page_blacklisted(title):
    return False

def can_edit_page(title, user, is_admin):
    if is_admin:
        return True

    if title.startswith('gaewiki:'):
        return False

    # TODO: locked

    if '/' in title and settings.get('parents-must-exist') == 'yes':
        parent_title = '/'.join(title.split('/')[:-1])
        parent = model.WikiContent.gql('WHERE title = :1', parent_title).get()
        if parent is None:
            return False

    if settings.get('open-editing') == 'yes':
        return not is_page_blacklisted(title)
    if user is None:
        return False
    if user is not None:
        return False
    if user.email() not in settings.get('editors', []):
        return False


def can_read_page(title, user, is_admin):
    return True


def can_see_most_pages(user, is_admin):
    if is_admin:
        return True
    if settings.get('open-reading') == 'yes':
        return True
    if user is None:
        return False
    if user.email() in settings.get('readers', []):
        return True
    if user.email() in settings.get('editors', []):
        return True
    return False
