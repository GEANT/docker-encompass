"""
analyzes data received
"""

import logging
import os
import subprocess
import threading
import time
from django.conf import settings
from . import enc_data

logger = logging.getLogger(__name__)

ENC_REPO_DIR = "/data"
_SYNC_STATE_LOCK = threading.Lock()
_SYNC_STATE = {
    "running": False,
    "pending": False,
    "actor": None,
    "action": None,
}


class EncSyncError(Exception):
    """
    Raised when Git sync or enCapsule sync fails after ENC writes.
    """


class EncapsuleTriggerError(EncSyncError):
    """Raised when enCapsule fan-out trigger fails after git push."""


def _env_int(name: str, default: int) -> int:
    """
    Return an integer from environment or default if not set/invalid.
    """
    value = str(os.environ.get(name, default)).strip()
    try:
        return int(value)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    """
    Return a float from environment or default if not set/invalid.
    """
    value = str(os.environ.get(name, default)).strip()
    try:
        return float(value)
    except ValueError:
        return default


def _git_sync_mode() -> str:
    """
    Return git sync mode from environment, defaulting to 'sync' if invalid.
    """
    mode = str(os.environ.get("GIT_SYNC_MODE", "sync")).strip().lower()
    if mode not in {"sync", "async"}:
        return "sync"
    return mode


def _commit_actor(actor: dict | None) -> tuple[str, str, str]:
    """
    Resolve commit actor from request user info, with bot fallback.
    Returns (name, email, 'Name <email>').
    """
    default_name = str(os.environ.get("GIT_COMMIT_NAME", "encompass-bot")).strip()
    default_email = str(os.environ.get("GIT_COMMIT_EMAIL", "encompass@local")).strip()

    if isinstance(actor, dict):
        name = str(actor.get("name") or actor.get("username") or default_name).strip()
        email = str(actor.get("email") or default_email).strip()
    else:
        name = default_name
        email = default_email

    author = f"{name} <{email}>"
    return name, email, author


def _commit_message(action: str | None, author: str) -> str:
    """
    Build commit message with optional action context and actor metadata.
    """
    base_message = str(os.environ.get("GIT_COMMIT_MESSAGE", "ENC data update")).strip()
    if not base_message:
        base_message = "ENC data update"
    if action:
        return f"{base_message}: {action}\n\nActor: {author}"
    return f"{base_message}\n\nActor: {author}"


def _run_checked(command, cwd=None, timeout=None) -> subprocess.CompletedProcess:
    """
    Run command and raise EncSyncError with stderr/stdout on failure.
    """
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as err:
        raise EncSyncError(
            f"Command timed out after {timeout}s: {' '.join(command)}"
        ) from err
    if result.returncode != 0:
        details = (result.stderr or result.stdout or "").strip()
        raise EncSyncError(f"Command failed: {' '.join(command)}; {details}")
    return result


def _sync_git_repo(actor: dict | None = None, action: str | None = None) -> bool:
    """
    Commit and push ENC data if there are staged/unstaged changes.
    """
    timeout = _env_int("GIT_SYNC_TIMEOUT", 30)

    _run_checked(
        ["git", "add", "hosts.yaml", "groups.yaml"], cwd=ENC_REPO_DIR, timeout=timeout
    )

    status = _run_checked(
        ["git", "status", "-s", "--", "hosts.yaml", "groups.yaml"],
        cwd=ENC_REPO_DIR,
        timeout=timeout,
    )
    if not status.stdout.strip():
        return False

    commit_name, commit_email, commit_author = _commit_actor(actor)
    commit_message = _commit_message(action, commit_author)
    branch = os.environ.get("GIT_REPO_BRANCH", "main")

    _run_checked(
        ["git", "config", "user.name", commit_name], cwd=ENC_REPO_DIR, timeout=timeout
    )
    _run_checked(
        ["git", "config", "user.email", commit_email], cwd=ENC_REPO_DIR, timeout=timeout
    )
    _run_checked(
        ["git", "commit", "--author", commit_author, "-m", commit_message],
        cwd=ENC_REPO_DIR,
        timeout=timeout,
    )
    _run_checked(["git", "push", "origin", branch], cwd=ENC_REPO_DIR, timeout=timeout)
    return True


