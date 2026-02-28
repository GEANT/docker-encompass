"""Shared ENC data access helpers for Django views and internal tools."""

from __future__ import annotations

import logging
import os
import re
from contextlib import contextmanager
from pathlib import Path
from threading import RLock

from django.db import connection
import yaml

logger = logging.getLogger(__name__)

ENC_DATA_DIR = Path("/data")
_WRITE_LOCK = RLock()


class EncDataLockTimeout(Exception):
    """Raised when ENC write lock cannot be acquired in time."""


class _EncDumper(yaml.SafeDumper):
    pass


def _represent_none(self, _):
    return self.represent_scalar("tag:yaml.org,2002:null", "")


_EncDumper.add_representer(type(None), _represent_none)


def _data_path(what: str) -> Path:
    if what not in ("hosts", "groups"):
        raise ValueError(f"Unsupported ENC dataset: {what}")
    return ENC_DATA_DIR / f"{what}.yaml"


def _lock_name(what: str) -> str:
    return f"encompass:enc:{what}"


@contextmanager
def data_lock(what: str, timeout: int = 5):
    """
    Acquire a cross-process lock for ENC writes using MySQL advisory locks.
    Falls back to in-process lock only if DB lock operation fails.
    """
    lock_name = _lock_name(what)
    using_db_lock = False
    use_local_fallback = False
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT GET_LOCK(%s, %s)", [lock_name, timeout])
            acquired = cursor.fetchone()
        if acquired and acquired[0] == 1:
            using_db_lock = True
        else:
            raise EncDataLockTimeout(f"Timed out acquiring lock for {what}")
    except EncDataLockTimeout:
        raise
    except Exception as err:  # pylint: disable=broad-except
        logger.warning("Falling back to local lock for '%s': %s", what, err)
        use_local_fallback = True

    if use_local_fallback:
        with _WRITE_LOCK:
            yield
        return

    try:
        yield
    finally:
        if using_db_lock:
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT RELEASE_LOCK(%s)", [lock_name])
            except Exception as err:  # pylint: disable=broad-except
                logger.warning("Failed to release DB lock '%s': %s", lock_name, err)


def load_map(what: str) -> dict:
    """
    Load and parse ENC YAML data for the given dataset (hosts or groups)
    Returns an empty dict on any error (file not found, parse error, etc.)
    """
    path = _data_path(what)
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except OSError as err:
        logger.error("Failed reading YAML file '%s': %s", path, err)
        return {}

    try:
        loaded = yaml.safe_load(raw) or {}
    except yaml.YAMLError as err:
        logger.error("Failed parsing YAML file '%s': %s", path, err)
        return {}

    if not isinstance(loaded, dict):
        logger.error(
            "Ignoring non-mapping YAML in '%s' (type: %s)",
            path,
            type(loaded).__name__,
        )
        return {}

    return loaded


def save_map(what: str, data: dict) -> None:
    """
    Save the given data dict as YAML for the given dataset (hosts or groups).
    The save is done atomically by writing to a temp file and renaming it.
    """
    path = _data_path(what)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(f"{path.suffix}.tmp")
    dumped = yaml.dump(data, Dumper=_EncDumper, sort_keys=False)

    with _WRITE_LOCK:
        temp_path.write_text(dumped, encoding="utf-8")
        os.replace(temp_path, path)


def yaml_response_payload(data):
    """
    Convert the given data dict to a YAML string for HTTP response.
    Returns an empty string if the data is empty.
    """
    if not data:
        return ""
    return yaml.dump(data, Dumper=_EncDumper, sort_keys=False)


def resolve_host(hosts: dict, groups: dict, fqdn: str):
    """
    Resolve a host by its FQDN using the given hosts and groups data.
    Returns the host data if found, otherwise returns None.
    """
    host = hosts.get(fqdn)
    if host:
        return host

    for group_name, group_data in groups.items():
        if group_name == "default":
            continue
        for host_selector in group_data.get("hosts", []):
            selector = str(host_selector).strip()
            if not selector:
                continue

            is_regex_selector = (
                len(selector) >= 2
                and selector.startswith("/")
                and selector.endswith("/")
            )
            if is_regex_selector:
                pattern = selector[1:-1]
                try:
                    is_match = re.fullmatch(pattern, fqdn) is not None
                except re.error as err:
                    raise ValueError(
                        f"Invalid host regex '{selector}' in group '{group_name}': {err}"
                    ) from err
            else:
                is_match = fqdn.startswith(selector)

            if is_match:
                result = group_data.copy()
                result.pop("hosts", None)
                return result

    default_group = groups.get("default")
    if default_group:
        result = default_group.copy()
        result.pop("hosts", None)
        return result

    return None


def normalize_host_payload(payload: dict) -> dict:
    """
    Normalize a host payload by stripping whitespace and removing empty values.
    Returns a dictionary suitable for saving to ENC.
    """
    data = {}
    environment = str(payload.get("environment", "")).strip()
    if environment:
        data["environment"] = environment

    classes = [
        str(item).strip() for item in payload.get("classes", []) if str(item).strip()
    ]
    if classes:
        data["classes"] = classes

    parameters = {
        str(key).strip(): value
        for key, value in (payload.get("parameters", {}) or {}).items()
        if str(key).strip()
    }
    if parameters:
        data["parameters"] = parameters

    return data


def normalize_group_payload(payload: dict) -> dict:
    """
    Normalize a group payload by stripping whitespace and removing empty values.
    Returns a dictionary suitable for saving to ENC.
    """
    data = {}
    environment = str(payload.get("environment", "")).strip()
    if environment:
        data["environment"] = environment

    classes = [
        str(item).strip() for item in payload.get("classes", []) if str(item).strip()
    ]
    if classes:
        data["classes"] = classes

    hosts = [
        str(item).strip() for item in payload.get("hosts", []) if str(item).strip()
    ]
    if hosts:
        data["hosts"] = hosts

    parameters = {
        str(key).strip(): value
        for key, value in (payload.get("parameters", {}) or {}).items()
        if str(key).strip()
    }
    if parameters:
        data["parameters"] = parameters

    return data
