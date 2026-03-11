"""
views definition
"""

# pylint: disable=too-many-lines

# -*- coding: utf-8 -*-
import os
import json
import logging
import re
from functools import wraps
import ldap
import yaml
import markdown
from django.conf import settings
from django.core.paginator import Paginator
from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.views.decorators.http import require_GET
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.templatetags.static import static
from . import tools
from . import user_helpers
from . import spring_cleaning

LDAP_OPT_PROTOCOL_VERSION = getattr(ldap, "OPT_PROTOCOL_VERSION", 3)
LDAP_OPT_REFERRALS = getattr(ldap, "OPT_REFERRALS", 0)
LDAP_MOD_DELETE = getattr(ldap, "MOD_DELETE", 1)
LDAP_MOD_ADD = getattr(ldap, "MOD_ADD", 0)

# Configure logging
logger = logging.getLogger(__name__)

# Contstants
MY_ENV = os.environ.copy()
MY_ENV["PYTHONUNBUFFERED"] = "TRUE"
MY_ENV["PATH"] = f"{settings.HOME_DIR}/bin:{os.environ['PATH']}"
_IMG_SRC_PATTERN = re.compile(
    r'(<img\b[^>]*\bsrc=["\'])([^"\']+)(["\'])', re.IGNORECASE
)


def _rewrite_relative_markdown_image_src(html: str) -> str:
    """Convert relative markdown image sources to Django static URLs."""

    def _replace(match):
        prefix, src, suffix = match.groups()
        lowered = src.lower()
        if lowered.startswith(("http://", "https://", "data:", "/", "#")):
            return match.group(0)

        static_path = src[7:] if src.startswith("static/") else src
        return f"{prefix}{static(static_path)}{suffix}"

    return _IMG_SRC_PATTERN.sub(_replace, html)


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


def _normalize_group_value(value: str) -> str:
    """Normalize LDAP group DNs for resilient comparisons."""
    return re.sub(r"\s+", "", str(value or "")).lower()


def _group_name_from_dn(value: str) -> str:
    """Extract group common name from a DN if present (CN=...)."""
    token = str(value or "").strip()
    for part in token.split(","):
        head = part.strip()
        if head.lower().startswith("cn="):
            return head[3:].strip().lower()
    return token.lower()


def _user_in_any_group(groups, expected_groups) -> bool:
    """Match user groups against expected groups by normalized DN and CN."""
    normalized_user = {_normalize_group_value(item) for item in groups}
    names_user = {_group_name_from_dn(item) for item in groups}

    for expected in expected_groups:
        expected_dn = _normalize_group_value(expected)
        expected_name = _group_name_from_dn(expected)
        if expected_dn in normalized_user or expected_name in names_user:
            return True
    return False


def _ldap_error_detail(err: Exception) -> str:
    """Extract a concise, user-friendly detail from an LDAP exception."""
    if not getattr(err, "args", None):
        return ""
    first = err.args[0]
    if isinstance(first, dict):
        desc = str(first.get("desc", "")).strip()
        info = str(first.get("info", "")).strip()
        return ": ".join(part for part in (desc, info) if part)
    return str(first).strip()


def _is_ldap_exception(err: Exception, exc_name: str) -> bool:
    """Best-effort check for a specific python-ldap exception class."""
    exc_cls = getattr(ldap, exc_name, None)
    return isinstance(exc_cls, type) and isinstance(err, exc_cls)


