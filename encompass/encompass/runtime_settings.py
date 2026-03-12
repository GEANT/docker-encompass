"""Helpers to read/write runtime settings stored in the database."""

from __future__ import annotations

import json
import os
from typing import Any, Dict, cast
from django.apps import apps
from django.core.exceptions import AppRegistryNotReady
from django.db.utils import OperationalError, ProgrammingError

try:
    import MySQLdb
except Exception:  # pylint: disable=broad-except
    MySQLdb = None  # pylint: disable=invalid-name

DEFAULTS: Dict[str, bool] = {
    "UNCLASSIFIED_HOSTS_ENABLED": str(
        os.environ.get("UNCLASSIFIED_HOSTS_ENABLED", "true")
    )
    .strip()
    .lower()
    in {"1", "true", "yes", "on"},
    "FEATURE_BRANCH": str(os.environ.get("FEATURE_BRANCH", "false")).strip().lower()
    in {"1", "true", "yes", "on"},
    "ENC_OVERLAPPING_DEFINITIONS_ENABLED": str(
        os.environ.get("ENC_OVERLAPPING_DEFINITIONS_ENABLED", "false")
    )
    .strip()
    .lower()
    in {"1", "true", "yes", "on"},
    "USE_ENCAPSULE": str(os.environ.get("USE_ENCAPSULE", "true")).strip().lower()
    in {"1", "true", "yes", "on"},
    "AUTH_LDAP_ENABLED": False,
    "LDAP_TLS_SKIP_VERIFY": False,
}
DEFAULT_PUPPET_ENVIRONMENTS = ["production"]
LDAP_TEXT_DEFAULTS: Dict[str, str] = {
    "LDAP_PROTO": "ldaps",
    "LDAP_PORT": "636",
    "LDAP_SERVER": "ad.example.org",
    "LDAP_PROFILE": "ad",
    "LDAP_GROUPS_BASE_DN": "OU=Groups,OU=IT,OU=EXAMPLE,DC=example,DC=org",
    "LDAP_USER_BASE_DN": "OU=EXAMPLE,OU=Users,OU=EXAMPLE,DC=example,DC=org",
    "LDAP_BIND_DN": "CN=binduser ,OU=EXAMPLE,OU=Users,OU=EXAMPLE,DC=example,DC=org",
    "LDAP_BIND_PASSWORD": "binduser",
    "LDAP_GROUP_RDN_ATTR": "CN",
    "LDAP_USER_SEARCH_FILTER": "",
    "LDAP_GROUP_SEARCH_FILTER": "",
    "LDAP_GROUP_TYPE": "",
    "LDAP_USER_ATTR_MAP": '{"first_name": "givenName", "last_name": "sn", "email": "mail"}',
    "LDAP_PASSWORD_RESET_URL": "",
    "LDAP_PASSWORD_RESET_HELP": "",
}
PUPPETDB_TEXT_DEFAULTS: Dict[str, str] = {
    "PUPPETDB_SCHEMA": "http",
    "PUPPETDB_HOST": "puppetdb.example.org",
    "PUPPETDB_PORT": "8080",
    "PUPPETDB_TIMEOUT": "20",
    "PUPPETDB_AUTH_METHOD": "none",
    "PUPPETDB_AUTH_HEADER": "Authorization",
    "PUPPETDB_AUTH_TOKEN": "",
    "PUPPETDB_BASIC_USERNAME": "",
    "PUPPETDB_BASIC_PASSWORD": "",
    "PUPPETDB_CLIENT_CERT_PATH": "",
    "PUPPETDB_CLIENT_KEY_PATH": "",
    "PUPPETDB_CA_CERT_PATH": "",
    "PUPPETDB_TLS_SKIP_VERIFY": "false",
}
ENCAPSULE_SYNC_TEXT_DEFAULTS: Dict[str, str] = {
    "ENCAPSULE_SYNC_SCHEME": "http",
    "ENCAPSULE_SYNC_TIMEOUT": "5",
    "ENCAPSULE_SYNC_PORT": "8081",
    "ENCAPSULE_SYNC_USE_SRV": "false",
    "ENCAPSULE_SYNC_HOST": "encapsule.example.org",
}


def _runtime_model():
    return apps.get_model("encompass", "RuntimeSetting")


def _mysql_runtime_connection():
    """Open a direct MySQL connection for bootstrap-time reads."""
    if MySQLdb is None:
        return None

    host = str(os.environ.get("MYSQL_HOST", "")).strip()
    user = str(os.environ.get("MYSQL_USER", "")).strip()
    database = str(os.environ.get("MYSQL_DB", "")).strip()
    if not host or not user or not database:
        return None

    password = str(os.environ.get("MYSQL_PASSWORD", ""))
    port_raw = str(os.environ.get("MYSQL_PORT", "3306")).strip()
    try:
        port = int(port_raw)
    except ValueError:
        return None

    try:
        return MySQLdb.connect(  # type: ignore[union-attr]
            host=host,
            user=user,
            passwd=password,
            db=database,
            port=port,
            charset="utf8mb4",
            connect_timeout=2,
        )
    except Exception:  # pylint: disable=broad-except
        return None


def _raw_runtime_value_bool(key: str) -> bool | None:
    """Best-effort runtime bool lookup using raw SQL before app registry is ready."""
    conn = _mysql_runtime_connection()
    if conn is None:
        return None
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT value_bool FROM runtime_settings WHERE `key` = %s LIMIT 1",
                [key],
            )
            row = cursor.fetchone()
    except Exception:  # pylint: disable=broad-except
        return None
    finally:
        try:
            conn.close()
        except Exception:  # pylint: disable=broad-except
            pass
    if row is None or row[0] is None:
        return None
    return bool(row[0])


