"""WSGI config for encapsule runtime."""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "encompass.agent_settings")

application = get_wsgi_application()
