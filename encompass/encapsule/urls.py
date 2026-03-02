"""URL configuration for encapsule read-only ENC runtime."""

from django.urls import re_path

from . import views

urlpatterns = [
    re_path(r"^healthz$", views.healthz),
    re_path(r"^hosts/?$", views.hosts_collection),
    re_path(r"^hosts/(?P<fqdn>[^/]+)/?$", views.hosts_item),
    re_path(r"^groups/?$", views.groups_collection),
    re_path(r"^groups/(?P<name>[^/]+)/?$", views.groups_item),
    re_path(r"^sync/?$", views.sync_from_git),
]
