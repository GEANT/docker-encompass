"""URL configuration for encapsule read-only ENC runtime."""

from django.urls import re_path

from . import agent_views

urlpatterns = [
    re_path(r"^healthz$", agent_views.healthz),
    re_path(r"^hosts/?$", agent_views.hosts_collection),
    re_path(r"^hosts/(?P<fqdn>[^/]+)/?$", agent_views.hosts_item),
    re_path(r"^groups/?$", agent_views.groups_collection),
    re_path(r"^groups/(?P<name>[^/]+)/?$", agent_views.groups_item),
    re_path(r"^sync/?$", agent_views.sync_from_git),
]
