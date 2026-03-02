"""WSGI config for encapsule runtime."""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "encapsule.settings")

application = get_wsgi_application()
