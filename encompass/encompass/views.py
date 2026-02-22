"""
views definition
"""

# -*- coding: utf-8 -*-
import os
import json
import logging
from functools import wraps
import yaml
import markdown
# import requests
from django.conf import settings
from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.views.decorators.http import require_GET
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from . import tools

# Configure logging
logger = logging.getLogger(__name__)

# Contstants
MY_ENV = os.environ.copy()
MY_ENV["PYTHONUNBUFFERED"] = "TRUE"
MY_ENV["PATH"] = f"{settings.HOME_DIR}/bin:{os.environ['PATH']}"

READ_ONLY_GROUPS = [settings.ENC_ADMIN_GROUP, settings.ENC_VIEWER_GROUP]
ADMIN_ONLY_GROUPS = [settings.ENC_ADMIN_GROUP]


def get_user_groups(user):
    """Return user groups compatible with LDAP and MySQL auth modes."""
    if not getattr(user, "is_authenticated", False):
        return []

    if getattr(settings, "USE_AUTH_MYSQL", False):
        return list(user.groups.values_list("name", flat=True))

    if hasattr(user, "ldap_user"):
        return user.ldap_user.attrs.get("memberOf", [])

    return []


def get_user_identity(user):
    """Return display-friendly user identity fields for templates."""
    if not getattr(user, "is_authenticated", False):
        return {
            "username": settings.UNLOGGED,
            "display_name": settings.UNLOGGED,
            "email": None,
            "groups": [],
        }

    if getattr(settings, "USE_AUTH_MYSQL", False):
        return {
            "username": user.get_username(),
            "display_name": user.get_username() or settings.UNLOGGED,
            "email": user.email or None,
            "groups": get_user_groups(user),
        }

    if hasattr(user, "ldap_user"):
        attrs = user.ldap_user.attrs
        return {
            "username": attrs.get("sAMAccountName", [user.get_username()])[0],
            "display_name": attrs.get("displayName", [settings.UNLOGGED])[0],
            "email": attrs.get("mail", [None])[0],
            "groups": attrs.get("memberOf", []),
        }

    return {
        "username": user.get_username(),
        "display_name": user.get_username() or settings.UNLOGGED,
        "email": user.email or None,
        "groups": [],
    }


def group_required_ldap(group_dn: str | list):
    """group(s) required"""
    group_dn_list = group_dn if isinstance(group_dn, list) else [group_dn]

    def in_group_ldap(user):
        groups = get_user_groups(user)
        if any(group in groups for group in group_dn_list):
            return True
        return False

    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if in_group_ldap(request.user):
                return view_func(request, *args, **kwargs)

            identity = get_user_identity(request.user)
            group_name = tools.get_groups_info(identity["groups"])
            return render(
                request,
                settings.ERROR_HTML,
                {
                    "results": [
                        f"Username {identity['username']} is not authorized to access this feature",
                        "Try with a different user",
                    ],
                    "card_header": "Authorization Error",
                    "disp_name": identity["display_name"],
                    "encompass_email": identity["email"],
                    "group_name": group_name,
                    "watermark": settings.WATERMARK,
                    "current_version": settings.CURRENT_VERSION,
                },
            )

        return wrapper

    return decorator


def healthz(_):
    """
    Ping page
    Using underscore as function argument as we don't use the request object
    """
    data = {"ping": "pong!", "status": "enCompass success"}
    return JsonResponse(data, status=200, content_type="application/json")


@login_required(login_url="/encompass/login/")
def user_settings(request):
    """Allow MySQL users to change their own password."""
    if not getattr(settings, "USE_AUTH_MYSQL", False):
        return render(
            request,
            settings.ERROR_HTML,
            {
                "results": ["User settings are managed externally (LDAP mode)", settings.TRY_AGAIN],
                "current_version": settings.CURRENT_VERSION,
                "watermark": settings.WATERMARK,
            },
        )

    identity = get_user_identity(request.user)
    groups = identity["groups"]
    group_name = tools.get_groups_info(groups)

    if request.method == "POST":
        current_password = request.POST.get("current_password", "")
        new_password = request.POST.get("new_password", "")
        confirm_password = request.POST.get("confirm_password", "")

        if not request.user.check_password(current_password):
            messages.error(request, "Current password is incorrect")
        elif not new_password:
            messages.error(request, "New password cannot be empty")
        elif new_password != confirm_password:
            messages.error(request, "New password and confirmation do not match")
        else:
            request.user.set_password(new_password)
            request.user.save(update_fields=["password"])
            messages.success(request, "Password updated successfully. Please log in again.")
            return redirect("/encompass/logout_confirmation/")

    context = {
        "encompass_email": identity["email"],
        "disp_name": identity["display_name"],
        "group_name": group_name,
        "demo_mode": settings.DEMO_MODE,
        "watermark": settings.WATERMARK,
        "current_version": settings.CURRENT_VERSION,
    }
    return render(request, "user_settings.html", context)


