"""Encrypted store for CSR challengePassword values."""

from __future__ import annotations

import base64
import hashlib
import logging
import os
import secrets
from contextlib import contextmanager
from pathlib import Path
from threading import RLock

from cryptography.fernet import Fernet
from cryptography.fernet import InvalidToken
from django.db import connection
import yaml


logger = logging.getLogger(__name__)

CSR_DATA_PATH = Path(
    os.environ.get("CSR_CHALLENGE_DATA_PATH", "/data/csr_challenges.yaml")
)
_LOCK_NAME = "encompass:csr:challenges"
_LOCAL_LOCK = RLock()


class CSRChallengeStoreError(Exception):
    """Raised when CSR challenge store operations fail."""


def host_entity_name(hostname: str) -> str:
    """Canonical entity name for host entries."""
    return f"host/{str(hostname).strip()}"


def group_entity_name(groupname: str) -> str:
    """Canonical entity name for group entries."""
    return f"group/{str(groupname).strip()}"


def _load_fernet() -> Fernet:
    """Build a Fernet instance from a dedicated CSR encryption key."""
    raw_key = str(os.environ.get("CSR_CHALLENGE_KEY", "")).strip()
    if not raw_key:
        raise CSRChallengeStoreError("CSR_CHALLENGE_KEY is required")

    try:
        # Accept a raw Fernet key directly when provided.
        return Fernet(raw_key.encode("utf-8"))
    except (ValueError, TypeError):
        # Deterministically derive a valid Fernet key from an arbitrary secret.
        digest = hashlib.sha256(raw_key.encode("utf-8")).digest()
        derived_key = base64.urlsafe_b64encode(digest)
        return Fernet(derived_key)


@contextmanager
def _db_lock(timeout: int = 5):
    """Cross-process lock with local fallback when DB locking is unavailable."""
    using_db_lock = False
    use_local_fallback = False
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT GET_LOCK(%s, %s)", [_LOCK_NAME, timeout])
            acquired = cursor.fetchone()
        if not acquired or acquired[0] != 1:
            raise CSRChallengeStoreError("Timed out acquiring CSR challenge lock")
        using_db_lock = True
    except CSRChallengeStoreError:
        raise
    except Exception as err:  # pylint: disable=broad-except
        logger.warning("Falling back to local CSR lock: %s", err)
        use_local_fallback = True

    if use_local_fallback:
        with _LOCAL_LOCK:
            yield
        return

    try:
        yield
    finally:
        if using_db_lock:
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT RELEASE_LOCK(%s)", [_LOCK_NAME])
            except Exception as err:  # pylint: disable=broad-except
                logger.warning("Failed to release CSR challenge lock: %s", err)


def _load_store() -> dict[str, str]:
    """Load encrypted challenge map from disk."""
    try:
        raw = CSR_DATA_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except OSError as err:
        raise CSRChallengeStoreError(f"Failed to read CSR store: {err}") from err

    try:
        parsed = yaml.safe_load(raw) or {}
    except yaml.YAMLError as err:
        raise CSRChallengeStoreError(f"Failed to parse CSR store: {err}") from err

    if not isinstance(parsed, dict):
        raise CSRChallengeStoreError("CSR store content must be a mapping")

    records = parsed.get("records", parsed)
    if not isinstance(records, dict):
        raise CSRChallengeStoreError("CSR store records must be a mapping")

    normalized = {}
    for key, value in records.items():
        entity = str(key).strip()
        token = str(value).strip()
        if entity and token:
            normalized[entity] = token
    return normalized


def _save_store(records: dict[str, str]) -> None:
    """Persist encrypted challenge map atomically."""
    CSR_DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    temp_path = CSR_DATA_PATH.with_suffix(f"{CSR_DATA_PATH.suffix}.tmp")
    payload = {"records": dict(sorted(records.items()))}
    dumped = yaml.safe_dump(payload, sort_keys=False)
    temp_path.write_text(dumped, encoding="utf-8")
    os.replace(temp_path, CSR_DATA_PATH)


def _encrypt(fernet: Fernet, value: str) -> str:
    return fernet.encrypt(value.encode("utf-8")).decode("utf-8")


def _decrypt(fernet: Fernet, value: str) -> str:
    try:
        return fernet.decrypt(value.encode("utf-8")).decode("utf-8")
    except InvalidToken as err:
        raise CSRChallengeStoreError("Failed to decrypt CSR challenge token") from err


def _new_challenge_password() -> str:
    return secrets.token_urlsafe(24)


def get_or_create(entity_name: str) -> tuple[str, bool]:
    """Return challengePassword for entity, creating one if missing."""
    entity = str(entity_name).strip()
    if not entity:
        raise CSRChallengeStoreError("entity_name is required")

    fernet = _load_fernet()
    with _db_lock():
        store = _load_store()
        encrypted = store.get(entity)
        if encrypted:
            return _decrypt(fernet, encrypted), False

        challenge_password = _new_challenge_password()
        store[entity] = _encrypt(fernet, challenge_password)
        _save_store(store)
        return challenge_password, True


def rotate(entity_name: str) -> str:
    """Rotate challengePassword for one entity and return the plaintext value."""
    entity = str(entity_name).strip()
    if not entity:
        raise CSRChallengeStoreError("entity_name is required")

    fernet = _load_fernet()
    challenge_password = _new_challenge_password()
    with _db_lock():
        store = _load_store()
        store[entity] = _encrypt(fernet, challenge_password)
        _save_store(store)
    return challenge_password


def rotate_many(entity_names: list[str]) -> dict[str, str]:
    """Rotate challengePassword for multiple entities."""
    fernet = _load_fernet()
    entities = [str(name).strip() for name in entity_names if str(name).strip()]
    if not entities:
        return {}

    rotated = {}
    with _db_lock():
        store = _load_store()
        for entity in entities:
            challenge_password = _new_challenge_password()
            store[entity] = _encrypt(fernet, challenge_password)
            rotated[entity] = challenge_password
        _save_store(store)
    return rotated


def delete(entity_name: str) -> bool:
    """Delete challenge entry for an entity."""
    entity = str(entity_name).strip()
    if not entity:
        return False

    with _db_lock():
        store = _load_store()
        if entity not in store:
            return False
        del store[entity]
        _save_store(store)
        return True


def all_entity_names() -> list[str]:
    """Return all known entity names in the CSR store."""
    with _db_lock():
        return sorted(_load_store().keys())