def _trigger_encapsule_sync() -> None:
    """
    Trigger enCapsule sync fan-out unless disabled by USE_ENCAPSULE.
    """
    use_encapsule = str(os.environ.get("USE_ENCAPSULE", "true")).strip().lower()
    if use_encapsule in {"0", "false", "no", "off"}:
        logger.info("USE_ENCAPSULE disabled: skipping enCapsule sync fan-out")
        return

    timeout = _env_int("GIT_SYNC_TIMEOUT", 30)
    try:
        _run_checked(["/usr/local/bin/encapsule-sync.sh"], timeout=timeout)
    except EncSyncError as err:
        raise EncapsuleTriggerError(str(err)) from err


def _sync_once(
    actor: dict | None = None,
    action: str | None = None,
    force_trigger: bool = False,
) -> None:
    """
    Perform a single sync operation: commit/push ENC data and trigger enCapsule sync if needed.
    """
    if force_trigger:
        _trigger_encapsule_sync()
        return

    changed = _sync_git_repo(actor=actor, action=action)
    if changed:
        _trigger_encapsule_sync()


def _sync_with_retries(actor: dict | None = None, action: str | None = None) -> None:
    """
    Perform sync with retries on failure, using environment-configured retry count and delay.
    """
    retries = _env_int("GIT_SYNC_RETRIES", 2)
    delay = _env_float("GIT_SYNC_RETRY_DELAY", 2.0)
    total_attempts = retries + 1
    force_trigger = False

    for attempt in range(total_attempts):
        attempt_num = attempt + 1
        logger.info("ENC sync attempt %s/%s started", attempt_num, total_attempts)
        try:
            _sync_once(actor=actor, action=action, force_trigger=force_trigger)
            if attempt > 0:
                logger.info(
                    "ENC sync attempt %s/%s succeeded after retry",
                    attempt_num,
                    total_attempts,
                )
            return
        except EncSyncError as err:
            if isinstance(err, EncapsuleTriggerError):
                force_trigger = True
            if attempt >= retries:
                logger.error(
                    "ENC sync attempt %s/%s failed permanently: %s",
                    attempt_num,
                    total_attempts,
                    err,
                )
                raise
            logger.warning(
                "ENC sync attempt %s/%s failed: %s; retrying in %.1fs",
                attempt_num,
                total_attempts,
                err,
                delay,
            )
            time.sleep(delay)


def _sync_worker() -> None:
    """
    Background worker function to perform enCapsule sync fan-out with retries.
    """
    while True:
        with _SYNC_STATE_LOCK:
            actor = _SYNC_STATE["actor"]
            action = _SYNC_STATE["action"]
            _SYNC_STATE["pending"] = False
            _SYNC_STATE["actor"] = None
            _SYNC_STATE["action"] = None
        try:
            _sync_with_retries(actor=actor, action=action)
        except EncSyncError:
            logger.exception("Asynchronous ENC sync failed")

        with _SYNC_STATE_LOCK:
            if _SYNC_STATE["pending"]:
                continue
            _SYNC_STATE["running"] = False
            return


def _enqueue_async_sync(actor: dict | None = None, action: str | None = None) -> None:
    """
    Enqueue an asynchronous ENC sync operation if not already running.
    """
    with _SYNC_STATE_LOCK:
        _SYNC_STATE["pending"] = True
        _SYNC_STATE["actor"] = actor
        _SYNC_STATE["action"] = action
        if _SYNC_STATE["running"]:
            return
        _SYNC_STATE["running"] = True

    worker = threading.Thread(target=_sync_worker, name="enc-sync-worker", daemon=True)
    worker.start()


def _sync_after_write(actor: dict | None = None, action: str | None = None) -> None:
    """
    Commit/push YAML changes and trigger enCapsule sync when needed.
    """
    if _git_sync_mode() == "async":
        _enqueue_async_sync(actor=actor, action=action)
        return
    _sync_with_retries(actor=actor, action=action)


def get_host_details(hostname: str) -> dict:
    """
    Get host details from local ENC YAML data, with group/default fallback.
    """
    hosts = enc_data.load_map("hosts")
    groups = enc_data.load_map("groups")
    data = enc_data.resolve_host(hosts, groups, hostname)
    return data


def host_exists(hostname: str) -> bool:
    """
    Check if a host exists in ENC.
    """
    return hostname in enc_data.load_map("hosts")


def delete_host(hostname: str, actor: dict | None = None) -> dict:
    """
    Delete host from ENC.
    """
    with enc_data.data_lock("hosts"):
        hosts = enc_data.load_map("hosts")
        if hostname not in hosts:
            raise Exception(
                f"ENC error for {hostname}: 404"
            )  # pylint: disable=broad-exception-raised
        deleted = hosts[hostname]
        del hosts[hostname]
        enc_data.save_map("hosts", hosts)
    _sync_after_write(actor=actor, action=f"delete host {hostname}")
    return deleted