@require_GET
@login_required(login_url="/encompass/login/")
@group_required_ldap(READ_ONLY_GROUPS)
def host_details(_request, hostname):
    """
    Retrieve details for a specific host from the enc.sock API and return as JSON response.
    
    :param _request: Django HttpRequest object (not used in this function, hence the underscore)
    :param hostname: Hostname for which to retrieve details
    """
    try:
        data = tools.get_host_details(hostname)
        return JsonResponse(data)
    except Exception as e:  # pylint: disable=broad-except
        logger.exception("host_details failed for host '%s'", hostname)
        return JsonResponse({"error": str(e)}, status=500)


@require_GET
@login_required(login_url="/encompass/login/")
@group_required_ldap(READ_ONLY_GROUPS)
def group_details(_request, groupname):
    """
    Retrieve details for a specific group from the enc.sock API and return as JSON response.
    
    :param _request: Django HttpRequest object (not used in this function, hence the underscore)
    :param groupname: Group name for which to retrieve details
    """
    try:
        data = tools.get_group_details(groupname)
        if not isinstance(data, dict):
            logger.error(
                "Malformed group payload for '%s': expected dict, got %s",
                groupname,
                type(data).__name__,
            )
            return JsonResponse({"error": "Malformed group data from ENC"}, status=502)
        return JsonResponse(data)
    except Exception as e:  # pylint: disable=broad-except
        logger.exception("group_details failed for group '%s'", groupname)
        return JsonResponse({"error": str(e)}, status=500)


@login_required(login_url="/encompass/login/")
@group_required_ldap(ADMIN_ONLY_GROUPS)
def host_purge_confirmation(request):
    """Show delete confirmation for a host."""
    if request.method != "POST":
        return render(
            request,
            settings.ERROR_HTML,
            {
                "results": ["Invalid request method", settings.TRY_AGAIN],
                "current_version": settings.CURRENT_VERSION,
            },
        )

    hostname = request.POST.get("hostname", "").strip()
    if not hostname:
        return render(
            request,
            settings.ERROR_HTML,
            {
                "results": ["No host selected", settings.TRY_AGAIN],
                "current_version": settings.CURRENT_VERSION,
            },
        )

    identity = get_user_identity(request.user)
    group_name = tools.get_groups_info(identity["groups"])

    context = {
        "hostname": hostname,
        "encompass_email": identity["email"],
        "disp_name": identity["display_name"],
        "group_name": group_name,
        "watermark": settings.WATERMARK,
        "current_version": settings.CURRENT_VERSION,
    }

    return render(request, "host_purge_confirmation.html", context)


@login_required(login_url="/encompass/login/")
@group_required_ldap(ADMIN_ONLY_GROUPS)
def host_purge_execute(request):
    """Delete a host from ENC and return to hosts list."""
    if request.method != "POST":
        return render(
            request,
            settings.ERROR_HTML,
            {
                "results": ["Invalid request method", settings.TRY_AGAIN],
                "current_version": settings.CURRENT_VERSION,
            },
        )

    hostname = request.POST.get("hostname", "").strip()
    if not hostname:
        return render(
            request,
            settings.ERROR_HTML,
            {
                "results": ["No host selected", settings.TRY_AGAIN],
                "current_version": settings.CURRENT_VERSION,
            },
        )

    try:
        tools.delete_host(hostname)
        messages.success(request, f"Host '{hostname}' deleted successfully!")
    except tools.enc_data.EncDataLockTimeout:
        return render(
            request,
            settings.ERROR_HTML,
            {
                "results": [
                    "Another host update is in progress. Please retry.",
                    settings.TRY_AGAIN,
                ],
                "current_version": settings.CURRENT_VERSION,
            },
        )
    except Exception as e:  # pylint: disable=broad-except
        return render(
            request,
            settings.ERROR_HTML,
            {
                "results": [str(e), settings.TRY_AGAIN],
                "current_version": settings.CURRENT_VERSION,
            },
        )

    return redirect("/encompass/hosts")