def _change_password_ldap(user, current_password: str, new_password: str):
    """Change user password against LDAP/AD using the authenticated user DN."""
    ldap_user = getattr(user, "ldap_user", None)
    user_dn = str(getattr(ldap_user, "dn", "")).strip()
    if not user_dn:
        return False, "Unable to resolve your LDAP identity for password change."

    ldap_profile = str(getattr(settings, "LDAP_PROF", "ad")).strip().lower()
    ldap_proto = str(os.environ.get("LDAP_PROTO", "")).strip().lower()
    if ldap_profile == "ad" and ldap_proto != "ldaps":
        return (
            False,
            "Active Directory password change requires LDAPS (set LDAP_PROTO=ldaps).",
        )

    conn = None
    try:
        conn = ldap.initialize(settings.AUTH_LDAP_SERVER_URI)
        conn.set_option(LDAP_OPT_PROTOCOL_VERSION, 3)
        conn.set_option(LDAP_OPT_REFERRALS, 0)
        conn.simple_bind_s(user_dn, current_password)

        if ldap_profile == "ad":
            old_password = f'"{current_password}"'.encode("utf-16-le")
            updated_password = f'"{new_password}"'.encode("utf-16-le")
            conn.modify_s(
                user_dn,
                [
                    (LDAP_MOD_DELETE, "unicodePwd", [old_password]),
                    (LDAP_MOD_ADD, "unicodePwd", [updated_password]),
                ],
            )
        else:
            conn.passwd_s(user_dn, current_password, new_password)

        return True, "Password updated successfully. Please log in again."
    except Exception as err:  # pylint: disable=broad-except
        if _is_ldap_exception(err, "INVALID_CREDENTIALS"):
            return False, "Current password is incorrect"

        if _is_ldap_exception(err, "CONSTRAINT_VIOLATION"):
            detail = _ldap_error_detail(err)
            message = "New password does not meet directory policy requirements"
            if detail:
                message = f"{message}: {detail}"
            return False, message

        if _is_ldap_exception(err, "UNWILLING_TO_PERFORM"):
            detail = _ldap_error_detail(err)
            message = "Directory refused the password change request"
            if detail:
                message = f"{message}: {detail}"
            return False, message

        detail = _ldap_error_detail(err)
        logger.warning(
            "LDAP password change failed for user '%s': %s",
            user.get_username(),
            detail or repr(err),
        )
        message = "Password change failed due to a directory error"
        if detail:
            message = f"{message}: {detail}"
        return False, message
    finally:
        if conn is not None:
            try:
                conn.unbind_s()
            except Exception:  # pylint: disable=broad-except
                pass


def group_required_ldap(group_dn: str | list):
    """group(s) required"""
    group_dn_list = group_dn if isinstance(group_dn, list) else [group_dn]

    def in_group_ldap(user):
        groups = get_user_groups(user)
        if _user_in_any_group(groups, group_dn_list):
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


def healthz(_request):
    """Ping page for Nomad/Kubernetes health checks."""
    data = {"ping": "pong!", "status": "enCompass success"}
    return JsonResponse(data, status=200, content_type="application/json")


@login_required(login_url="/encompass/login/")
def user_settings(request):
    """Allow users to change their own password for supported auth backends."""
    is_db_auth = getattr(settings, "USE_AUTH_MYSQL", False)
    is_ldap_auth = getattr(settings, "USE_AUTH_LDAP", False)

    if not is_db_auth and not is_ldap_auth:
        return render(
            request,
            settings.ERROR_HTML,
            {
                "results": [
                    "User settings are managed externally",
                    settings.TRY_AGAIN,
                ],
                "current_version": settings.CURRENT_VERSION,
                "watermark": settings.WATERMARK,
            },
        )

    identity = get_user_identity(request.user)
    groups = identity["groups"]
    group_name = tools.get_groups_info(groups)

    if request.method == "POST":
        if settings.DEMO_MODE:
            messages.error(request, "This feature is unavailable on the demo site")
            return redirect("/encompass/user_settings/")

        current_password = request.POST.get("current_password", "")
        new_password = request.POST.get("new_password", "")
        confirm_password = request.POST.get("confirm_password", "")

        if not request.user.check_password(current_password):
            messages.error(request, "Current password is incorrect")
        elif not new_password:
            messages.error(request, "New password cannot be empty")
        elif new_password != confirm_password:
            messages.error(request, "New password and confirmation do not match")
        elif is_db_auth:
            request.user.set_password(new_password)
            request.user.save(update_fields=["password"])
            messages.success(
                request, "Password updated successfully. Please log in again."
            )
            return redirect("/encompass/logout_confirmation/")
        else:
            changed, message = _change_password_ldap(
                request.user, current_password, new_password
            )
            if changed:
                messages.success(request, message)
                return redirect("/encompass/logout_confirmation/")
            messages.error(request, message)

    context = {
        "encompass_email": identity["email"],
        "disp_name": identity["display_name"],
        "group_name": group_name,
        "is_db_auth": is_db_auth,
        "is_ldap_auth": is_ldap_auth,
        "demo_mode": settings.DEMO_MODE,
        "watermark": settings.WATERMARK,
        "current_version": settings.CURRENT_VERSION,
    }
    return render(request, "user_settings.html", context)


