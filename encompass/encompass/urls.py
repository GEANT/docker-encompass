"""
URL configuration for test_project project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/4.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.conf import settings
from django.shortcuts import redirect
from django.urls import path
from django.urls import re_path
from django.contrib.auth import views as auth_views
from django.views.generic.base import RedirectView
from django.contrib import admin
from . import views
from . import enc_views

favicon_view = RedirectView.as_view(
    url="/static/images/favicon.ico", permanent=True
)

extra = {
    "watermark": settings.WATERMARK,
    "current_version": settings.CURRENT_VERSION,
}

urlpatterns = [
    re_path(r"^favicon\.ico$", favicon_view),
    re_path(
        r"^encompass/login/$",
        auth_views.LoginView.as_view(template_name="login.html", extra_context=extra),
        name="login",
    ),
    re_path(
        r"^encompass/logout/$",
        auth_views.LogoutView.as_view(template_name="logout.html", extra_context=extra),
        name="logout",
    ),
    path("admin/", admin.site.urls),
    re_path(r"^$", lambda req: redirect(views.home_page)),
    re_path(r"^encompass/$", views.home_page),
    re_path(r"^encompass/help/$", views.help_page),
    re_path(r"^encompass/about/$", views.about_page),
    re_path(r"^encompass/query/$", views.query),
    re_path(r"^encompass/query_host/$", views.query_host),
    re_path(r"^encompass/logout_confirmation/$", views.logout_confirmation),
    re_path(r"^encompass/hosts$", views.host_list),
    re_path(r"^encompass/hosts/add$", views.host_add),
    re_path(r"^encompass/hosts/(?P<hostname>[^/]+)/details$", views.host_details),
    re_path(r"^encompass/host_purge_confirmation/$", views.host_purge_confirmation),
    re_path(r"^encompass/host_purge_execute/$", views.host_purge_execute),
    re_path(r"^encompass/host_save/$", views.host_save),
    re_path(r"^encompass/groups$", views.group_list),
    re_path(r"^encompass/groups/add$", views.group_add),
    re_path(r"^encompass/groups/(?P<groupname>[^/]+)/details$", views.group_details),
    re_path(r"^encompass/group_purge_confirmation/$", views.group_purge_confirmation),
    re_path(r"^encompass/group_purge_execute/$", views.group_purge_execute),
    re_path(r"^encompass/group_save/$", views.group_save),
    re_path(r"^healthz$", views.healthz),
    re_path(r"^hosts/?$", enc_views.hosts_collection),
    re_path(r"^hosts/(?P<fqdn>[^/]+)/?$", enc_views.hosts_item),
    re_path(r"^groups/?$", enc_views.groups_collection),
    re_path(r"^groups/(?P<name>[^/]+)/?$", enc_views.groups_item),
]