@login_required(login_url="/encompass/login/")
@group_required_ldap(ADMIN_ONLY_GROUPS)
def host_save(request):
    """Save a host definition via ENC."""
    if request.method != "POST":
        return JsonResponse({"error": "Invalid request method"}, status=405)

    try:
        payload = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON payload"}, status=400)

    hostname = str(payload.get("hostname", "")).strip()
    if not hostname:
        return JsonResponse({"error": "No host selected"}, status=400)

    host_payload = {
        "environment": payload.get("environment", ""),
        "classes": payload.get("classes", []),
        "parameters": payload.get("parameters", {}),
    }

    try:
        tools.update_host(hostname, host_payload)
    except tools.enc_data.EncDataLockTimeout:
        return JsonResponse(
            {"error": "Conflict", "message": "Another host update is in progress"},
            status=409,
        )
    except Exception as e:  # pylint: disable=broad-except
        logger.exception("host_save failed for host '%s'", hostname)
        return JsonResponse({"error": str(e)}, status=500)

    return JsonResponse({"status": "ok"})


@login_required(login_url="/encompass/login/")
@group_required_ldap(ADMIN_ONLY_GROUPS)
def host_add(request):
    """Add a new host to ENC."""
    identity = get_user_identity(request.user)
    group_name = tools.get_groups_info(identity["groups"])

    if request.method == "GET":
        # Show the form
        context = {
            "encompass_email": identity["email"],
            "disp_name": identity["display_name"],
            "group_name": group_name,
            "watermark": settings.WATERMARK,
            "current_version": settings.CURRENT_VERSION,
            "feature_branch": settings.FEATURE_BRANCH,
            "puppet_environments": settings.PUPPET_ENVIRONMENTS,
        }
        return render(request, "host_add.html", context)

    # POST: Create the host
    hostname = request.POST.get("hostname", "").strip()
    if not hostname:
        return render(
            request,
            settings.ERROR_HTML,
            {
                "results": ["Hostname is required", settings.TRY_AGAIN],
                "current_version": settings.CURRENT_VERSION,
            },
        )

    # Check if host already exists
    if tools.host_exists(hostname):
        return render(
            request,
            settings.ERROR_HTML,
            {
                "results": [f"Host '{hostname}' already exists", settings.TRY_AGAIN],
                "current_version": settings.CURRENT_VERSION,
            },
        )

    environment = request.POST.get("environment", "").strip()
    classes = [cls.strip() for cls in request.POST.getlist("classes[]") if cls.strip()]

    # Build parameters dict from keys and values
    param_keys = request.POST.getlist("param_keys[]")
    param_values = request.POST.getlist("param_values[]")
    parameters = {}
    for key, value in zip(param_keys, param_values):
        key = key.strip()
        if key:
            parameters[key] = value

    host_payload = {
        "environment": environment,
        "classes": classes,
        "parameters": parameters,
    }

    try:
        tools.create_host(hostname, host_payload)
        messages.success(request, f"Host '{hostname}' created successfully!")
    except tools.enc_data.EncDataLockTimeout:
        return render(
            request,
            settings.ERROR_HTML,
            {
                "results": [
                    "Another host update is in progress. Please retry.",
                    settings.TRY_AGAIN,
                ],
                "current_version": settings.CURRENT_VERSION,
            },
        )
    except Exception as e:  # pylint: disable=broad-except
        return render(
            request,
            settings.ERROR_HTML,
            {
                "results": [f"Failed to create host: {str(e)}", settings.TRY_AGAIN],
                "current_version": settings.CURRENT_VERSION,
            },
        )

    # Success - redirect to hosts list with a success message
    return redirect("/encompass/hosts")


@login_required(login_url="/encompass/login/")
@group_required_ldap(ADMIN_ONLY_GROUPS)
def group_purge_confirmation(request):
    """Show confirmation page for deleting a group."""
    groupname = request.GET.get("name", "").strip()
    if not groupname:
        return render(
            request,
            settings.ERROR_HTML,
            {
                "results": ["No group specified", settings.TRY_AGAIN],
                "current_version": settings.CURRENT_VERSION,
            },
        )

    try:
        group_info = tools.get_group_details(groupname)
    except Exception as e:  # pylint: disable=broad-except
        return render(
            request,
            settings.ERROR_HTML,
            {
                "results": [f"Failed to retrieve group details: {str(e)}", settings.TRY_AGAIN],
                "current_version": settings.CURRENT_VERSION,
            },
        )

    identity = get_user_identity(request.user)
    group_name = tools.get_groups_info(identity["groups"])

    context = {
        "groupname": groupname,
        "group_details": group_info,
        "encompass_email": identity["email"],
        "disp_name": identity["display_name"],
        "group_name": group_name,
        "watermark": settings.WATERMARK,
        "current_version": settings.CURRENT_VERSION,
    }
    return render(request, "group_purge_confirmation.html", context)


