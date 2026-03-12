"""Helpers to read/write runtime settings stored in the database."""

from __future__ import annotations

import os
from typing import Any, Dict, cast
from django.apps import apps
from django.core.exceptions import AppRegistryNotReady
from django.db.utils import OperationalError, ProgrammingError

DEFAULTS: Dict[str, bool] = {
    "UNCLASSIFIED_HOSTS_ENABLED": str(
        os.environ.get("UNCLASSIFIED_HOSTS_ENABLED", "true")
    ).strip().lower() in {"1", "true", "yes", "on"},
    "FEATURE_BRANCH": str(os.environ.get("FEATURE_BRANCH", "false")).strip().lower()
    in {"1", "true", "yes", "on"},
    "ENC_OVERLAPPING_DEFINITIONS_ENABLED": str(
        os.environ.get("ENC_OVERLAPPING_DEFINITIONS_ENABLED", "false")
    ).strip().lower()
    in {"1", "true", "yes", "on"},
    "USE_ENCAPSULE": str(os.environ.get("USE_ENCAPSULE", "true")).strip().lower()
    in {"1", "true", "yes", "on"},
    # Runtime toggle for future wiring. Current LDAP backend bootstrap still
    # depends on Django settings initialization.
    "AUTH_LDAP_ENABLED": str(
        os.environ.get("AUTH_LDAP_ENABLED", "false")
    ).strip().lower() in {"1", "true", "yes", "on"},
    "LDAP_TLS_SKIP_VERIFY": str(
        os.environ.get("LDAP_TLS_SKIP_VERIFY", "false")
    ).strip().lower() in {"1", "true", "yes", "on"},
}

def _runtime_model():
    return apps.get_model("encompass", "RuntimeSetting")


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


def feature_branch_enabled() -> bool:
    return get_bool("FEATURE_BRANCH")


def unclassified_hosts_enabled() -> bool:
    return get_bool("UNCLASSIFIED_HOSTS_ENABLED")


def overlapping_definitions_enabled() -> bool:
    return get_bool("ENC_OVERLAPPING_DEFINITIONS_ENABLED")


def encapsule_enabled() -> bool:
    return get_bool("USE_ENCAPSULE")


def ldap_auth_enabled() -> bool:
    return get_bool("AUTH_LDAP_ENABLED")


def ldap_tls_skip_verify_enabled() -> bool:
    return get_bool("LDAP_TLS_SKIP_VERIFY")
