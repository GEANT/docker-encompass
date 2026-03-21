"""
Minimal Django settings for the encapsule ENC agent runtime (no DB dependency)
"""

import json
import os
import socket
from urllib.parse import urlparse


def env_json(name, default):
    """
    Imports a JSON object and creates a dictionary or list from it.
    """
    return json.loads(os.environ.get(name, json.dumps(default)))


def env_log_level(name, default="ERROR"):
    """
    Return a validated logging level from environment.
    """
    valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
    level = str(os.environ.get(name, default)).strip().upper()
    return level if level in valid_levels else default


def _sync_target_hosts() -> list[str]:
    """Extract hostnames from ENCAPSULE_SYNC_HOST entries for ALLOWED_HOSTS."""
    raw = str(os.environ.get("ENCAPSULE_SYNC_HOST", "")).strip()
    if not raw:
        return []

    hosts: list[str] = []
    for entry in raw.split(","):
        token = entry.strip()
        if not token or token.startswith("_"):
            continue

        if token.startswith("http://") or token.startswith("https://"):
            parsed = urlparse(token)
            if parsed.hostname:
                hosts.append(parsed.hostname)
            continue

        if token.startswith("[") and "]" in token:
            hosts.append(token[1 : token.index("]")])
            continue

        if ":" in token and token.count(":") == 1:
            host, _port = token.rsplit(":", 1)
            if host:
                hosts.append(host)
            continue

        hosts.append(token)

    return hosts


SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "encapsule-dev-only-secret")
DEBUG = env_json("DEBUG", False)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

try:
    LOCAL_ADDR = socket.getaddrinfo(socket.getfqdn(), None, socket.AF_INET)[0][4][0]
except socket.gaierror:
    LOCAL_ADDR = "127.0.0.1"

DEFAULT_LOCAL_ALLOWED_HOSTS = list({"localhost", "127.0.0.1", LOCAL_ADDR})
ALLOWED_HOSTS = (
    env_json("ALLOWED_HOSTS", [])
    + DEFAULT_LOCAL_ALLOWED_HOSTS
    + _sync_target_hosts()
)
ALLOWED_HOSTS = list(dict.fromkeys(ALLOWED_HOSTS))


# Add allow_cidr to middleware for ALLOWED_CIDR_NETS support
INSTALLED_APPS = (
    "django.contrib.contenttypes",
)

ALLOWED_CIDR_NETS = env_json("ALLOWED_CIDR_NETS", [])

MIDDLEWARE = (
    "django.middleware.common.CommonMiddleware",
    "allow_cidr.middleware.AllowCIDRMiddleware",
)

ROOT_URLCONF = "encapsule.urls"

TEMPLATES = []

WSGI_APPLICATION = "encapsule.wsgi.application"

USE_TZ = True
TIME_ZONE = os.environ.get("TIME_ZONE", "UTC")
LANGUAGE_CODE = os.environ.get("LANGUAGE_CODE", "en-us")

DATABASES = {}

ENCAPSULE_LOG_LEVEL = env_log_level(
    "ENCAPSULE_LOGGING",
    "DEBUG" if DEBUG else "INFO",
)
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "stream_to_console": {
            "level": ENCAPSULE_LOG_LEVEL,
            "class": "logging.StreamHandler",
        },
    },
    "loggers": {
        "django.server": {
            "handlers": ["stream_to_console"],
            "level": ENCAPSULE_LOG_LEVEL,
            "propagate": False,
        },
        "django.request": {
            "handlers": ["stream_to_console"],
            "level": ENCAPSULE_LOG_LEVEL,
            "propagate": False,
        },
        "encompass": {
            "handlers": ["stream_to_console"],
            "level": ENCAPSULE_LOG_LEVEL,
            "propagate": False,
        },
    },
}