@login_required(login_url="/encompass/login/")
@group_required_ldap(ADMIN_ONLY_GROUPS)
def group_purge_execute(request):
    """Execute deletion of a group."""
    if request.method != "POST":
        return JsonResponse({"error": "Invalid request method"}, status=405)

    groupname = request.POST.get("groupname", "").strip()
    if not groupname:
        return render(
            request,
            settings.ERROR_HTML,
            {
                "results": ["No group specified", settings.TRY_AGAIN],
                "current_version": settings.CURRENT_VERSION,
            },
        )

    try:
        tools.delete_group(groupname)
        messages.success(request, f"Group '{groupname}' deleted successfully!")
    except tools.enc_data.EncDataLockTimeout:
        return render(
            request,
            settings.ERROR_HTML,
            {
                "results": [
                    "Another group update is in progress. Please retry.",
                    settings.TRY_AGAIN,
                ],
                "current_version": settings.CURRENT_VERSION,
            },
        )
    except Exception as e:  # pylint: disable=broad-except
        return render(
            request,
            settings.ERROR_HTML,
            {
                "results": [f"Failed to delete group: {str(e)}", settings.TRY_AGAIN],
                "current_version": settings.CURRENT_VERSION,
            },
        )

    return redirect("/encompass/groups")


@login_required(login_url="/encompass/login/")
@group_required_ldap(ADMIN_ONLY_GROUPS)
def group_save(request):
    """Save a group definition via ENC."""
    if request.method != "POST":
        return JsonResponse({"error": "Invalid request method"}, status=405)

    try:
        payload = json.loads(request.body or "{}")
        logger.info("group_save received payload: %s", payload)
    except json.JSONDecodeError as e:
        logger.error("JSON decode error: %s", e)
        return JsonResponse({"error": "Invalid JSON payload"}, status=400)

    groupname = str(payload.get("groupname", "")).strip()
    if not groupname:
        logger.warning("group_save called without groupname")
        return JsonResponse({"error": "No group selected"}, status=400)

    group_payload = {
        "environment": payload.get("environment", ""),
        "classes": payload.get("classes", []),
        "hosts": payload.get("hosts", []),
        "parameters": payload.get("parameters", {}),
    }

    try:
        logger.info("Calling update_group for '%s' with payload: %s", groupname, group_payload)
        tools.update_group(groupname, group_payload)
        logger.info("Successfully updated group '%s'", groupname)
    except tools.enc_data.EncDataLockTimeout:
        return JsonResponse(
            {"error": "Conflict", "message": "Another group update is in progress"},
            status=409,
        )
    except Exception as e:  # pylint: disable=broad-except
        logger.error("Error updating group '%s': %s", groupname, e, exc_info=True)
        return JsonResponse({"error": str(e)}, status=500)

    return JsonResponse({"status": "ok"})