@require_GET
@login_required(login_url="/encompass/login/")
@group_required_ldap(settings.READ_ONLY_GROUPS)
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
@group_required_ldap(settings.READ_ONLY_GROUPS)
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
@group_required_ldap(settings.ADMIN_ONLY_GROUPS)
def host_purge_confirmation(request):
    """Show delete confirmation for a host."""
    if request.method != "POST":
        return render(
            request,
            settings.ERROR_HTML,
            {
                "results": ["Invalid request method", settings.TRY_AGAIN],
                "back_url": "/encompass/hosts",
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
                "back_url": "/encompass/hosts",
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
@group_required_ldap(settings.ADMIN_ONLY_GROUPS)
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
        commit_actor = user_helpers.get_user_commit_info(request.user)
        tools.delete_host(hostname, actor=commit_actor)
        messages.success(request, f"Host '{hostname}' deleted successfully!")
    except tools.EncapsuleTriggerError as sync_error:
        logger.warning(
            "Host delete completed but enCapsule sync failed for '%s': %s",
            hostname,
            sync_error,
        )
        messages.warning(request, settings.ENCAPSULE_SYNC_WARNING_MESSAGE)
        return redirect("/encompass/hosts")
    except tools.enc_data.EncDataLockTimeout:
        return render(
            request,
            settings.ERROR_HTML,
            {
                "results": [
                    "Another host update is in progress. Please retry.",
                    settings.TRY_AGAIN,
                ],
                "back_url": "/encompass/hosts",
                "current_version": settings.CURRENT_VERSION,
            },
        )
    except Exception as e:  # pylint: disable=broad-except
        return render(
            request,
            settings.ERROR_HTML,
            {
                "results": [str(e), settings.TRY_AGAIN],
                "back_url": "/encompass/hosts",
                "current_version": settings.CURRENT_VERSION,
            },
        )

    return redirect("/encompass/hosts")


@login_required(login_url="/encompass/login/")
@group_required_ldap(settings.ADMIN_ONLY_GROUPS)
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
        commit_actor = user_helpers.get_user_commit_info(request.user)
        tools.update_host(hostname, host_payload, actor=commit_actor)
    except tools.EncapsuleTriggerError as sync_error:
        logger.warning(
            "Host save completed but enCapsule sync failed for '%s': %s",
            hostname,
            sync_error,
        )
        return JsonResponse(
            {
                "status": "ok",
                "warning": f"{settings.ENCAPSULE_SYNC_WARNING_MESSAGE} Details: {str(sync_error)}",
            }
        )
    except tools.enc_data.EncDataLockTimeout:
        return JsonResponse(
            {"error": "Conflict", "message": "Another host update is in progress"},
            status=409,
        )
    except Exception as e:  # pylint: disable=broad-except
        logger.exception("host_save failed for host '%s'", hostname)
        return JsonResponse({"error": str(e)}, status=500)

    sync_result = tools.get_last_sync_result()
    if sync_result.get("state") == "async" and tools.encapsule_sync_enabled():
        return JsonResponse(
            {
                "status": "ok",
                "warning": settings.ENCAPSULE_ASYNC_INFO_MESSAGE,
            }
        )
    if sync_result.get("state") == "no_changes":
        return JsonResponse(
            {
                "status": "ok",
                "warning": settings.NO_CHANGES_INFO_MESSAGE,
            }
        )

    if tools.sync_runs_async() and tools.encapsule_sync_enabled():
        return JsonResponse(
            {
                "status": "ok",
                "warning": settings.ENCAPSULE_ASYNC_INFO_MESSAGE,
            }
        )

    return JsonResponse({"status": "ok"})


@login_required(login_url="/encompass/login/")
@group_required_ldap(settings.ADMIN_ONLY_GROUPS)
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
        commit_actor = user_helpers.get_user_commit_info(request.user)
        tools.create_host(hostname, host_payload, actor=commit_actor)
        messages.success(request, f"Host '{hostname}' created successfully!")
    except tools.EncapsuleTriggerError as sync_error:
        logger.warning(
            "Host create completed but enCapsule sync failed for '%s': %s",
            hostname,
            sync_error,
        )
        messages.warning(request, settings.ENCAPSULE_SYNC_WARNING_MESSAGE)
        return redirect("/encompass/hosts")
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
@group_required_ldap(settings.ADMIN_ONLY_GROUPS)
def group_purge_confirmation(request):
    """Show confirmation page for deleting a group."""
    groupname = request.GET.get("name", "").strip()
    if not groupname:
        return render(
            request,
            settings.ERROR_HTML,
            {
                "results": ["No group specified", settings.TRY_AGAIN],
                "back_url": "/encompass/groups",
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
                "results": [
                    f"Failed to retrieve group details: {str(e)}",
                    settings.TRY_AGAIN,
                ],
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
@group_required_ldap(settings.ADMIN_ONLY_GROUPS)
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
        commit_actor = user_helpers.get_user_commit_info(request.user)
        tools.delete_group(groupname, actor=commit_actor)
        messages.success(request, f"Group '{groupname}' deleted successfully!")
    except tools.EncapsuleTriggerError as sync_error:
        logger.warning(
            "Group delete completed but enCapsule sync failed for '%s': %s",
            groupname,
            sync_error,
        )
        messages.warning(request, settings.ENCAPSULE_SYNC_WARNING_MESSAGE)
        return redirect("/encompass/groups")
    except tools.enc_data.EncDataLockTimeout:
        return render(
            request,
            settings.ERROR_HTML,
            {
                "results": [
                    "Another group update is in progress. Please retry.",
                    settings.TRY_AGAIN,
                ],
                "back_url": "/encompass/groups",
                "current_version": settings.CURRENT_VERSION,
            },
        )
    except Exception as e:  # pylint: disable=broad-except
        return render(
            request,
            settings.ERROR_HTML,
            {
                "results": [f"Failed to delete group: {str(e)}", settings.TRY_AGAIN],
                "back_url": "/encompass/groups",
                "current_version": settings.CURRENT_VERSION,
            },
        )

    return redirect("/encompass/groups")


@login_required(login_url="/encompass/login/")
@group_required_ldap(settings.ADMIN_ONLY_GROUPS)
def group_save(request):
    """
    Save a group definition via ENC.
    """
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
    if groupname == "default":
        group_payload["hosts"] = []

    try:
        logger.info(
            "Calling update_group for '%s' with payload: %s", groupname, group_payload
        )
        commit_actor = user_helpers.get_user_commit_info(request.user)
        tools.update_group(groupname, group_payload, actor=commit_actor)
        logger.info("Successfully updated group '%s'", groupname)
    except tools.EncapsuleTriggerError as sync_error:
        logger.warning(
            "Group save completed but enCapsule sync failed for '%s': %s",
            groupname,
            sync_error,
        )
        return JsonResponse(
            {
                "status": "ok",
                "warning": f"{settings.ENCAPSULE_SYNC_WARNING_MESSAGE} Details: {str(sync_error)}",
            }
        )
    except tools.enc_data.EncDataLockTimeout:
        return JsonResponse(
            {"error": "Conflict", "message": "Another group update is in progress"},
            status=409,
        )
    except ValueError as e:
        logger.warning("Group validation failed for '%s': %s", groupname, e)
        return JsonResponse({"error": str(e)}, status=400)
    except Exception as e:  # pylint: disable=broad-except
        logger.error("Error updating group '%s': %s", groupname, e, exc_info=True)
        return JsonResponse({"error": str(e)}, status=500)

    sync_result = tools.get_last_sync_result()
    if sync_result.get("state") == "async" and tools.encapsule_sync_enabled():
        return JsonResponse(
            {
                "status": "ok",
                "warning": settings.ENCAPSULE_ASYNC_INFO_MESSAGE,
            }
        )
    if sync_result.get("state") == "no_changes":
        return JsonResponse(
            {
                "status": "ok",
                "warning": settings.NO_CHANGES_INFO_MESSAGE,
            }
        )

    if tools.sync_runs_async() and tools.encapsule_sync_enabled():
        return JsonResponse(
            {
                "status": "ok",
                "warning": settings.ENCAPSULE_ASYNC_INFO_MESSAGE,
            }
        )

    return JsonResponse({"status": "ok"})


@login_required(login_url="/encompass/login/")
@group_required_ldap(settings.ADMIN_ONLY_GROUPS)
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

    # Validate that at least one host selector is provided for non-default groups
    if groupname != "default" and not hosts:
        return render(
            request,
            settings.ERROR_HTML,
            {
                "results": [
                    "At least one host selector is required for non-default groups",
                    settings.TRY_AGAIN,
                ],
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
        "hosts": [] if groupname == "default" else hosts,
        "parameters": parameters,
    }

    try:
        commit_actor = user_helpers.get_user_commit_info(request.user)
        tools.create_group(groupname, group_payload, actor=commit_actor)
        messages.success(request, f"Group '{groupname}' created successfully!")
    except ValueError as e:
        return render(
            request,
            settings.ERROR_HTML,
            {
                "results": [str(e), settings.TRY_AGAIN],
                "current_version": settings.CURRENT_VERSION,
            },
        )
    except tools.EncapsuleTriggerError as sync_error:
        logger.warning(
            "Group create completed but enCapsule sync failed for '%s': %s",
            groupname,
            sync_error,
        )
        messages.warning(request, settings.ENCAPSULE_SYNC_WARNING_MESSAGE)
        return redirect("/encompass/groups")
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


def markdown_page(request, markdown_file, markdown_variant="default"):
    """
    Render the help page by reading content from help.md, converting it to HTML.
    :param request: Django HttpRequest object
    :param markdown_file: Name of the markdown file to render
    :return: Rendered help page with content from the specified markdown file
    """
    identity = get_user_identity(request.user)
    group_name = tools.get_groups_info(identity["groups"])

    with open(f"templates/{markdown_file}", encoding="utf-8") as f:
        content = f.read()

    html = markdown.markdown(content, extensions=["fenced_code", "tables", "toc"])
    html = _rewrite_relative_markdown_image_src(html)
    context = {
        "encompass_email": identity["email"],
        "group_name": group_name,
        "disp_name": identity["display_name"],
        "watermark": settings.WATERMARK,
        "current_version": settings.CURRENT_VERSION,
        "content": html,
        "markdown_variant": markdown_variant,
    }

    return render(request, "markdown.html", context)


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
@group_required_ldap(settings.READ_ONLY_GROUPS)
def home_page(request):
    """List available groups."""
    identity = get_user_identity(request.user)
    groups = identity["groups"]
    group_name = tools.get_groups_info(groups)
    is_db_auth = getattr(settings, "USE_AUTH_MYSQL", False)
    is_ldap_auth = getattr(settings, "USE_AUTH_LDAP", False)
    is_admin = _user_in_any_group(groups, [settings.ENC_ADMIN_GROUP])
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
        "is_ldap_auth": is_ldap_auth,
        "is_admin": is_admin,
        "feature_branch": settings.FEATURE_BRANCH,
        "encapsule_sync_enabled": tools.encapsule_sync_enabled(),
    }

    return render(request, "home.html", context)


@login_required(login_url="/encompass/login/")
@group_required_ldap(settings.READ_ONLY_GROUPS)
def feature_branches_page(request):
    """List non-predefined environments and where they are used."""
    identity = get_user_identity(request.user)
    groups = identity["groups"]
    group_name = tools.get_groups_info(groups)

    usage = []
    if settings.FEATURE_BRANCH:
        usage = tools.list_nonstandard_environment_usage()

    context = {
        "groups": groups,
        "encompass_email": identity["email"],
        "disp_name": identity["display_name"],
        "group_name": group_name,
        "watermark": settings.WATERMARK,
        "current_version": settings.CURRENT_VERSION,
        "feature_branch": settings.FEATURE_BRANCH,
        "predefined_environments": settings.PUPPET_ENVIRONMENTS,
        "custom_environment_usage": usage,
    }
    return render(request, "feature_branches.html", context)


@login_required(login_url="/encompass/login/")
@group_required_ldap(settings.ADMIN_ONLY_GROUPS)
def encapsule_sync_now(request):
    """Manually trigger enCapsule synchronization from the UI."""
    if request.method != "POST":
        return JsonResponse({"error": "Invalid request method"}, status=405)

    if not tools.encapsule_sync_enabled():
        messages.info(
            request, "enCapsule synchronization is disabled by configuration."
        )
        return redirect("/encompass/")

    try:
        tools.trigger_encapsule_sync_now()
        messages.success(request, "Sync with enCapsule completed successfully.")
    except tools.EncSyncError as err:
        logger.warning("Manual enCapsule sync failed: %s", err)
        messages.warning(request, f"Sync with enCapsule failed: {str(err)}")

    return redirect("/encompass/")


@login_required(login_url="/encompass/login/")
@group_required_ldap(settings.READ_ONLY_GROUPS)
def host_list(request):
    """List hosts for health check."""
    identity = get_user_identity(request.user)
    groups = identity["groups"]
    group_name = tools.get_groups_info(groups)
    is_db_auth = getattr(settings, "USE_AUTH_MYSQL", False)
    can_save_hosts = request.user.is_superuser or _user_in_any_group(
        groups, [settings.ENC_ADMIN_GROUP]
    )
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
@group_required_ldap(settings.READ_ONLY_GROUPS)
def group_list(request):
    """List groups for health check."""
    identity = get_user_identity(request.user)
    groups = identity["groups"]
    group_name = tools.get_groups_info(groups)
    is_db_auth = getattr(settings, "USE_AUTH_MYSQL", False)
    can_save_groups = request.user.is_superuser or _user_in_any_group(
        groups, [settings.ENC_ADMIN_GROUP]
    )
    if is_db_auth and not request.user.is_superuser:
        can_save_groups = can_save_groups and request.user.get_username() == "admin"
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
        "can_save_groups": can_save_groups,
    }

    return render(request, "groups.html", context)


@login_required(login_url="/encompass/login/")
@group_required_ldap(settings.READ_ONLY_GROUPS)
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
            hosts = tools.enc_data.load_map("hosts")
            groups_map = tools.enc_data.load_map("groups")
            resolution = tools.enc_data.resolve_host_with_source(
                hosts, groups_map, hostname
            )
            host_data = resolution.get("data")
            if host_data is None:
                context["error"] = f"Host '{hostname}' not found in ENC"
                context["hostname"] = hostname
                return render(request, "query_host.html", context)

            # Convert back to YAML for display (pretty printed)
            yaml_output = yaml.dump(
                host_data, default_flow_style=False, sort_keys=False
            )

            context["hostname"] = hostname
            context["yaml_output"] = yaml_output
            context["host_data"] = host_data
            context["is_default_fallback"] = bool(
                resolution.get("is_default_fallback")
            )
            context["classification_source"] = str(
                resolution.get("source", "unknown")
            )

        except Exception as e:  # pylint: disable=broad-except
            logger.exception("Error querying host '%s'", hostname)
            context["error"] = f"Failed to query host: {str(e)}"
            context["hostname"] = hostname

    return render(request, "query_host.html", context)


@login_required(login_url="/encompass/login/")
@group_required_ldap(settings.READ_ONLY_GROUPS)
def unclassified_hosts_page(request):
    """Show PuppetDB nodes classified with the ENC default profile."""
    identity = get_user_identity(request.user)
    groups = identity["groups"]
    group_name = tools.get_groups_info(groups)

    page_str = request.GET.get("page", "1")
    try:
        page_number = int(page_str)
    except ValueError:
        page_number = 1

    context = {
        "encompass_email": identity["email"],
        "group_name": group_name,
        "disp_name": identity["display_name"],
        "watermark": settings.WATERMARK,
        "current_version": settings.CURRENT_VERSION,
        "unclassified_hosts_enabled": settings.UNCLASSIFIED_HOSTS_ENABLED,
    }

    if not settings.UNCLASSIFIED_HOSTS_ENABLED:
        return render(request, "unclassified_hosts.html", context)

    try:
        result = tools.list_unclassified_hosts()
    except Exception as e:  # pylint: disable=broad-except
        logger.exception("Failed to list unclassified hosts")
        context["error"] = f"Failed to load unclassified hosts: {str(e)}"
        return render(request, "unclassified_hosts.html", context)

    per_page = 50
    paginator = Paginator(result["unclassified"], per_page)
    page_obj = paginator.get_page(page_number)

    context.update(
        {
            "puppetdb_url": result["puppetdb_url"],
            "total_nodes": len(result["nodes"]),
            "unclassified_total": len(result["unclassified"]),
            "unclassified_hosts": page_obj.object_list,
            "page": page_obj.number,
            "total_pages": paginator.num_pages or 1,
            "has_previous": page_obj.has_previous(),
            "has_next": page_obj.has_next(),
            "previous_page": (
                page_obj.previous_page_number() if page_obj.has_previous() else 1
            ),
            "next_page": (
                page_obj.next_page_number()
                if page_obj.has_next()
                else paginator.num_pages
            ),
        }
    )
    return render(request, "unclassified_hosts.html", context)


@login_required(login_url="/encompass/login/")
@group_required_ldap(settings.READ_ONLY_GROUPS)
def spring_cleaning_page(request):
    """Show orphan hosts/groups report based on current PuppetDB nodes."""
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

    try:
        puppetdb_nodes = spring_cleaning.get_puppetdb_nodes()
        orphan_hosts = spring_cleaning.discover_orphan_hosts(puppetdb_nodes)
        orphan_groups_data = spring_cleaning.discover_orphan_groups(puppetdb_nodes)
    except spring_cleaning.EncSyncError as err:
        logger.exception("Failed to build spring cleaning report")
        context["error"] = f"Failed to load spring cleaning report: {str(err)}"
        return render(request, "spring_cleaning.html", context)
    except Exception as err:  # pylint: disable=broad-except
        logger.exception("Unexpected spring cleaning failure")
        context["error"] = f"Failed to load spring cleaning report: {str(err)}"
        return render(request, "spring_cleaning.html", context)

    context.update(
        {
            "puppetdb_nodes_total": len(puppetdb_nodes),
            "orphan_hosts": orphan_hosts,
            "orphan_hosts_total": len(orphan_hosts),
            "orphan_groups": orphan_groups_data["orphan_groups"],
            "orphan_groups_total": len(orphan_groups_data["orphan_groups"]),
            "never_matching_groups": orphan_groups_data["never_matching_groups"],
            "never_matching_groups_total": len(
                orphan_groups_data["never_matching_groups"]
            ),
            "shadowed_groups": orphan_groups_data["shadowed_groups"],
            "shadowed_groups_total": len(orphan_groups_data["shadowed_groups"]),
        }
    )

    return render(request, "spring_cleaning.html", context)


@login_required(login_url="/encompass/login/")
@group_required_ldap(settings.READ_ONLY_GROUPS)
def git_log_page(request):
    """Show paginated `git log -p` output from the ENC repository."""
    identity = get_user_identity(request.user)
    groups = identity["groups"]
    group_name = tools.get_groups_info(groups)

    try:
        page = int(request.GET.get("page", "1"))
    except ValueError:
        page = 1

    context = {
        "encompass_email": identity["email"],
        "group_name": group_name,
        "disp_name": identity["display_name"],
        "watermark": settings.WATERMARK,
        "current_version": settings.CURRENT_VERSION,
        "git_branch": os.environ.get("GIT_BRANCH", "main"),
    }

    try:
        git_log = tools.get_git_log_patch_page(page=page, per_page=1)
    except Exception as e:  # pylint: disable=broad-except
        logger.exception("Failed to load git log page")
        context["error"] = f"Failed to load git log output: {str(e)}"
        return render(request, "git_log.html", context)

    current_page = git_log["page"]
    total_pages = git_log["total_pages"]

    context.update(
        {
            "git_log_output": git_log["output"],
            "total_commits": git_log["total_commits"],
            "page": current_page,
            "total_pages": total_pages,
            "has_previous": current_page > 1,
            "has_next": current_page < total_pages,
            "previous_page": current_page - 1,
            "next_page": current_page + 1,
        }
    )
    return render(request, "git_log.html", context)


@login_required(login_url="/encompass/login/")
def logout_confirmation(request):
    """Show update confirmation."""
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