def update_host(hostname: str, payload: dict, actor: dict | None = None) -> dict:
    """
    Update host in ENC from full payload.
    """
    with enc_data.data_lock("hosts"):
        hosts = enc_data.load_map("hosts")
        if hostname not in hosts:
            raise Exception(
                f"ENC error for {hostname}: 404"
            )  # pylint: disable=broad-exception-raised
        normalized = enc_data.normalize_host_payload(payload)
        hosts[hostname] = normalized
        enc_data.save_map("hosts", hosts)
    _sync_after_write(actor=actor, action=f"update host {hostname}")
    return normalized


def create_host(hostname: str, payload: dict, actor: dict | None = None) -> dict:
    """
    Create new host in ENC.
    """
    with enc_data.data_lock("hosts"):
        hosts = enc_data.load_map("hosts")
        normalized = enc_data.normalize_host_payload(payload)
        hosts[hostname] = normalized
        enc_data.save_map("hosts", hosts)
    _sync_after_write(actor=actor, action=f"create host {hostname}")
    return normalized


def get_file_content(filename):
    """
    Get the content of a file, removing newline characters.
    Returns an empty string if the file does not exist or cannot be read.
    """
    try:
        with open(filename, "r", encoding="utf-8") as wm_file:
            filename_data = wm_file.read().replace("\n", "")
    except FileNotFoundError:
        filename_data = ""

    return filename_data


def get_groups_info(groups: list, return_all: bool = False) -> str | list:
    """
    Get groups information.
    Returns the highest privilege group name.
    Possible return values: admin, viewer, not yet known
    """
    if return_all:
        group_names = []
        if settings.ENC_ADMIN_GROUP in groups:
            group_names.append("admin")
        if settings.ENC_VIEWER_GROUP in groups:
            group_names.append("viewer")

        return group_names

    if settings.ENC_ADMIN_GROUP in groups:
        return "admin"
    if settings.ENC_VIEWER_GROUP in groups:
        return "viewer"

    return "not yet known"


def get_group_details(groupname: str) -> dict:
    """Get group details from ENC."""
    groups = enc_data.load_map("groups")
    if groupname not in groups:
        raise Exception(
            f"ENC error for {groupname}: 404"
        )  # pylint: disable=broad-exception-raised
    return groups[groupname]


def delete_group(groupname: str, actor: dict | None = None) -> dict:
    """Delete group from ENC."""
    with enc_data.data_lock("groups"):
        groups = enc_data.load_map("groups")
        if groupname not in groups:
            raise Exception(
                f"ENC error for {groupname}: 404"
            )  # pylint: disable=broad-exception-raised
        if groupname == "default":
            raise Exception(
                f"ENC error for {groupname}: 403"
            )  # pylint: disable=broad-exception-raised
        deleted = groups[groupname]
        del groups[groupname]
        enc_data.save_map("groups", groups)
    _sync_after_write(actor=actor, action=f"delete group {groupname}")
    return deleted


def update_group(groupname: str, payload: dict, actor: dict | None = None) -> dict:
    """
    Update group in ENC from full payload.
    """
    with enc_data.data_lock("groups"):
        groups = enc_data.load_map("groups")
        if groupname not in groups:
            raise Exception(
                f"ENC error for {groupname}: 404"
            )  # pylint: disable=broad-exception-raised
        normalized = enc_data.normalize_group_payload(payload)
        groups[groupname] = normalized
        enc_data.save_map("groups", groups)
    _sync_after_write(actor=actor, action=f"update group {groupname}")
    return normalized


def create_group(groupname: str, payload: dict, actor: dict | None = None) -> dict:
    """
    Create new group in ENC.
    """
    with enc_data.data_lock("groups"):
        groups = enc_data.load_map("groups")
        normalized = enc_data.normalize_group_payload(payload)
        groups[groupname] = normalized
        enc_data.save_map("groups", groups)
    _sync_after_write(actor=actor, action=f"create group {groupname}")
    return normalized


def group_exists(groupname: str) -> bool:
    """
    Check if a group exists in ENC.
    """
    return groupname in enc_data.load_map("groups")


def list_hosts() -> list[str]:
    """
    Return sorted host names.
    """
    return sorted(enc_data.load_map("hosts").keys())


def list_groups() -> list[str]:
    """
    Return sorted group names.
    """
    return sorted(enc_data.load_map("groups").keys())
