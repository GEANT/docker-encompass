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
from . import runtime_settings

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


def _is_ldap_authenticated(user) -> bool:
    """Return True when the current user was authenticated through LDAP."""
    if not getattr(settings, "USE_AUTH_LDAP", False):
        return False
    backend = str(getattr(user, "backend", "")).strip()
    return backend == "django_auth_ldap.backend.LDAPBackend"


def get_user_groups(user):
    """Return user groups from local Django group assignments."""
    if not getattr(user, "is_authenticated", False):
        return []

    return list(user.groups.values_list("name", flat=True))


def get_user_identity(user):
    """Return display-friendly user identity fields for templates."""
    if not getattr(user, "is_authenticated", False):
        return {
            "username": settings.UNLOGGED,
            "display_name": settings.UNLOGGED,
            "email": None,
            "groups": [],
        }

    if _is_ldap_authenticated(user):
        attrs = getattr(user.ldap_user, "attrs", None) or {}
        return {
            "username": (
                attrs.get("sAMAccountName", [user.get_username()])[0]
                if isinstance(attrs, dict)
                else user.get_username()
            ),
            "display_name": (
                attrs.get("displayName", [settings.UNLOGGED])[0]
                if isinstance(attrs, dict)
                else user.get_username() or settings.UNLOGGED
            ),
            "email": (
                attrs.get("mail", [None])[0]
                if isinstance(attrs, dict)
                else (user.email or None)
            ),
            "groups": get_user_groups(user),
        }

    if getattr(settings, "USE_AUTH_MYSQL", False):
        groups = get_user_groups(user)
        if user.is_superuser and user.get_username() == "admin":
            groups = list(groups) + ["__local_superuser__"]
        return {
            "username": user.get_username(),
            "display_name": user.get_username() or settings.UNLOGGED,
            "email": user.email or None,
            "groups": groups,
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


def _is_local_shared_admin(user) -> bool:
    """Return True for the built-in shared local DB admin account."""
    if not getattr(settings, "USE_AUTH_MYSQL", False):
        return False
    return str(user.get_username()).strip().lower() == "admin"


def can_modify_enc_definitions(user) -> bool:
    """Allow ENC definition writes only for enc_admin users, excluding shared local admin."""
    if not getattr(user, "is_authenticated", False):
        return False
    if _is_local_shared_admin(user):
        return False
    return _user_in_any_group(get_user_groups(user), [settings.ENC_ADMIN_GROUP])


def _enc_write_forbidden_page(request):
    """Render a consistent forbidden page for ENC write operations."""
    identity = get_user_identity(request.user)
    group_name = tools.get_groups_info(identity["groups"])
    return render(
        request,
        settings.ERROR_HTML,
        {
            "results": [
                "Only enc_admin users can modify hosts and groups definitions",
                "Use a dedicated enc_admin account",
            ],
            "card_header": "Authorization Error",
            "disp_name": identity["display_name"],
            "encompass_email": identity["email"],
            "group_name": group_name,
            "watermark": settings.WATERMARK,
            "current_version": settings.CURRENT_VERSION,
        },
        status=403,
    )


def _enc_write_forbidden_json() -> JsonResponse:
    """Return a JSON forbidden response for ENC write operations."""
    return JsonResponse(
        {
            "error": "Forbidden",
            "message": "Only enc_admin users can modify hosts and groups definitions",
        },
        status=403,
    )


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
    ldap_proto = (
        runtime_settings.get_text(
            "LDAP_PROTO", runtime_settings.LDAP_TEXT_DEFAULTS["LDAP_PROTO"]
        )
        .strip()
        .lower()
    )
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
    auth_backend = str(request.session.get("_auth_user_backend", "")).strip()
    is_ldap_user = auth_backend == "django_auth_ldap.backend.LDAPBackend"

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
        elif not is_ldap_user:
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
        "is_ldap_user": is_ldap_user,
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
        if isinstance(data, dict):
            data = dict(data)
            data["_revision"] = tools.payload_revision(data)
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
        data = dict(data)
        data["_revision"] = tools.payload_revision(data)
        return JsonResponse(data)
    except Exception as e:  # pylint: disable=broad-except
        logger.exception("group_details failed for group '%s'", groupname)
        return JsonResponse({"error": str(e)}, status=500)


@login_required(login_url="/encompass/login/")
@group_required_ldap(settings.ADMIN_ONLY_GROUPS)
def host_purge_confirmation(request):
    """Show delete confirmation for a host."""
    if not can_modify_enc_definitions(request.user):
        return _enc_write_forbidden_page(request)

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
    if not can_modify_enc_definitions(request.user):
        return _enc_write_forbidden_page(request)

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
    if not can_modify_enc_definitions(request.user):
        return _enc_write_forbidden_json()

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
    expected_revision = str(payload.get("expected_revision", "")).strip() or None

    try:
        commit_actor = user_helpers.get_user_commit_info(request.user)
        tools.update_host(
            hostname,
            host_payload,
            actor=commit_actor,
            expected_revision=expected_revision,
        )
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
    except tools.StaleObjectError as stale_error:
        return JsonResponse(
            {
                "error": str(stale_error),
                "message": "Conflict",
            },
            status=409,
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
    if not can_modify_enc_definitions(request.user):
        return _enc_write_forbidden_page(request)

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
            "feature_branch": runtime_settings.feature_branch_enabled(),
            "puppet_environments": runtime_settings.puppet_environments(),
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
    if not can_modify_enc_definitions(request.user):
        return _enc_write_forbidden_page(request)

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
    if not can_modify_enc_definitions(request.user):
        return _enc_write_forbidden_page(request)

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
    if not can_modify_enc_definitions(request.user):
        return _enc_write_forbidden_json()

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
    expected_revision = str(payload.get("expected_revision", "")).strip() or None
    if groupname == "default":
        group_payload["hosts"] = []

    try:
        logger.info(
            "Calling update_group for '%s' with payload: %s", groupname, group_payload
        )
        commit_actor = user_helpers.get_user_commit_info(request.user)
        tools.update_group(
            groupname,
            group_payload,
            actor=commit_actor,
            expected_revision=expected_revision,
        )
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
    except tools.StaleObjectError as stale_error:
        return JsonResponse(
            {
                "error": str(stale_error),
                "message": "Conflict",
            },
            status=409,
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
    if not can_modify_enc_definitions(request.user):
        return _enc_write_forbidden_page(request)

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
            "feature_branch": runtime_settings.feature_branch_enabled(),
            "puppet_environments": runtime_settings.puppet_environments(),
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


def _ldap_settings_sections() -> list[dict]:
    """Return grouped LDAP settings metadata for Global Settings page."""
    defaults = runtime_settings.LDAP_TEXT_DEFAULTS
    return [
        {
            "title": "Connection",
            "fields": [
                {
                    "key": "LDAP_PROFILE",
                    "label": "LDAP Profile",
                    "description": "Supported values: ad, openldap.",
                    "suggestion": defaults["LDAP_PROFILE"],
                    "input_type": "select",
                    "options": ["ad", "openldap"],
                },
                {
                    "key": "LDAP_PROTO",
                    "label": "LDAP Protocol",
                    "description": "Supported values: ldap, ldaps.",
                    "suggestion": defaults["LDAP_PROTO"],
                    "input_type": "select",
                    "options": ["ldap", "ldaps"],
                },
                {
                    "key": "LDAP_SERVER",
                    "label": "LDAP Server",
                    "description": "Directory server hostname or IP.",
                    "suggestion": defaults["LDAP_SERVER"],
                    "input_type": "text",
                },
                {
                    "key": "LDAP_PORT",
                    "label": "LDAP Port",
                    "description": "TCP port for LDAP connection.",
                    "suggestion": defaults["LDAP_PORT"],
                    "input_type": "number",
                },
                {
                    "key": "LDAP_LOGGING",
                    "label": "LDAP Logger Level",
                    "description": "Logger level for django_auth_ldap.",
                    "suggestion": defaults["LDAP_LOGGING"],
                    "input_type": "select",
                    "options": ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
                },
            ],
        },
        {
            "title": "Search Base DNs",
            "fields": [
                {
                    "key": "LDAP_GROUPS_BASE_DN",
                    "label": "LDAP Groups Base DN",
                    "description": "Base DN used for LDAP group search.",
                    "suggestion": defaults["LDAP_GROUPS_BASE_DN"],
                    "input_type": "text",
                },
                {
                    "key": "LDAP_USER_BASE_DN",
                    "label": "LDAP User Base DN",
                    "description": "Base DN used for LDAP user search.",
                    "suggestion": defaults["LDAP_USER_BASE_DN"],
                    "input_type": "text",
                },
            ],
        },
        {
            "title": "Bind and Mapping",
            "fields": [
                {
                    "key": "LDAP_BIND_DN",
                    "label": "LDAP Bind DN",
                    "description": "Bind DN used by service account.",
                    "suggestion": defaults["LDAP_BIND_DN"],
                    "input_type": "text",
                },
                {
                    "key": "LDAP_BIND_PASSWORD",
                    "label": "LDAP Bind Password",
                    "description": "Password for LDAP bind DN.",
                    "suggestion": defaults["LDAP_BIND_PASSWORD"],
                    "input_type": "password",
                },
                {
                    "key": "LDAP_GROUP_RDN_ATTR",
                    "label": "LDAP Group RDN Attribute",
                    "description": "Typically CN for AD, cn for OpenLDAP.",
                    "suggestion": defaults["LDAP_GROUP_RDN_ATTR"],
                    "input_type": "text",
                },
                {
                    "key": "LDAP_USER_ATTR_MAP",
                    "label": "LDAP User Attribute Map",
                    "description": "JSON object mapping local fields to LDAP attributes.",
                    "suggestion": defaults["LDAP_USER_ATTR_MAP"],
                    "input_type": "text",
                },
            ],
        },
        {
            "title": "Search Filters and Group Type",
            "fields": [
                {
                    "key": "LDAP_USER_SEARCH_FILTER",
                    "label": "LDAP User Search Filter",
                    "description": "Optional LDAP user filter; leave empty for profile default.",
                    "suggestion": defaults["LDAP_USER_SEARCH_FILTER"],
                    "input_type": "text",
                },
                {
                    "key": "LDAP_GROUP_SEARCH_FILTER",
                    "label": "LDAP Group Search Filter",
                    "description": "Optional LDAP group filter; leave empty for profile default.",
                    "suggestion": defaults["LDAP_GROUP_SEARCH_FILTER"],
                    "input_type": "text",
                },
                {
                    "key": "LDAP_GROUP_TYPE",
                    "label": "LDAP Group Type",
                    "description": "Optional override: ad_nested, ad, groupofnames, posix.",
                    "suggestion": defaults["LDAP_GROUP_TYPE"],
                    "input_type": "select",
                    "options": ["", "ad_nested", "ad", "groupofnames", "posix"],
                },
            ],
        },
        {
            "title": "Login Help",
            "fields": [
                {
                    "key": "LDAP_PASSWORD_RESET_URL",
                    "label": "LDAP Password Reset URL",
                    "description": "Optional external reset URL shown on login page.",
                    "suggestion": defaults["LDAP_PASSWORD_RESET_URL"],
                    "input_type": "text",
                },
                {
                    "key": "LDAP_PASSWORD_RESET_HELP",
                    "label": "LDAP Password Reset Help",
                    "description": "Optional fallback help text when URL is not provided.",
                    "suggestion": defaults["LDAP_PASSWORD_RESET_HELP"],
                    "input_type": "text",
                },
            ],
        },
    ]


def _puppetdb_settings_fields() -> list[dict]:
    """Return PuppetDB settings metadata for Global Settings page."""
    defaults = runtime_settings.PUPPETDB_TEXT_DEFAULTS
    return [
        {
            "key": "PUPPETDB_SCHEMA",
            "label": "PuppetDB Schema",
            "description": "Protocol scheme for PuppetDB endpoint.",
            "suggestion": defaults["PUPPETDB_SCHEMA"],
            "input_type": "select",
            "options": ["http", "https"],
        },
        {
            "key": "PUPPETDB_HOST",
            "label": "PuppetDB Host",
            "description": "PuppetDB hostname or IP.",
            "suggestion": defaults["PUPPETDB_HOST"],
            "input_type": "text",
        },
        {
            "key": "PUPPETDB_PORT",
            "label": "PuppetDB Port",
            "description": "TCP port for PuppetDB endpoint.",
            "suggestion": defaults["PUPPETDB_PORT"],
            "input_type": "number",
        },
        {
            "key": "PUPPETDB_TIMEOUT",
            "label": "PuppetDB Timeout",
            "description": "HTTP timeout in seconds for PuppetDB calls.",
            "suggestion": defaults["PUPPETDB_TIMEOUT"],
            "input_type": "number",
        },
        {
            "key": "PUPPETDB_AUTH_METHOD",
            "label": "PuppetDB Auth Method",
            "description": "Authentication mode for PuppetDB endpoint.",
            "suggestion": defaults["PUPPETDB_AUTH_METHOD"],
            "input_type": "select",
            "options": ["none", "token", "basic"],
        },
        {
            "key": "PUPPETDB_AUTH_HEADER",
            "label": "PuppetDB Auth Header",
            "description": "Header name used when Auth Method is token.",
            "suggestion": defaults["PUPPETDB_AUTH_HEADER"],
            "input_type": "text",
        },
        {
            "key": "PUPPETDB_AUTH_TOKEN",
            "label": "PuppetDB Auth Token",
            "description": "Token value sent in the configured auth header.",
            "suggestion": defaults["PUPPETDB_AUTH_TOKEN"],
            "input_type": "password",
        },
        {
            "key": "PUPPETDB_BASIC_USERNAME",
            "label": "PuppetDB Basic Username",
            "description": "Username used when Auth Method is basic.",
            "suggestion": defaults["PUPPETDB_BASIC_USERNAME"],
            "input_type": "text",
        },
        {
            "key": "PUPPETDB_BASIC_PASSWORD",
            "label": "PuppetDB Basic Password",
            "description": "Password used when Auth Method is basic.",
            "suggestion": defaults["PUPPETDB_BASIC_PASSWORD"],
            "input_type": "password",
        },
        {
            "key": "PUPPETDB_CLIENT_CERT_PATH",
            "label": "PuppetDB Client Certificate Path",
            "description": "Optional file path to client certificate for mTLS.",
            "suggestion": defaults["PUPPETDB_CLIENT_CERT_PATH"],
            "input_type": "text",
        },
        {
            "key": "PUPPETDB_CLIENT_KEY_PATH",
            "label": "PuppetDB Client Key Path",
            "description": "Optional file path to client key for mTLS.",
            "suggestion": defaults["PUPPETDB_CLIENT_KEY_PATH"],
            "input_type": "text",
        },
        {
            "key": "PUPPETDB_CA_CERT_PATH",
            "label": "PuppetDB CA Certificate Path",
            "description": "Optional CA bundle path used for TLS verification.",
            "suggestion": defaults["PUPPETDB_CA_CERT_PATH"],
            "input_type": "text",
        },
        {
            "key": "PUPPETDB_TLS_SKIP_VERIFY",
            "label": "Skip PuppetDB TLS Certificate Verification",
            "description": "Allow untrusted PuppetDB server certificates (not recommended).",
            "suggestion": defaults["PUPPETDB_TLS_SKIP_VERIFY"],
            "input_type": "select",
            "options": ["false", "true"],
        },
    ]


def _encapsule_sync_settings_fields() -> list[dict]:
    """Return enCapsule sync settings metadata for Global Settings page."""
    defaults = runtime_settings.ENCAPSULE_SYNC_TEXT_DEFAULTS
    return [
        {
            "key": "ENCAPSULE_SYNC_SCHEME",
            "label": "Sync Scheme",
            "description": "Protocol for enCapsule sync endpoints.",
            "suggestion": defaults["ENCAPSULE_SYNC_SCHEME"],
            "input_type": "select",
            "options": ["http", "https"],
        },
        {
            "key": "ENCAPSULE_SYNC_TIMEOUT",
            "label": "Sync Timeout",
            "description": "Curl timeout in seconds for each sync target.",
            "suggestion": defaults["ENCAPSULE_SYNC_TIMEOUT"],
            "input_type": "number",
        },
        {
            "key": "ENCAPSULE_SYNC_PORT",
            "label": "Sync Port",
            "description": "Default target port when host entries omit a port (ignored when Use SRV Targets is true).",  # pylint: disable=line-too-long
            "suggestion": defaults["ENCAPSULE_SYNC_PORT"],
            "input_type": "number",
        },
        {
            "key": "ENCAPSULE_SYNC_USE_SRV",
            "label": "Use SRV Targets",
            "description": "Use SRV discovery for host entries (true/false).",
            "suggestion": defaults["ENCAPSULE_SYNC_USE_SRV"],
            "input_type": "select",
            "options": ["false", "true"],
        },
        {
            "key": "ENCAPSULE_SYNC_HOST",
            "label": "Sync Hosts",
            "description": "Comma-separated targets. Supports multiple hosts (e.g. enc1.example.org,enc2.example.org:9092); use SRV names when Use SRV is true.",  # pylint: disable=line-too-long
            "suggestion": defaults["ENCAPSULE_SYNC_HOST"],
            "input_type": "text",
        },
    ]


def _git_sync_settings_fields() -> list[dict]:
    """Return Git sync settings metadata for Global Settings page."""
    defaults = runtime_settings.GIT_SYNC_TEXT_DEFAULTS
    return [
        {
            "key": "GIT_SYNC_MODE",
            "label": "Git Sync Mode",
            "description": "Run git/sync writes synchronously or asynchronously.",
            "suggestion": defaults["GIT_SYNC_MODE"],
            "input_type": "select",
            "options": ["sync", "async"],
        },
        {
            "key": "GIT_SYNC_TIMEOUT",
            "label": "Git Sync Timeout",
            "description": "Timeout in seconds for each git/sync command.",
            "suggestion": defaults["GIT_SYNC_TIMEOUT"],
            "input_type": "number",
        },
        {
            "key": "GIT_SYNC_RETRIES",
            "label": "Git Sync Retries",
            "description": "Number of retries after an initial failed sync attempt.",
            "suggestion": defaults["GIT_SYNC_RETRIES"],
            "input_type": "number",
        },
        {
            "key": "GIT_SYNC_RETRY_DELAY",
            "label": "Git Sync Retry Delay",
            "description": "Delay in seconds between sync retries.",
            "suggestion": defaults["GIT_SYNC_RETRY_DELAY"],
            "input_type": "number",
        },
    ]


def _validate_ldap_settings(values: dict[str, str]) -> list[str]:
    """Validate LDAP text settings submitted via Global Settings."""
    errors: list[str] = []

    profile = str(values.get("LDAP_PROFILE", "")).strip().lower()
    if profile and profile not in {"ad", "openldap"}:
        errors.append("LDAP Profile must be 'ad' or 'openldap'.")

    proto = str(values.get("LDAP_PROTO", "")).strip().lower()
    if proto and proto not in {"ldap", "ldaps"}:
        errors.append("LDAP Protocol must be 'ldap' or 'ldaps'.")

    ldap_logging = str(values.get("LDAP_LOGGING", "")).strip().upper()
    if ldap_logging and ldap_logging not in {
        "DEBUG",
        "INFO",
        "WARNING",
        "ERROR",
        "CRITICAL",
    }:
        errors.append(
            "LDAP Logger Level must be one of: DEBUG, INFO, WARNING, ERROR, CRITICAL."
        )

    port = str(values.get("LDAP_PORT", "")).strip()
    if port:
        if not port.isdigit():
            errors.append("LDAP Port must be a numeric value.")
        else:
            port_value = int(port)
            if port_value < 1 or port_value > 65535:
                errors.append("LDAP Port must be between 1 and 65535.")

    group_type = str(values.get("LDAP_GROUP_TYPE", "")).strip().lower()
    if group_type and group_type not in {"ad_nested", "ad", "groupofnames", "posix"}:
        errors.append(
            "LDAP Group Type must be one of: ad_nested, ad, groupofnames, posix."
        )

    attr_map_raw = str(values.get("LDAP_USER_ATTR_MAP", "")).strip()
    if attr_map_raw:
        try:
            attr_map = json.loads(attr_map_raw)
            if not isinstance(attr_map, dict):
                errors.append("LDAP User Attribute Map must be a JSON object.")
        except json.JSONDecodeError:
            errors.append("LDAP User Attribute Map must be valid JSON.")

    return errors


def _validate_puppetdb_settings(values: dict[str, str]) -> list[str]:
    """Validate PuppetDB settings submitted via Global Settings."""
    return tools.validate_puppetdb_settings(values)


def _validate_encapsule_sync_settings(values: dict[str, str]) -> list[str]:
    """Validate enCapsule sync settings submitted via Global Settings."""
    errors: list[str] = []

    scheme = str(values.get("ENCAPSULE_SYNC_SCHEME", "")).strip().lower()
    if not scheme:
        errors.append("Sync Scheme cannot be empty.")
    elif scheme not in {"http", "https"}:
        errors.append("Sync Scheme must be 'http' or 'https'.")

    timeout = str(values.get("ENCAPSULE_SYNC_TIMEOUT", "")).strip()
    if not timeout:
        errors.append("Sync Timeout cannot be empty.")
    elif not timeout.isdigit():
        errors.append("Sync Timeout must be numeric.")
    else:
        timeout_value = int(timeout)
        if timeout_value < 1 or timeout_value > 300:
            errors.append("Sync Timeout must be between 1 and 300 seconds.")

    use_srv = str(values.get("ENCAPSULE_SYNC_USE_SRV", "")).strip().lower()
    if use_srv not in {"true", "false"}:
        errors.append("Use SRV Targets must be 'true' or 'false'.")

    port = str(values.get("ENCAPSULE_SYNC_PORT", "")).strip()
    if use_srv != "true":
        if not port:
            errors.append("Sync Port cannot be empty.")
        elif not port.isdigit():
            errors.append("Sync Port must be numeric.")
        else:
            port_value = int(port)
            if port_value < 1 or port_value > 65535:
                errors.append("Sync Port must be between 1 and 65535.")
    elif port and not port.isdigit():
        errors.append("Sync Port must be numeric when provided.")

    host = str(values.get("ENCAPSULE_SYNC_HOST", "")).strip()
    if not host:
        errors.append("Sync Hosts cannot be empty.")

    return errors


def _validate_git_sync_settings(values: dict[str, str]) -> list[str]:
    """Validate Git sync settings submitted via Global Settings."""
    errors: list[str] = []

    mode = str(values.get("GIT_SYNC_MODE", "")).strip().lower()
    if mode not in {"sync", "async"}:
        errors.append("Git Sync Mode must be 'sync' or 'async'.")

    timeout = str(values.get("GIT_SYNC_TIMEOUT", "")).strip()
    if not timeout:
        errors.append("Git Sync Timeout cannot be empty.")
    elif not timeout.isdigit():
        errors.append("Git Sync Timeout must be numeric.")
    else:
        timeout_value = int(timeout)
        if timeout_value < 1 or timeout_value > 3600:
            errors.append("Git Sync Timeout must be between 1 and 3600 seconds.")

    retries = str(values.get("GIT_SYNC_RETRIES", "")).strip()
    if not retries:
        errors.append("Git Sync Retries cannot be empty.")
    elif not retries.isdigit():
        errors.append("Git Sync Retries must be numeric.")
    else:
        retries_value = int(retries)
        if retries_value < 0 or retries_value > 100:
            errors.append("Git Sync Retries must be between 0 and 100.")

    retry_delay = str(values.get("GIT_SYNC_RETRY_DELAY", "")).strip()
    if not retry_delay:
        errors.append("Git Sync Retry Delay cannot be empty.")
    else:
        try:
            retry_delay_value = float(retry_delay)
            if retry_delay_value < 0 or retry_delay_value > 3600:
                errors.append(
                    "Git Sync Retry Delay must be between 0 and 3600 seconds."
                )
        except (TypeError, ValueError):
            errors.append("Git Sync Retry Delay must be numeric.")

    return errors


def _effective_ldap_values(values: dict[str, str]) -> dict[str, str]:
    """Build effective LDAP values by applying runtime defaults and profile defaults."""
    defaults = runtime_settings.LDAP_TEXT_DEFAULTS

    profile = (
        str(values.get("LDAP_PROFILE", "")).strip().lower()
        or str(defaults["LDAP_PROFILE"]).strip().lower()
        or "ad"
    )
    if profile not in {"ad", "openldap"}:
        profile = "ad"

    proto = (
        str(values.get("LDAP_PROTO", "")).strip().lower()
        or str(defaults["LDAP_PROTO"]).strip().lower()
        or "ldaps"
    )
    if proto not in {"ldap", "ldaps"}:
        proto = "ldaps"

    server = str(values.get("LDAP_SERVER", "")).strip() or str(defaults["LDAP_SERVER"])
    port = str(values.get("LDAP_PORT", "")).strip() or str(defaults["LDAP_PORT"])
    bind_dn = str(values.get("LDAP_BIND_DN", "")).strip()
    bind_password = str(values.get("LDAP_BIND_PASSWORD", "")).strip()
    user_base_dn = str(values.get("LDAP_USER_BASE_DN", "")).strip() or str(
        defaults["LDAP_USER_BASE_DN"]
    )
    groups_base_dn = str(values.get("LDAP_GROUPS_BASE_DN", "")).strip() or str(
        defaults["LDAP_GROUPS_BASE_DN"]
    )
    user_filter = str(values.get("LDAP_USER_SEARCH_FILTER", "")).strip() or (
        "(sAMAccountName=%(user)s)" if profile == "ad" else "(uid=%(user)s)"
    )
    group_filter = str(values.get("LDAP_GROUP_SEARCH_FILTER", "")).strip() or (
        "(objectClass=group)" if profile == "ad" else "(objectClass=groupOfNames)"
    )

    return {
        "LDAP_PROFILE": profile,
        "LDAP_PROTO": proto,
        "LDAP_SERVER": server,
        "LDAP_PORT": port,
        "LDAP_BIND_DN": bind_dn,
        "LDAP_BIND_PASSWORD": bind_password,
        "LDAP_USER_BASE_DN": user_base_dn,
        "LDAP_GROUPS_BASE_DN": groups_base_dn,
        "LDAP_USER_SEARCH_FILTER": user_filter,
        "LDAP_GROUP_SEARCH_FILTER": group_filter,
    }


def _test_ldap_settings(
    values: dict[str, str], tls_skip_verify: bool
) -> tuple[bool, list[tuple[str, str]]]:
    """Probe LDAP connectivity and simple searches using submitted (unsaved) values."""
    results: list[tuple[str, str]] = []
    effective = _effective_ldap_values(values)
    ldap_uri = f"{effective['LDAP_PROTO']}://{effective['LDAP_SERVER']}:{effective['LDAP_PORT']}"

    timeout_raw = str(os.environ.get("LDAP_NETWORK_TIMEOUT", "2")).strip()
    try:
        timeout = float(timeout_raw)
    except (TypeError, ValueError):
        timeout = 2.0

    conn = None
    has_error = False

    def _probe_filter(raw_filter: str) -> str:
        """Convert auth template placeholders into safe LDAP probe values."""
        probe = str(raw_filter or "").strip()
        if not probe:
            return "(objectClass=*)"
        return (
            probe.replace("%(user)s", "*")
            .replace("%(group)s", "*")
            .replace("{user}", "*")
            .replace("{group}", "*")
        )

    try:
        conn = ldap.initialize(ldap_uri)
        conn.set_option(LDAP_OPT_PROTOCOL_VERSION, 3)
        conn.set_option(LDAP_OPT_REFERRALS, 0)

        ldap_opt_network_timeout = getattr(ldap, "OPT_NETWORK_TIMEOUT", None)
        if ldap_opt_network_timeout is not None:
            conn.set_option(ldap_opt_network_timeout, timeout)
        ldap_opt_timeout = getattr(ldap, "OPT_TIMEOUT", None)
        if ldap_opt_timeout is not None:
            conn.set_option(ldap_opt_timeout, timeout)

        ldap_opt_x_tls_require_cert = getattr(ldap, "OPT_X_TLS_REQUIRE_CERT", None)
        ldap_opt_x_tls_never = getattr(ldap, "OPT_X_TLS_NEVER", 0)
        ldap_opt_x_tls_demand = getattr(ldap, "OPT_X_TLS_DEMAND", 2)
        ldap_opt_x_tls_newctx = getattr(ldap, "OPT_X_TLS_NEWCTX", None)
        if ldap_opt_x_tls_require_cert is not None:
            conn.set_option(
                ldap_opt_x_tls_require_cert,
                ldap_opt_x_tls_never if tls_skip_verify else ldap_opt_x_tls_demand,
            )
        # Force a fresh TLS context so per-test TLS verification mode is applied.
        if ldap_opt_x_tls_newctx is not None:
            conn.set_option(ldap_opt_x_tls_newctx, 0)

        results.append(("info", f"Connecting to {ldap_uri}"))
        if tls_skip_verify:
            results.append(
                ("warning", "TLS certificate verification is currently disabled.")
            )

        bind_dn = effective["LDAP_BIND_DN"]
        if bind_dn:
            conn.simple_bind_s(bind_dn, effective["LDAP_BIND_PASSWORD"])
            results.append(("success", "Bind succeeded with configured LDAP Bind DN."))
        else:
            conn.simple_bind_s()
            results.append(("success", "Anonymous bind succeeded."))

        scope_subtree = getattr(ldap, "SCOPE_SUBTREE", 2)
        search_checks = [
            (
                "User search",
                effective["LDAP_USER_BASE_DN"],
                _probe_filter(effective["LDAP_USER_SEARCH_FILTER"]),
            ),
            (
                "Group search",
                effective["LDAP_GROUPS_BASE_DN"],
                _probe_filter(effective["LDAP_GROUP_SEARCH_FILTER"]),
            ),
        ]

        for label, base_dn, search_filter in search_checks:
            if not base_dn:
                has_error = True
                results.append(("error", f"{label} failed: base DN is empty."))
                continue

            try:
                found = conn.search_ext_s(
                    base_dn,
                    scope_subtree,
                    search_filter,
                    attrlist=["dn"],
                    timeout=int(timeout),
                    sizelimit=1,
                )
                if found:
                    results.append(("success", f"{label} succeeded."))
                else:
                    results.append(
                        ("warning", f"{label} executed but returned no entries.")
                    )
            except Exception as err:  # pylint: disable=broad-except
                if _is_ldap_exception(err, "SIZELIMIT_EXCEEDED"):
                    results.append(
                        (
                            "warning",
                            f"{label} reached server size limit; search filter/base appears valid.",
                        )
                    )
                    continue

                has_error = True
                detail = _ldap_error_detail(err)
                message = f"{label} failed"
                if detail:
                    message = f"{message}: {detail}"
                results.append(("error", message))

    except Exception as err:  # pylint: disable=broad-except
        has_error = True
        detail = _ldap_error_detail(err)
        message = "LDAP test failed"
        if detail:
            message = f"{message}: {detail}"
        results.append(("error", message))
    finally:
        if conn is not None:
            try:
                conn.unbind_s()
            except Exception:  # pylint: disable=broad-except
                pass

    return (not has_error), results


@login_required(login_url="/encompass/login/")
@group_required_ldap(settings.ADMIN_ONLY_GROUPS)
def global_settings_page(request):
    """View and update global runtime settings."""
    identity = get_user_identity(request.user)
    groups = identity["groups"]
    group_name = tools.get_groups_info(groups)
    is_db_auth = getattr(settings, "USE_AUTH_MYSQL", False)
    is_local_admin = is_db_auth and request.user.get_username() == "admin"

    if not is_local_admin:
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

    managed_keys = [
        "UNCLASSIFIED_HOSTS_ENABLED",
        "FEATURE_BRANCH",
        "ENC_OVERLAPPING_DEFINITIONS_ENABLED",
        "CSR_PASSWORD_DEFAULT_PROFILE_ENABLED",
        "USE_ENCAPSULE",
        "AUTH_LDAP_ENABLED",
        "LDAP_TLS_SKIP_VERIFY",
        "LDAP_MIRROR_GROUPS",
    ]
    ldap_toggle_keys = [
        "AUTH_LDAP_ENABLED",
        "LDAP_TLS_SKIP_VERIFY",
        "LDAP_MIRROR_GROUPS",
    ]
    encapsule_toggle_keys = ["USE_ENCAPSULE"]
    feature_toggle_keys = [
        key
        for key in managed_keys
        if key not in ldap_toggle_keys + encapsule_toggle_keys
    ]
    ldap_sections = _ldap_settings_sections()
    puppetdb_fields = _puppetdb_settings_fields()
    encapsule_sync_fields = _encapsule_sync_settings_fields()
    git_sync_fields = _git_sync_settings_fields()
    puppetdb_keys = [field["key"] for field in puppetdb_fields]
    encapsule_sync_keys = [field["key"] for field in encapsule_sync_fields]
    git_sync_keys = [field["key"] for field in git_sync_fields]
    ldap_keys = [
        field["key"] for section in ldap_sections for field in section["fields"]
    ]
    puppetdb_form_values: dict[str, str] | None = None
    puppetdb_panel_expanded = False
    encapsule_sync_form_values: dict[str, str] | None = None
    encapsule_form_toggles: dict[str, bool] | None = None
    encapsule_panel_expanded = False
    ldap_form_values: dict[str, str] | None = None
    ldap_form_toggles: dict[str, bool] | None = None
    ldap_panel_expanded = False
    git_sync_form_values: dict[str, str] | None = None
    git_sync_panel_expanded = False

    if request.method == "POST":
        if settings.DEMO_MODE:
            messages.error(request, "This feature is unavailable on the demo site")
        else:
            actor = request.user.get_username() or "admin"
            settings_section = (
                str(request.POST.get("settings_section", "all")).strip().lower()
            )
            ldap_values = {
                key: str(request.POST.get(f"ldap_{key}", "")).strip()
                for key in ldap_keys
            }
            puppetdb_values = {
                key: str(request.POST.get(f"puppetdb_{key}", "")).strip()
                for key in puppetdb_keys
            }
            encapsule_sync_values = {
                key: str(request.POST.get(f"encapsule_sync_{key}", "")).strip()
                for key in encapsule_sync_keys
            }
            git_sync_values = {
                key: str(request.POST.get(f"git_sync_{key}", "")).strip()
                for key in git_sync_keys
            }
            is_ldap_test = settings_section in ["ldap", "ldap_test"] and (
                "test_ldap" in request.POST
            )
            is_puppetdb_test = settings_section in ["puppetdb", "all"] and (
                "test_puppetdb" in request.POST
            )

            if is_ldap_test:
                ldap_panel_expanded = True
                ldap_form_values = ldap_values
                ldap_form_toggles = {
                    key: key in request.POST for key in ldap_toggle_keys
                }
                ldap_errors = _validate_ldap_settings(ldap_values)
                if ldap_errors:
                    for error in ldap_errors:
                        messages.error(request, error)
                else:
                    test_ok, test_results = _test_ldap_settings(
                        ldap_values,
                        tls_skip_verify=("LDAP_TLS_SKIP_VERIFY" in request.POST),
                    )
                    for level, text in test_results:
                        if level == "success":
                            messages.success(request, text)
                        elif level == "warning":
                            messages.warning(request, text)
                        elif level == "error":
                            messages.error(request, text)
                        else:
                            messages.info(request, text)

                    if test_ok:
                        messages.success(
                            request,
                            "LDAP test completed. Values look valid; you can now save them.",
                        )
            elif is_puppetdb_test:
                puppetdb_panel_expanded = True
                puppetdb_form_values = puppetdb_values
                puppetdb_errors = _validate_puppetdb_settings(puppetdb_values)
                if puppetdb_errors:
                    for error in puppetdb_errors:
                        messages.error(request, error)
                else:
                    test_ok, test_results = tools.test_puppetdb_settings(
                        puppetdb_values
                    )
                    for level, text in test_results:
                        if level == "success":
                            messages.success(request, text)
                        elif level == "warning":
                            messages.warning(request, text)
                        elif level == "error":
                            messages.error(request, text)
                        else:
                            messages.info(request, text)

                    if test_ok:
                        messages.success(
                            request,
                            "PuppetDB test completed. Values look valid; you can now save them.",
                        )
            else:
                has_errors = False
                if settings_section in ["all", "feature"]:
                    for key in feature_toggle_keys:
                        runtime_settings.set_bool(
                            key, key in request.POST, updated_by=actor
                        )
                    runtime_settings.set_puppet_environments(
                        request.POST.getlist("puppet_environments[]"),
                        updated_by=actor,
                    )

                if settings_section in ["all", "puppetdb"]:
                    puppetdb_panel_expanded = True
                    puppetdb_errors = _validate_puppetdb_settings(puppetdb_values)
                    if puppetdb_errors:
                        has_errors = True
                        puppetdb_form_values = puppetdb_values
                        for error in puppetdb_errors:
                            messages.error(request, error)
                    else:
                        for key, value in puppetdb_values.items():
                            runtime_settings.set_text(key, value, updated_by=actor)

                if settings_section in ["all", "git_sync"]:
                    git_sync_panel_expanded = True
                    git_sync_errors = _validate_git_sync_settings(git_sync_values)
                    if git_sync_errors:
                        has_errors = True
                        git_sync_form_values = git_sync_values
                        for error in git_sync_errors:
                            messages.error(request, error)
                    else:
                        for key, value in git_sync_values.items():
                            runtime_settings.set_text(key, value, updated_by=actor)

                if settings_section in ["all", "ldap"]:
                    ldap_errors = _validate_ldap_settings(ldap_values)
                    if ldap_errors:
                        has_errors = True
                        for error in ldap_errors:
                            messages.error(request, error)
                        return redirect("/encompass/global_settings/")

                    for key in ldap_toggle_keys:
                        runtime_settings.set_bool(
                            key, key in request.POST, updated_by=actor
                        )
                    for key, value in ldap_values.items():
                        runtime_settings.set_text(key, value, updated_by=actor)

                if settings_section in ["all", "encapsule"]:
                    encapsule_panel_expanded = True
                    encapsule_sync_errors = _validate_encapsule_sync_settings(
                        encapsule_sync_values
                    )
                    if encapsule_sync_errors:
                        has_errors = True
                        encapsule_panel_expanded = True
                        encapsule_sync_form_values = encapsule_sync_values
                        encapsule_form_toggles = {
                            key: key in request.POST for key in encapsule_toggle_keys
                        }
                        for error in encapsule_sync_errors:
                            messages.error(request, error)
                    else:
                        for key, value in encapsule_sync_values.items():
                            runtime_settings.set_text(key, value, updated_by=actor)
                        for key in encapsule_toggle_keys:
                            runtime_settings.set_bool(
                                key,
                                key in request.POST,
                                updated_by=actor,
                            )

                if not has_errors:
                    messages.success(request, "Global settings updated")
                    return redirect("/encompass/global_settings/")

    for section in ldap_sections:
        for field in section["fields"]:
            key = field["key"]
            if ldap_form_values is not None:
                field["value"] = ldap_form_values.get(key, "")
            else:
                field["value"] = runtime_settings.get_text(key, field["suggestion"])

    for field in puppetdb_fields:
        key = field["key"]
        if puppetdb_form_values is not None:
            field["value"] = puppetdb_form_values.get(key, "")
        else:
            field["value"] = runtime_settings.get_text_raw(key)

    for field in encapsule_sync_fields:
        key = field["key"]
        if encapsule_sync_form_values is not None:
            field["value"] = encapsule_sync_form_values.get(key, "")
        else:
            field["value"] = runtime_settings.get_text_raw(key)

    for field in git_sync_fields:
        key = field["key"]
        if git_sync_form_values is not None:
            field["value"] = git_sync_form_values.get(key, "")
        else:
            field["value"] = runtime_settings.get_text(key, field["suggestion"])

    toggle_items = [
        {
            "key": "UNCLASSIFIED_HOSTS_ENABLED",
            "label": "Unclassified Hosts",
            "description": "Enable/disable the unclassified hosts page and logic.",
            "enabled": runtime_settings.unclassified_hosts_enabled(),
        },
        {
            "key": "FEATURE_BRANCH",
            "label": "Feature Branch Mode",
            "description": "Enable custom environment tracking in the UI.",
            "enabled": runtime_settings.feature_branch_enabled(),
        },
        {
            "key": "ENC_OVERLAPPING_DEFINITIONS_ENABLED",
            "label": "Overlapping Definitions",
            "description": "Allow overlapping ENC definitions and merge results.",
            "enabled": runtime_settings.overlapping_definitions_enabled(),
        },
        {
            "key": "CSR_PASSWORD_DEFAULT_PROFILE_ENABLED",
            "label": "Auto-sign Default Profile",
            "description": "Enable/disable auto-signing for the default profile.",
            "enabled": runtime_settings.csr_password_default_profile_enabled(),
        },
    ]

    encapsule_toggle_items = [
        {
            "key": "USE_ENCAPSULE",
            "label": "Use enCapsule",
            "description": "Enable/disable sync fan-out toward enCapsule targets.",
            "enabled": (
                encapsule_form_toggles["USE_ENCAPSULE"]
                if encapsule_form_toggles is not None
                else runtime_settings.encapsule_enabled()
            ),
        },
    ]

    ldap_toggle_items = [
        {
            "key": "AUTH_LDAP_ENABLED",
            "label": "LDAP Authentication",
            "description": "Enable/disable LDAP authentication fallback.",  # pylint: disable=line-too-long
            "enabled": (
                ldap_form_toggles["AUTH_LDAP_ENABLED"]
                if ldap_form_toggles is not None
                else runtime_settings.ldap_auth_enabled()
            ),
        },
        {
            "key": "LDAP_TLS_SKIP_VERIFY",
            "label": "Skip LDAP TLS Certificate Verification",
            "description": "Allow untrusted/self-signed LDAP certificates.",
            "enabled": (
                ldap_form_toggles["LDAP_TLS_SKIP_VERIFY"]
                if ldap_form_toggles is not None
                else runtime_settings.ldap_tls_skip_verify_enabled()
            ),
        },
        {
            "key": "LDAP_MIRROR_GROUPS",
            "label": "Mirror LDAP Groups into Django",
            "description": "Create/update local Django groups from LDAP memberships during login.",
            "enabled": (
                ldap_form_toggles["LDAP_MIRROR_GROUPS"]
                if ldap_form_toggles is not None
                else runtime_settings.ldap_mirror_groups_enabled()
            ),
        },
    ]

    context = {
        "encompass_email": identity["email"],
        "disp_name": identity["display_name"],
        "group_name": group_name,
        "toggle_items": toggle_items,
        "encapsule_toggle_items": encapsule_toggle_items,
        "encapsule_toggle_keys": encapsule_toggle_keys,
        "ldap_toggle_items": ldap_toggle_items,
        "ldap_toggle_keys": ldap_toggle_keys,
        "puppet_environments": runtime_settings.puppet_environments(),
        "puppetdb_fields": puppetdb_fields,
        "git_sync_fields": git_sync_fields,
        "encapsule_sync_fields": encapsule_sync_fields,
        "ldap_sections": ldap_sections,
        "puppetdb_panel_expanded": puppetdb_panel_expanded,
        "git_sync_panel_expanded": git_sync_panel_expanded,
        "encapsule_panel_expanded": encapsule_panel_expanded,
        "ldap_panel_expanded": ldap_panel_expanded,
        "watermark": settings.WATERMARK,
        "current_version": settings.CURRENT_VERSION,
    }
    return render(request, "global_settings.html", context)


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
        "feature_branch": runtime_settings.feature_branch_enabled(),
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
    if runtime_settings.feature_branch_enabled():
        usage = tools.list_nonstandard_environment_usage()

    context = {
        "groups": groups,
        "encompass_email": identity["email"],
        "disp_name": identity["display_name"],
        "group_name": group_name,
        "watermark": settings.WATERMARK,
        "current_version": settings.CURRENT_VERSION,
        "feature_branch": runtime_settings.feature_branch_enabled(),
        "predefined_environments": runtime_settings.puppet_environments(),
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
    can_save_hosts = can_modify_enc_definitions(request.user)
    host_names = tools.list_hosts()
    context = {
        "groups": groups,
        "encompass_email": identity["email"],
        "disp_name": identity["display_name"],
        "group_name": group_name,
        "watermark": settings.WATERMARK,
        "current_version": settings.CURRENT_VERSION,
        "hosts": host_names,
        "feature_branch": runtime_settings.feature_branch_enabled(),
        "puppet_environments": runtime_settings.puppet_environments(),
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
    can_save_groups = can_modify_enc_definitions(request.user)
    groups_list = tools.list_groups()
    context = {
        "groups": groups,
        "encompass_email": identity["email"],
        "disp_name": identity["display_name"],
        "group_name": group_name,
        "watermark": settings.WATERMARK,
        "current_version": settings.CURRENT_VERSION,
        "groups_list": groups_list,
        "feature_branch": runtime_settings.feature_branch_enabled(),
        "puppet_environments": runtime_settings.puppet_environments(),
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
            context["is_default_fallback"] = bool(resolution.get("is_default_fallback"))
            context["classification_source"] = str(resolution.get("source", "unknown"))

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
        "unclassified_hosts_enabled": runtime_settings.unclassified_hosts_enabled(),
    }

    if not runtime_settings.unclassified_hosts_enabled():
        return render(request, "unclassified_hosts.html", context)

    puppetdb_issues = tools.validate_puppetdb_settings()
    if puppetdb_issues:
        context["warning"] = (
            "PuppetDB settings are incomplete or invalid. "
            "Configure PuppetDB Schema, Host, Port, and Timeout in Global Settings."
        )
        context["puppetdb_issues"] = puppetdb_issues
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

    puppetdb_issues = tools.validate_puppetdb_settings()
    if puppetdb_issues:
        context["warning"] = (
            "PuppetDB settings are incomplete or invalid. "
            "Configure PuppetDB Schema, Host, Port, and Timeout in Global Settings."
        )
        context["puppetdb_issues"] = puppetdb_issues
        return render(request, "spring_cleaning.html", context)

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