def _raw_runtime_value_text(key: str) -> str | None:
    """Best-effort runtime text lookup using raw SQL before app registry is ready."""
    conn = _mysql_runtime_connection()
    if conn is None:
        return None
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT value_text FROM runtime_settings WHERE `key` = %s LIMIT 1",
                [key],
            )
            row = cursor.fetchone()
    except Exception:  # pylint: disable=broad-except
        return None
    finally:
        try:
            conn.close()
        except Exception:  # pylint: disable=broad-except
            pass
    if row is None or row[0] is None:
        return None
    return str(row[0]).strip()


def get_bool(key: str, default: bool | None = None) -> bool:
    """Return runtime boolean setting from DB with safe fallback."""
    fallback = DEFAULTS.get(key, False) if default is None else bool(default)
    try:
        runtime_model = cast(Any, _runtime_model())
        item = runtime_model.objects.filter(key=key).only("value_bool").first()
        if item is None:
            return fallback
        return bool(item.value_bool)
    except (OperationalError, ProgrammingError, AppRegistryNotReady, LookupError):
        raw = _raw_runtime_value_bool(key)
        if raw is not None:
            return raw
        return fallback


def set_bool(key: str, value: bool, updated_by: str = "system") -> None:
    """Persist a runtime setting value."""
    runtime_model = cast(Any, _runtime_model())
    runtime_model.objects.update_or_create(
        key=key,
        defaults={
            "value_bool": bool(value),
            "updated_by": updated_by or "system",
        },
    )


def _normalize_list(values: list[str] | tuple[str, ...] | None) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for item in values or []:
        value = str(item).strip()
        if not value:
            continue
        lowered = value.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        normalized.append(value)
    return normalized


def get_list(key: str, default: list[str] | None = None) -> list[str]:
    """Return runtime list setting from DB with safe fallback."""
    fallback = _normalize_list(default or [])
    try:
        runtime_model = cast(Any, _runtime_model())
        item = runtime_model.objects.filter(key=key).only("value_text").first()
        if item is None:
            return fallback
        raw = str(getattr(item, "value_text", "") or "").strip()
        if not raw:
            return fallback
        parsed = json.loads(raw)
        if not isinstance(parsed, list):
            return fallback
        values = _normalize_list(parsed)
        return values or fallback
    except (
        OperationalError,
        ProgrammingError,
        AppRegistryNotReady,
        LookupError,
        json.JSONDecodeError,
    ):
        raw = _raw_runtime_value_text(key)
        if raw:
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    values = _normalize_list(parsed)
                    if values:
                        return values
            except json.JSONDecodeError:
                pass
        return fallback


def set_list(key: str, values: list[str], updated_by: str = "system") -> None:
    """Persist a runtime list setting as JSON text."""
    normalized = _normalize_list(values)
    runtime_model = cast(Any, _runtime_model())
    runtime_model.objects.update_or_create(
        key=key,
        defaults={
            "value_text": json.dumps(normalized),
            "updated_by": updated_by or "system",
        },
    )


def get_text(key: str, default: str | None = None) -> str:
    """Return runtime text setting from DB with safe fallback."""
    fallback = str(default or "").strip()
    value = get_text_raw(key)
    return value or fallback


def get_text_raw(key: str) -> str:
    """Return stored runtime text value without applying fallback defaults."""
    try:
        runtime_model = cast(Any, _runtime_model())
        item = runtime_model.objects.filter(key=key).only("value_text").first()
        if item is None:
            return ""
        value = str(getattr(item, "value_text", "") or "").strip()
        return value
    except (OperationalError, ProgrammingError, AppRegistryNotReady, LookupError):
        raw = _raw_runtime_value_text(key)
        return raw or ""


def set_text(key: str, value: str, updated_by: str = "system") -> None:
    """Persist a runtime text setting."""
    runtime_model = cast(Any, _runtime_model())
    runtime_model.objects.update_or_create(
        key=key,
        defaults={
            "value_text": str(value or "").strip(),
            "updated_by": updated_by or "system",
        },
    )


def feature_branch_enabled() -> bool:
    """Return whether feature branch is enabled."""
    return get_bool("FEATURE_BRANCH")


def unclassified_hosts_enabled() -> bool:
    """Return whether unclassified hosts are enabled."""
    return get_bool("UNCLASSIFIED_HOSTS_ENABLED")


def overlapping_definitions_enabled() -> bool:
    """Return whether overlapping definitions are enabled."""
    return get_bool("ENC_OVERLAPPING_DEFINITIONS_ENABLED")


def encapsule_enabled() -> bool:
    """Return whether enCapsule is enabled."""
    return get_bool("USE_ENCAPSULE")


def ldap_auth_enabled() -> bool:
    """Return whether LDAP authentication is enabled."""
    return get_bool("AUTH_LDAP_ENABLED")


def ldap_tls_skip_verify_enabled() -> bool:
    """Return whether LDAP TLS skip verify is enabled."""
    return get_bool("LDAP_TLS_SKIP_VERIFY")


def puppet_environments() -> list[str]:
    """Return the list of Puppet environments."""
    return get_list("PUPPET_ENVIRONMENTS", DEFAULT_PUPPET_ENVIRONMENTS)


def set_puppet_environments(values: list[str], updated_by: str = "system") -> None:
    """Set the list of Puppet environments."""
    normalized = _normalize_list(values) or DEFAULT_PUPPET_ENVIRONMENTS
    set_list("PUPPET_ENVIRONMENTS", normalized, updated_by=updated_by)
