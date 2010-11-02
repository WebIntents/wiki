import os
from google.appengine.api import namespace_manager

def namespace_manager_default_namespace_for_request():
    # name = os.environ['SERVER_NAME']
    name = namespace_manager.google_apps_namespace()
    return name