@login_required(login_url="/encompass/login/")
@group_required_ldap(ADMIN_ONLY_GROUPS)
def group_add(request):
    """Add a new group to ENC."""
    identity = get_user_identity(request.user)
    group_name = tools.get_groups_info(identity["groups"])

    if request.method == "GET":
        # Show the form
        context = {
            "encompass_email": identity["email"],
            "disp_name": identity["display_name"],
            "group_name": group_name,
            "watermark": settings.WATERMARK,
            "current_version": settings.CURRENT_VERSION,
            "feature_branch": settings.FEATURE_BRANCH,
            "puppet_environments": settings.PUPPET_ENVIRONMENTS,
        }
        return render(request, "group_add.html", context)

    # POST: Create the group
    groupname = request.POST.get("groupname", "").strip()
    if not groupname:
        return render(
            request,
            settings.ERROR_HTML,
            {
                "results": ["Group name is required", settings.TRY_AGAIN],
                "current_version": settings.CURRENT_VERSION,
            },
        )

    # Check if group already exists
    if tools.group_exists(groupname):
        return render(
            request,
            settings.ERROR_HTML,
            {
                "results": [f"Group '{groupname}' already exists", settings.TRY_AGAIN],
                "current_version": settings.CURRENT_VERSION,
            },
        )

    environment = request.POST.get("environment", "").strip()
    classes = [cls.strip() for cls in request.POST.getlist("classes[]") if cls.strip()]
    hosts = [host.strip() for host in request.POST.getlist("hosts[]") if host.strip()]

    # Validate that at least one class is provided
    if not classes:
        return render(
            request,
            settings.ERROR_HTML,
            {
                "results": ["At least one class is required", settings.TRY_AGAIN],
                "current_version": settings.CURRENT_VERSION,
            },
        )

    # Build parameters dict from keys and values
    param_keys = request.POST.getlist("param_keys[]")
    param_values = request.POST.getlist("param_values[]")
    parameters = {}
    for key, value in zip(param_keys, param_values):
        key = key.strip()
        if key:
            parameters[key] = value

    group_payload = {
        "environment": environment,
        "classes": classes,
        "hosts": hosts,
        "parameters": parameters,
    }

    try:
        tools.create_group(groupname, group_payload)
        messages.success(request, f"Group '{groupname}' created successfully!")
    except tools.enc_data.EncDataLockTimeout:
        return render(
            request,
            settings.ERROR_HTML,
            {
                "results": [
                    "Another group update is in progress. Please retry.",
                     settings.TRY_AGAIN,
                ],
                "current_version": settings.CURRENT_VERSION,
            },
        )
    except Exception as e:  # pylint: disable=broad-except
        return render(
            request,
            settings.ERROR_HTML,
            {
                "results": [
                    f"Failed to create group: {str(e)}",
                    settings.TRY_AGAIN,
                ],
                "current_version": settings.CURRENT_VERSION,
            },
        )

    # Success - redirect to groups list with a success message
    return redirect("/encompass/groups")


def help_page(request):
    """
    Docstring for help_page

    :param request: Django HttpRequest object
    :return: Rendered help page with content from help.md
    """
    identity = get_user_identity(request.user)
    group_name = tools.get_groups_info(identity["groups"])

    with open("templates/help.md", encoding="utf-8") as f:
        content = f.read()

    html = markdown.markdown(content, extensions=["fenced_code", "tables"])
    context = {
        "encompass_email": identity["email"],
        "group_name": group_name,
        "disp_name": identity["display_name"],
        "watermark": settings.WATERMARK,
        "current_version": settings.CURRENT_VERSION,
        "content": html,
    }

    return render(request, "help.html", context)


# def help_page(request):
#    """Dynamic Help page (fetches remote HTML content)"""
#    try:
#        encompass_email = request.user.ldap_user.attrs.get("mail", [None])[0]
#        disp_name = request.user.ldap_user.attrs.get(
#            "displayName", [settings.UNLOGGED]
#        )[0]
#        groups = request.user.ldap_user.attrs.get("memberOf", [])
#    except AttributeError:
#        encompass_email = None
#        disp_name = settings.UNLOGGED
#        groups = []
#
#    group_name = tools.get_groups_info(groups)
#    url = "https://cds.geant.org/tformator/help.html"
#    try:
#        response = requests.get(url, timeout=5)
#        if response.status_code == 200:
#            remote_html = markdown.markdown(response.text)
#        else:
#            remote_html = "<p>Help page temporarily unavailable.</p>"
#    except Exception:  # pylint: disable=broad-except
#        remote_html = "<p>Help page could not be loaded.</p>"
#
#    context = {
#        "encompass_email": encompass_email,
#        "group_name": group_name,
#        "disp_name": disp_name,
#        "watermark": settings.WATERMARK,
#        "current_version": settings.CURRENT_VERSION,
#        "remote_html": remote_html,
#    }
#
#    return render(request, "help.html", context)


def about_page(request):
    """About page"""
    identity = get_user_identity(request.user)
    group_name = tools.get_groups_info(identity["groups"])
    context = {
        "encompass_email": identity["email"],
        "group_name": group_name,
        "disp_name": identity["display_name"],
        "watermark": settings.WATERMARK,
        "current_version": settings.CURRENT_VERSION,
    }
    return render(request, "about.html", context)


@login_required(login_url="login/")
@group_required_ldap(READ_ONLY_GROUPS)
def home_page(request):
    """list available groups"""
    identity = get_user_identity(request.user)
    groups = identity["groups"]
    group_name = tools.get_groups_info(groups)
    is_db_auth = getattr(settings, "USE_AUTH_MYSQL", False)
    is_admin = settings.ENC_ADMIN_GROUP in groups
    if is_db_auth:
        is_admin = is_admin and request.user.get_username() == "admin"
    context = {
        "groups": groups,
        "encompass_email": identity["email"],
        "disp_name": identity["display_name"],
        "group_name": group_name,
        "watermark": settings.WATERMARK,
        "current_version": settings.CURRENT_VERSION,
        "is_db_auth": is_db_auth,
        "is_admin": is_admin,
    }

    return render(request, "home.html", context)


@login_required(login_url="/encompass/login/")
@group_required_ldap(READ_ONLY_GROUPS)
def host_list(request):
    """list hosts for health check"""
    identity = get_user_identity(request.user)
    groups = identity["groups"]
    group_name = tools.get_groups_info(groups)
    is_db_auth = getattr(settings, "USE_AUTH_MYSQL", False)
    can_save_hosts = request.user.is_superuser or settings.ENC_ADMIN_GROUP in groups
    if is_db_auth and not request.user.is_superuser:
        can_save_hosts = can_save_hosts and request.user.get_username() == "admin"
    host_names = tools.list_hosts()
    context = {
        "groups": groups,
        "encompass_email": identity["email"],
        "disp_name": identity["display_name"],
        "group_name": group_name,
        "watermark": settings.WATERMARK,
        "current_version": settings.CURRENT_VERSION,
        "hosts": host_names,
        "feature_branch": settings.FEATURE_BRANCH,
        "puppet_environments": settings.PUPPET_ENVIRONMENTS,
        "can_save_hosts": can_save_hosts,
    }

    return render(request, "hosts.html", context)


@login_required(login_url="/encompass/login/")
@group_required_ldap(READ_ONLY_GROUPS)
def group_list(request):
    """list groups for health check"""
    identity = get_user_identity(request.user)
    groups = identity["groups"]
    group_name = tools.get_groups_info(groups)
    groups_list = tools.list_groups()
    context = {
        "groups": groups,
        "encompass_email": identity["email"],
        "disp_name": identity["display_name"],
        "group_name": group_name,
        "watermark": settings.WATERMARK,
        "current_version": settings.CURRENT_VERSION,
        "groups_list": groups_list,
        "feature_branch": settings.FEATURE_BRANCH,
        "puppet_environments": settings.PUPPET_ENVIRONMENTS,
    }

    return render(request, "groups.html", context)


@login_required(login_url="/encompass/login/")
@group_required_ldap(READ_ONLY_GROUPS)
def query_host(request):
    """
    Query a specific host to see its ENC classification.
    GET: Show the query form
    POST: Query the host and display results
    """
    identity = get_user_identity(request.user)
    groups = identity["groups"]
    group_name = tools.get_groups_info(groups)

    context = {
        "encompass_email": identity["email"],
        "group_name": group_name,
        "disp_name": identity["display_name"],
        "watermark": settings.WATERMARK,
        "current_version": settings.CURRENT_VERSION,
    }

    if request.method == "POST":
        hostname = request.POST.get("hostname", "").strip()

        if not hostname:
            context["error"] = "Please enter a hostname"
            return render(request, "query_host.html", context)

        try:
            host_data = tools.get_host_details(hostname)
            if host_data is None:
                context["error"] = f"Host '{hostname}' not found in ENC"
                context["hostname"] = hostname
                return render(request, "query_host.html", context)

            # Convert back to YAML for display (pretty printed)
            yaml_output = yaml.dump(host_data, default_flow_style=False, sort_keys=False)

            context["hostname"] = hostname
            context["yaml_output"] = yaml_output
            context["host_data"] = host_data

        except Exception as e:  # pylint: disable=broad-except
            logger.exception("Error querying host '%s'", hostname)
            context["error"] = f"Failed to query host: {str(e)}"
            context["hostname"] = hostname

    return render(request, "query_host.html", context)


@login_required(login_url="/encompass/login/")
def logout_confirmation(request):
    """show update confirmation"""
    identity = get_user_identity(request.user)
    group_name = tools.get_groups_info(identity["groups"])
    context = {
        "encompass_email": identity["email"],
        "group_name": group_name,
        "disp_name": identity["display_name"],
        "watermark": settings.WATERMARK,
        "current_version": settings.CURRENT_VERSION,
    }

    return render(request, "logout_confirmation.html", context)
