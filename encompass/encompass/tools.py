"""
analyzes data received
"""

# pylint: disable=too-many-lines
import logging
import os
import json
import hashlib
import re
import subprocess
import threading
import time
import requests
from django.conf import settings
from csr_store import csr_attributes
from . import enc_data
from . import runtime_settings

logger = logging.getLogger(__name__)

ENC_REPO_DIR = "/data"
_SYNC_STATE_LOCK = threading.Lock()
_SYNC_STATE = {
    "running": False,
    "pending": False,
    "actor": None,
    "action": None,
}
_SYNC_RESULT = threading.local()


class EncSyncError(Exception):
    """Raised when Git sync or enCapsule sync fails after ENC writes"""


class EncapsuleTriggerError(EncSyncError):
    """Raised when enCapsule fan-out trigger fails after git push."""


class StaleObjectError(Exception):
    """Raised when a save request uses stale object revision data."""


def payload_revision(payload: dict | None) -> str:
    """Return a stable revision hash for an ENC payload dictionary."""
    normalized = payload if isinstance(payload, dict) else {}
    encoded = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


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


def sync_runs_async() -> bool:
    """Return True when sync is configured to run asynchronously."""
    return _git_sync_mode() == "async"


def encapsule_sync_enabled() -> bool:
    """Return True when enCapsule sync fan-out is enabled."""
    return runtime_settings.encapsule_enabled()


def get_last_sync_result() -> dict:
    """
    Return the latest sync outcome for the current request thread.
    """
    return getattr(_SYNC_RESULT, "value", {})


def _set_last_sync_result(state: str, details: str | None = None) -> None:
    """Store sync outcome for the current request thread."""
    value = {"state": state}
    if details:
        value["details"] = details
    _SYNC_RESULT.value = value


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
    """Build commit message with optional action context and actor metadata."""
    base_message = str(os.environ.get("GIT_COMMIT_MESSAGE", "ENC data update")).strip()
    if not base_message:
        base_message = "ENC data update"
    if action:
        return f"{base_message}: {action}\n\nActor: {author}"
    return f"{base_message}\n\nActor: {author}"


def _run_checked(
    command, cwd=None, timeout=None, env=None
) -> subprocess.CompletedProcess:
    """Run command and raise EncSyncError with stderr/stdout on failure."""
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout,
            env=env,
        )
    except subprocess.TimeoutExpired as err:
        raise EncSyncError(
            f"Command timed out after {timeout}s: {' '.join(command)}"
        ) from err
    if result.returncode != 0:
        details = (result.stderr or result.stdout or "").strip()
        raise EncSyncError(f"Command failed: {' '.join(command)}; {details}")
    return result


def _encapsule_sync_runtime_env() -> dict[str, str]:
    """Build env overrides for encapsule-sync.sh from runtime settings."""
    defaults = runtime_settings.ENCAPSULE_SYNC_TEXT_DEFAULTS

    scheme = (
        runtime_settings.get_text(
            "ENCAPSULE_SYNC_SCHEME", defaults["ENCAPSULE_SYNC_SCHEME"]
        )
        .strip()
        .lower()
    )
    if scheme not in {"http", "https"}:
        scheme = defaults["ENCAPSULE_SYNC_SCHEME"]

    timeout = runtime_settings.get_text(
        "ENCAPSULE_SYNC_TIMEOUT", defaults["ENCAPSULE_SYNC_TIMEOUT"]
    ).strip()
    if not timeout.isdigit():
        timeout = defaults["ENCAPSULE_SYNC_TIMEOUT"]

    port = runtime_settings.get_text(
        "ENCAPSULE_SYNC_PORT", defaults["ENCAPSULE_SYNC_PORT"]
    ).strip()
    if not port.isdigit():
        port = defaults["ENCAPSULE_SYNC_PORT"]

    use_srv = (
        runtime_settings.get_text(
            "ENCAPSULE_SYNC_USE_SRV", defaults["ENCAPSULE_SYNC_USE_SRV"]
        )
        .strip()
        .lower()
    )
    if use_srv not in {"true", "false"}:
        use_srv = defaults["ENCAPSULE_SYNC_USE_SRV"]

    host = runtime_settings.get_text(
        "ENCAPSULE_SYNC_HOST", defaults["ENCAPSULE_SYNC_HOST"]
    ).strip()

    return {
        "ENCAPSULE_SYNC_SCHEME": scheme,
        "ENCAPSULE_SYNC_TIMEOUT": timeout,
        "ENCAPSULE_SYNC_PORT": port,
        "ENCAPSULE_SYNC_USE_SRV": use_srv,
        "ENCAPSULE_SYNC_HOST": host,
    }


def _sync_git_repo(actor: dict | None = None, action: str | None = None) -> bool:
    """Commit and push ENC data if there are staged/unstaged changes."""
    timeout = _env_int("GIT_SYNC_TIMEOUT", 30)

    _run_checked(
        ["git", "add", "hosts.yaml", "groups.yaml", "csr_challenges.yaml"],
        cwd=ENC_REPO_DIR,
        timeout=timeout,
    )

    status = _run_checked(
        [
            "git",
            "status",
            "-s",
            "--",
            "hosts.yaml",
            "groups.yaml",
            "csr_challenges.yaml",
        ],
        cwd=ENC_REPO_DIR,
        timeout=timeout,
    )
    if not status.stdout.strip():
        return False

    commit_name, commit_email, commit_author = _commit_actor(actor)
    commit_message = _commit_message(action, commit_author)
    branch = os.environ.get("GIT_BRANCH", "main")

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
    """Trigger enCapsule sync fan-out unless disabled by USE_ENCAPSULE."""
    if not runtime_settings.encapsule_enabled():
        logger.info("USE_ENCAPSULE disabled: skipping enCapsule sync fan-out")
        return

    timeout = _env_int("GIT_SYNC_TIMEOUT", 30)
    sync_env = os.environ.copy()
    sync_env.update(_encapsule_sync_runtime_env())
    try:
        _run_checked(
            ["/usr/local/bin/encapsule-sync.sh"], timeout=timeout, env=sync_env
        )
    except EncSyncError as err:
        logger.warning(
            "encapsule_sync_trigger_failed timeout=%s error=%s",
            timeout,
            err,
        )
        raise EncapsuleTriggerError(str(err)) from err


def _sync_once(
    actor: dict | None = None,
    action: str | None = None,
    force_trigger: bool = False,
) -> bool:
    """Perform a single sync operation: commit/push ENC data and trigger enCapsule sync if needed"""
    if force_trigger:
        _trigger_encapsule_sync()
        return True

    changed = _sync_git_repo(actor=actor, action=action)
    if changed:
        _trigger_encapsule_sync()
    return changed


def _sync_with_retries(
    actor: dict | None = None,
    action: str | None = None,
    force_trigger_start: bool = False,
) -> bool:
    """
    Perform sync with retries on failure, using environment-configured retry count and delay.
    """
    retries = _env_int("GIT_SYNC_RETRIES", 2)
    delay = _env_float("GIT_SYNC_RETRY_DELAY", 2.0)
    total_attempts = retries + 1
    force_trigger = force_trigger_start
    changed = False

    for attempt in range(total_attempts):
        attempt_num = attempt + 1
        logger.info("ENC sync attempt %s/%s started", attempt_num, total_attempts)
        try:
            changed = _sync_once(
                actor=actor, action=action, force_trigger=force_trigger
            )
            if attempt > 0:
                logger.info(
                    "ENC sync attempt %s/%s succeeded after retry",
                    attempt_num,
                    total_attempts,
                )
            return changed
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
    """Background worker function to perform enCapsule sync fan-out with retries."""
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
    """Enqueue an asynchronous ENC sync operation if not already running."""
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
    """Commit/push YAML changes and trigger enCapsule sync when needed."""
    if _git_sync_mode() == "async":
        _set_last_sync_result("async")
        _enqueue_async_sync(actor=actor, action=action)
        return

    try:
        changed = _sync_with_retries(actor=actor, action=action)
    except EncapsuleTriggerError as err:
        _set_last_sync_result("sync_failed", str(err))
        raise
    except EncSyncError as err:
        _set_last_sync_result("sync_failed", str(err))
        raise

    if changed:
        _set_last_sync_result("synced")
    else:
        _set_last_sync_result("no_changes")
        logger.info("ENC write completed with no YAML changes; sync trigger skipped")


def trigger_encapsule_sync_now() -> None:
    """Trigger enCapsule fan-out immediately, with retries."""
    if not encapsule_sync_enabled():
        logger.info("Manual enCapsule sync requested but USE_ENCAPSULE is disabled")
        return

    _sync_with_retries(force_trigger_start=True)


def get_host_details(hostname: str) -> dict:
    """Get host details from local ENC YAML data, with group/default fallback."""
    hosts = enc_data.load_map("hosts")
    groups = enc_data.load_map("groups")
    data = enc_data.resolve_host(hosts, groups, hostname)
    return data


def host_exists(hostname: str) -> bool:
    """Check if a host exists in ENC."""
    return hostname in enc_data.load_map("hosts")


def delete_host(hostname: str, actor: dict | None = None) -> dict:
    """Delete host from ENC."""
    with enc_data.data_lock("hosts"):
        hosts = enc_data.load_map("hosts")
        if hostname not in hosts:
            # pylint: disable=broad-exception-raised
            raise Exception(f"ENC error for {hostname}: 404")
            # pylint: enable=broad-exception-raised
        deleted = hosts[hostname]
        del hosts[hostname]
        enc_data.save_map("hosts", hosts)
    csr_attributes.delete(csr_attributes.host_entity_name(hostname))
    _sync_after_write(actor=actor, action=f"delete host {hostname}")
    return deleted


def update_host(
    hostname: str,
    payload: dict,
    actor: dict | None = None,
    expected_revision: str | None = None,
) -> dict:
    """Update host in ENC from full payload."""
    with enc_data.data_lock("hosts"):
        hosts = enc_data.load_map("hosts")
        if hostname not in hosts:
            # pylint: disable=broad-exception-raised
            raise Exception(f"ENC error for {hostname}: 404")
            # pylint: enable=broad-exception-raised
        current_revision = payload_revision(hosts.get(hostname))
        if expected_revision and expected_revision != current_revision:
            raise StaleObjectError(
                f"Host '{hostname}' was updated by someone else. Reload and try again."
            )
        normalized = enc_data.normalize_host_payload(payload)
        hosts[hostname] = normalized
        enc_data.save_map("hosts", hosts)
    csr_attributes.get_or_create(csr_attributes.host_entity_name(hostname))
    _sync_after_write(actor=actor, action=f"update host {hostname}")
    return normalized


def create_host(hostname: str, payload: dict, actor: dict | None = None) -> dict:
    """Create new host in ENC."""
    with enc_data.data_lock("hosts"):
        hosts = enc_data.load_map("hosts")
        normalized = enc_data.normalize_host_payload(payload)
        hosts[hostname] = normalized
        enc_data.save_map("hosts", hosts)
    csr_attributes.get_or_create(csr_attributes.host_entity_name(hostname))
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

    def _normalize_group_value(value: str) -> str:
        return re.sub(r"\s+", "", str(value or "")).lower()

    def _group_name_from_dn(value: str) -> str:
        token = str(value or "").strip()
        for part in token.split(","):
            head = part.strip()
            if head.lower().startswith("cn="):
                return head[3:].strip().lower()
        return token.lower()

    is_local_superuser = "__local_superuser__" in groups

    normalized_user = {_normalize_group_value(item) for item in groups}
    names_user = {_group_name_from_dn(item) for item in groups}
    admin_dn = _normalize_group_value(settings.ENC_ADMIN_GROUP)
    viewer_dn = _normalize_group_value(settings.ENC_VIEWER_GROUP)
    admin_name = _group_name_from_dn(settings.ENC_ADMIN_GROUP)
    viewer_name = _group_name_from_dn(settings.ENC_VIEWER_GROUP)
    is_admin = admin_dn in normalized_user or admin_name in names_user
    is_viewer = viewer_dn in normalized_user or viewer_name in names_user

    if return_all:
        group_names = []
        if is_local_superuser:
            group_names.append("superuser")
        if is_admin:
            group_names.append("admin")
        if is_viewer:
            group_names.append("viewer")

        return group_names

    if is_local_superuser:
        return "superuser"
    if is_admin:
        return "admin"
    if is_viewer:
        return "viewer"

    return "not yet known"


def get_group_details(groupname: str) -> dict:
    """Get group details from ENC."""
    groups = enc_data.load_map("groups")
    if groupname not in groups:
        # pylint: disable=broad-exception-raised
        raise Exception(f"ENC error for {groupname}: 404")
    # pylint: enable=broad-exception-raised
    return groups[groupname]


def delete_group(groupname: str, actor: dict | None = None) -> dict:
    """Delete group from ENC."""
    with enc_data.data_lock("groups"):
        groups = enc_data.load_map("groups")
        if groupname not in groups:
            # pylint: disable=broad-exception-raised
            raise Exception(f"ENC error for {groupname}: 404")
            # pylint: enable=broad-exception-raised
        if groupname == "default":
            # pylint: disable=broad-exception-raised
            raise Exception(f"ENC error for {groupname}: 403")
            # pylint: enable=broad-exception-raised
        deleted = groups[groupname]
        del groups[groupname]
        enc_data.save_map("groups", groups)
    csr_attributes.delete(csr_attributes.group_entity_name(groupname))
    _sync_after_write(actor=actor, action=f"delete group {groupname}")
    return deleted


def update_group(
    groupname: str,
    payload: dict,
    actor: dict | None = None,
    expected_revision: str | None = None,
) -> dict:
    """Update group in ENC from full payload."""
    with enc_data.data_lock("groups"):
        groups = enc_data.load_map("groups")
        if groupname not in groups:
            # pylint: disable=broad-exception-raised
            raise Exception(f"ENC error for {groupname}: 404")
            # pylint: enable=broad-exception-raised
        current_revision = payload_revision(groups.get(groupname))
        if expected_revision and expected_revision != current_revision:
            raise StaleObjectError(
                f"Group '{groupname}' was updated by someone else. Reload and try again."
            )
        normalized = enc_data.normalize_group_payload(payload)
        if groupname != "default" and not normalized.get("hosts", []):
            raise ValueError(
                "At least one host selector is required for non-default groups"
            )
        validate_group_selector_overlaps(groups, groupname, normalized.get("hosts", []))
        groups[groupname] = normalized
        enc_data.save_map("groups", groups)
    csr_attributes.get_or_create(csr_attributes.group_entity_name(groupname))
    _sync_after_write(actor=actor, action=f"update group {groupname}")
    return normalized


def create_group(groupname: str, payload: dict, actor: dict | None = None) -> dict:
    """Create new group in ENC."""
    with enc_data.data_lock("groups"):
        groups = enc_data.load_map("groups")
        normalized = enc_data.normalize_group_payload(payload)
        if groupname != "default" and not normalized.get("hosts", []):
            raise ValueError(
                "At least one host selector is required for non-default groups"
            )
        validate_group_selector_overlaps(groups, groupname, normalized.get("hosts", []))
        groups[groupname] = normalized
        enc_data.save_map("groups", groups)
    csr_attributes.get_or_create(csr_attributes.group_entity_name(groupname))
    _sync_after_write(actor=actor, action=f"create group {groupname}")
    return normalized


def group_exists(groupname: str) -> bool:
    """Check if a group exists in ENC."""
    return groupname in enc_data.load_map("groups")


def list_hosts() -> list[str]:
    """Return sorted host names."""
    return sorted(enc_data.load_map("hosts").keys())


def list_groups() -> list[str]:
    """Return sorted group names."""
    return sorted(enc_data.load_map("groups").keys())


def list_nonstandard_environment_usage() -> list[dict]:
    """
    Return non-predefined environment usage across hosts and groups.

    Each item has shape:
    {
        "environment": "feature/foo",
        "hosts": ["host1.example.org", ...],
        "groups": ["group_a", ...],
    }
    """
    predefined = {
        str(item).strip().lower()
        for item in runtime_settings.puppet_environments()
        if str(item).strip()
    }

    usage: dict[str, dict] = {}

    def collect(environment_value: str, category: str, name: str) -> None:
        environment = str(environment_value or "").strip()
        if not environment:
            return
        if environment.lower() in predefined:
            return

        entry = usage.setdefault(
            environment,
            {"environment": environment, "hosts": [], "groups": []},
        )
        entry[category].append(name)

    hosts = enc_data.load_map("hosts")
    for hostname, payload in hosts.items():
        if not isinstance(payload, dict):
            continue
        collect(payload.get("environment", ""), "hosts", hostname)

    groups = enc_data.load_map("groups")
    for groupname, payload in groups.items():
        if not isinstance(payload, dict):
            continue
        collect(payload.get("environment", ""), "groups", groupname)

    results = []
    for environment in sorted(usage.keys(), key=lambda value: value.lower()):
        item = usage[environment]
        item["hosts"] = sorted(item["hosts"])
        item["groups"] = sorted(item["groups"])
        results.append(item)

    return results


def get_git_log_patch_page(page: int = 1, per_page: int = 1) -> dict:
    """
    Return paginated output of `git log -p` from the ENC repository.
    Pagination is commit-based (one or more commits per page).
    """
    if page < 1:
        page = 1
    if per_page < 1:
        per_page = 1

    timeout = _env_int("GIT_SYNC_TIMEOUT", 30)
    count_result = _run_checked(
        ["git", "rev-list", "--count", "HEAD"], cwd=ENC_REPO_DIR, timeout=timeout
    )

    total_commits = int((count_result.stdout or "0").strip() or "0")
    if total_commits <= 0:
        return {
            "page": 1,
            "per_page": per_page,
            "total_pages": 1,
            "total_commits": 0,
            "output": "",
        }

    total_pages = (total_commits + per_page - 1) // per_page
    if page > total_pages:
        page = total_pages

    skip = (page - 1) * per_page
    log_result = _run_checked(
        ["git", "log", "-p", "--max-count", str(per_page), "--skip", str(skip)],
        cwd=ENC_REPO_DIR,
        timeout=timeout,
    )

    return {
        "page": page,
        "per_page": per_page,
        "total_pages": total_pages,
        "total_commits": total_commits,
        "output": log_result.stdout,
    }


def _canonical_profile(profile: dict | None) -> str:
    """Canonicalize an ENC profile for reliable equality checks."""
    data = profile if isinstance(profile, dict) else {}

    environment = str(data.get("environment", "")).strip()
    classes = sorted(
        {
            str(class_name).strip()
            for class_name in (data.get("classes", []) or [])
            if str(class_name).strip()
        }
    )
    parameters = data.get("parameters", {}) or {}
    if not isinstance(parameters, dict):
        parameters = {}

    return json.dumps(
        {
            "environment": environment,
            "classes": classes,
            "parameters": parameters,
        },
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _is_regex_selector(selector: str) -> bool:
    """Return True when a selector uses /regex/ notation."""
    return len(selector) >= 2 and selector.startswith("/") and selector.endswith("/")


def _regex_literal_prefix(regex_selector: str) -> str:
    """Extract a leading literal prefix from /regex/ selectors when possible."""
    if not _is_regex_selector(regex_selector):
        return ""

    pattern = regex_selector[1:-1]
    if pattern.startswith("^"):
        pattern = pattern[1:]

    prefix_chars = []
    index = 0
    metas = set(".^$*+?{}[]|()")
    non_literal_escapes = set("dDsSwWbBAZzG")

    while index < len(pattern):
        char = pattern[index]
        if char == "\\":
            if index + 1 >= len(pattern):
                break
            escaped = pattern[index + 1]
            if escaped in non_literal_escapes:
                break
            prefix_chars.append(escaped)
            index += 2
            continue

        if char in metas:
            break

        prefix_chars.append(char)
        index += 1

    return "".join(prefix_chars)


def _selector_patterns_overlap(selector_a: str, selector_b: str) -> bool:
    """Return True when two selectors can overlap on at least one hostname."""
    if selector_a == selector_b:
        return True

    a_regex = _is_regex_selector(selector_a)
    b_regex = _is_regex_selector(selector_b)

    if not a_regex and not b_regex:
        return selector_a.startswith(selector_b) or selector_b.startswith(selector_a)

    if a_regex and not b_regex:
        regex_selector, prefix_selector = selector_a, selector_b
    elif b_regex and not a_regex:
        regex_selector, prefix_selector = selector_b, selector_a
    else:
        prefix_a = _regex_literal_prefix(selector_a)
        prefix_b = _regex_literal_prefix(selector_b)
        if prefix_a and prefix_b:
            return prefix_a.startswith(prefix_b) or prefix_b.startswith(prefix_a)
        return False

    literal_prefix = _regex_literal_prefix(regex_selector)
    if literal_prefix and (
        literal_prefix.startswith(prefix_selector)
        or prefix_selector.startswith(literal_prefix)
    ):
        return True

    pattern = regex_selector[1:-1]
    try:
        compiled = re.compile(pattern)
    except re.error as err:
        raise ValueError(f"Invalid host regex '{regex_selector}': {err}") from err

    probe_values = [
        prefix_selector,
        f"{prefix_selector}x",
        f"{prefix_selector}example.com",
    ]
    return any(compiled.fullmatch(value) for value in probe_values)


def validate_group_selector_overlaps(
    groups: dict, groupname: str, candidate_hosts: list[str]
) -> None:
    """Reject ambiguous selector overlaps unless explicitly enabled by configuration."""
    candidate_selectors = []
    for raw_selector in candidate_hosts or []:
        selector = str(raw_selector).strip()
        if not selector:
            continue
        if _is_regex_selector(selector):
            try:
                re.compile(selector[1:-1])
            except re.error as err:
                raise ValueError(f"Invalid host regex '{selector}': {err}") from err
        candidate_selectors.append(selector)

    if not candidate_selectors:
        return

    if runtime_settings.overlapping_definitions_enabled():
        return

    conflicts = []
    for other_group, group_data in (groups or {}).items():
        if other_group in {"default", groupname}:
            continue
        if not isinstance(group_data, dict):
            continue

        for raw_selector in group_data.get("hosts", []) or []:
            other_selector = str(raw_selector).strip()
            if not other_selector:
                continue
            if _is_regex_selector(other_selector):
                try:
                    re.compile(other_selector[1:-1])
                except re.error as err:
                    raise ValueError(
                        f"Invalid host regex '{other_selector}' in group '{other_group}': {err}"
                    ) from err

            for candidate_selector in candidate_selectors:
                if _selector_patterns_overlap(candidate_selector, other_selector):
                    conflicts.append((candidate_selector, other_group, other_selector))

    if not conflicts:
        return

    known_hosts = sorted(enc_data.load_map("hosts").keys())
    details = []
    seen = set()
    for candidate_selector, other_group, other_selector in conflicts:
        key = (candidate_selector, other_group, other_selector)
        if key in seen:
            continue
        seen.add(key)

        example_host = None
        candidate_regex = _is_regex_selector(candidate_selector)
        other_regex = _is_regex_selector(other_selector)

        if not candidate_regex and not other_regex:
            example_host = next(
                (
                    hostname
                    for hostname in known_hosts
                    if hostname.startswith(candidate_selector)
                    and hostname.startswith(other_selector)
                ),
                None,
            )

        detail = (
            f"'{candidate_selector}' overlaps with group '{other_group}' selector "
            f"'{other_selector}'"
        )
        if example_host:
            detail += f" (example host: {example_host})"

        details.append(detail)
        if len(details) >= 5:
            break

    raise ValueError(
        "Selector overlap detected. "
        "Adjust group host selectors to avoid ambiguous matches: " + "; ".join(details)
    )


def _puppetdb_runtime_values() -> dict[str, str]:
    """Return raw PuppetDB runtime settings without implicit defaults."""
    return {
        "PUPPETDB_SCHEMA": runtime_settings.get_text_raw("PUPPETDB_SCHEMA"),
        "PUPPETDB_HOST": runtime_settings.get_text_raw("PUPPETDB_HOST"),
        "PUPPETDB_PORT": runtime_settings.get_text_raw("PUPPETDB_PORT"),
        "PUPPETDB_TIMEOUT": runtime_settings.get_text_raw("PUPPETDB_TIMEOUT"),
        "PUPPETDB_AUTH_METHOD": runtime_settings.get_text_raw("PUPPETDB_AUTH_METHOD"),
        "PUPPETDB_AUTH_HEADER": runtime_settings.get_text_raw("PUPPETDB_AUTH_HEADER"),
        "PUPPETDB_AUTH_TOKEN": runtime_settings.get_text_raw("PUPPETDB_AUTH_TOKEN"),
        "PUPPETDB_BASIC_USERNAME": runtime_settings.get_text_raw("PUPPETDB_BASIC_USERNAME"),
        "PUPPETDB_BASIC_PASSWORD": runtime_settings.get_text_raw("PUPPETDB_BASIC_PASSWORD"),
        "PUPPETDB_CLIENT_CERT_PATH": runtime_settings.get_text_raw("PUPPETDB_CLIENT_CERT_PATH"),
        "PUPPETDB_CLIENT_KEY_PATH": runtime_settings.get_text_raw("PUPPETDB_CLIENT_KEY_PATH"),
        "PUPPETDB_CA_CERT_PATH": runtime_settings.get_text_raw("PUPPETDB_CA_CERT_PATH"),
        "PUPPETDB_TLS_SKIP_VERIFY": runtime_settings.get_text_raw("PUPPETDB_TLS_SKIP_VERIFY"),
    }


def validate_puppetdb_settings(values: dict[str, str] | None = None) -> list[str]:
    """Validate PuppetDB settings. Empty fields are treated as missing configuration."""
    config = values if values is not None else _puppetdb_runtime_values()
    errors: list[str] = []

    schema = str(config.get("PUPPETDB_SCHEMA", "")).strip().lower()
    if not schema:
        errors.append("PuppetDB Schema is not configured.")
    elif schema not in {"http", "https"}:
        errors.append("PuppetDB Schema must be 'http' or 'https'.")

    host = str(config.get("PUPPETDB_HOST", "")).strip()
    if not host:
        errors.append("PuppetDB Host is not configured.")

    port = str(config.get("PUPPETDB_PORT", "")).strip()
    if not port:
        errors.append("PuppetDB Port is not configured.")
    elif not port.isdigit():
        errors.append("PuppetDB Port must be numeric.")
    else:
        port_value = int(port)
        if port_value < 1 or port_value > 65535:
            errors.append("PuppetDB Port must be between 1 and 65535.")

    timeout = str(config.get("PUPPETDB_TIMEOUT", "")).strip()
    if not timeout:
        errors.append("PuppetDB Timeout is not configured.")
    elif not timeout.isdigit():
        errors.append("PuppetDB Timeout must be numeric.")
    else:
        timeout_value = int(timeout)
        if timeout_value < 1 or timeout_value > 300:
            errors.append("PuppetDB Timeout must be between 1 and 300 seconds.")

    auth_method = str(config.get("PUPPETDB_AUTH_METHOD", "")).strip().lower()
    if not auth_method:
        auth_method = runtime_settings.PUPPETDB_TEXT_DEFAULTS["PUPPETDB_AUTH_METHOD"]
    if auth_method not in {"none", "token", "basic"}:
        errors.append("PuppetDB Auth Method must be one of: none, token, basic.")
    elif auth_method == "token":
        auth_header = str(config.get("PUPPETDB_AUTH_HEADER", "")).strip()
        auth_token = str(config.get("PUPPETDB_AUTH_TOKEN", "")).strip()
        if not auth_header:
            errors.append("PuppetDB Auth Header is required when Auth Method is token.")
        if not auth_token:
            errors.append("PuppetDB Auth Token is required when Auth Method is token.")
    elif auth_method == "basic":
        username = str(config.get("PUPPETDB_BASIC_USERNAME", "")).strip()
        password = str(config.get("PUPPETDB_BASIC_PASSWORD", "")).strip()
        if not username:
            errors.append(
                "PuppetDB Basic Username is required when Auth Method is basic."
            )
        if not password:
            errors.append(
                "PuppetDB Basic Password is required when Auth Method is basic."
            )

    client_cert = str(config.get("PUPPETDB_CLIENT_CERT_PATH", "")).strip()
    client_key = str(config.get("PUPPETDB_CLIENT_KEY_PATH", "")).strip()
    if bool(client_cert) != bool(client_key):
        errors.append(
            "PuppetDB client certificate and client key must be set together."
        )

    tls_skip_verify = str(config.get("PUPPETDB_TLS_SKIP_VERIFY", "")).strip().lower()
    if tls_skip_verify and tls_skip_verify not in {"true", "false"}:
        errors.append("PuppetDB TLS Skip Verify must be 'true' or 'false'.")

    return errors


def _puppetdb_request_kwargs(values: dict[str, str]) -> dict:
    """Build requests kwargs for PuppetDB connectivity based on runtime settings."""
    timeout = int(str(values.get("PUPPETDB_TIMEOUT", "20")).strip())
    kwargs: dict = {"timeout": timeout}

    auth_method = str(values.get("PUPPETDB_AUTH_METHOD", "none")).strip().lower()
    if auth_method == "token":
        header_name = str(values.get("PUPPETDB_AUTH_HEADER", "Authorization")).strip()
        token = str(values.get("PUPPETDB_AUTH_TOKEN", "")).strip()
        kwargs["headers"] = {header_name: token}
    elif auth_method == "basic":
        username = str(values.get("PUPPETDB_BASIC_USERNAME", "")).strip()
        password = str(values.get("PUPPETDB_BASIC_PASSWORD", "")).strip()
        kwargs["auth"] = (username, password)

    client_cert = str(values.get("PUPPETDB_CLIENT_CERT_PATH", "")).strip()
    client_key = str(values.get("PUPPETDB_CLIENT_KEY_PATH", "")).strip()
    if client_cert and client_key:
        kwargs["cert"] = (client_cert, client_key)

    tls_skip_verify = (
        str(values.get("PUPPETDB_TLS_SKIP_VERIFY", "false")).strip().lower()
        == "true"
    )
    ca_cert = str(values.get("PUPPETDB_CA_CERT_PATH", "")).strip()
    if tls_skip_verify:
        kwargs["verify"] = False
    elif ca_cert:
        kwargs["verify"] = ca_cert

    return kwargs


def test_puppetdb_settings(
    values: dict[str, str],
) -> tuple[bool, list[tuple[str, str]]]:
    """Test PuppetDB connectivity using submitted (unsaved) values."""
    errors = validate_puppetdb_settings(values)
    if errors:
        return False, [("error", item) for item in errors]

    schema = str(values.get("PUPPETDB_SCHEMA", "")).strip().lower()
    host = str(values.get("PUPPETDB_HOST", "")).strip()
    port = str(values.get("PUPPETDB_PORT", "")).strip()
    url = f"{schema}://{host}:{port}/pdb/query/v4/nodes"

    results: list[tuple[str, str]] = [("info", f"Connecting to {url}")]
    request_kwargs = _puppetdb_request_kwargs(values)
    if str(values.get("PUPPETDB_TLS_SKIP_VERIFY", "false")).strip().lower() == "true":
        results.append(("warning", "PuppetDB TLS certificate verification is disabled."))

    try:
        response = requests.get(url, params={"limit": 1}, **request_kwargs)
    except requests.RequestException as err:
        return False, [("error", f"Failed to query PuppetDB: {err}")]

    if response.status_code != 200:
        return False, [
            (
                "error",
                f"PuppetDB query failed ({response.status_code}): {response.text[:200]}",
            )
        ]

    try:
        payload = response.json()
    except ValueError:
        return False, [("error", "PuppetDB returned invalid JSON payload")]

    if not isinstance(payload, list):
        return False, [("error", "PuppetDB nodes payload is not a list")]

    results.append(("success", "PuppetDB query succeeded."))
    results.append(
        ("info", f"Received {len(payload)} node record(s) in probe response.")
    )
    return True, results


def _puppetdb_nodes_url() -> str:
    """Build PuppetDB nodes URL from runtime settings."""
    values = _puppetdb_runtime_values()
    errors = validate_puppetdb_settings(values)
    if errors:
        raise EncSyncError(
            "PuppetDB settings are incomplete or invalid: " + "; ".join(errors)
        )
    schema = str(values["PUPPETDB_SCHEMA"]).strip().lower()
    host = str(values["PUPPETDB_HOST"]).strip()
    port = str(values["PUPPETDB_PORT"]).strip()
    return f"{schema}://{host}:{port}/pdb/query/v4/nodes"


def _build_group_matchers(
    groups: dict,
) -> tuple[dict, list[tuple[int, re.Pattern, dict]]]:
    """
    Build optimized group matchers preserving first-match order semantics.
    Returns (prefix_trie, regex_matchers).
    """
    root = {"children": {}, "match": None}
    regex_matchers = []
    order = 0

    for group_name, group_data in groups.items():
        if group_name == "default" or not isinstance(group_data, dict):
            continue

        payload = group_data.copy()
        payload.pop("hosts", None)

        for raw_selector in group_data.get("hosts", []) or []:
            selector = str(raw_selector).strip()
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
                    compiled = re.compile(pattern)
                except re.error as err:
                    raise EncSyncError(
                        f"Invalid host regex '{selector}' in group '{group_name}': {err}"
                    ) from err
                regex_matchers.append((order, compiled, payload))
                order += 1
                continue

            node = root
            for char in selector:
                node = node["children"].setdefault(
                    char, {"children": {}, "match": None}
                )

            if node["match"] is None:
                node["match"] = (order, payload)
            order += 1

    return root, regex_matchers


def _resolve_group_match(
    certname: str, trie: dict, regex_matchers: list[tuple[int, re.Pattern, dict]]
) -> dict | None:
    """Resolve a certname against compiled group matchers using earliest configured match."""
    node = trie
    best_order = None
    best_payload = None

    for char in certname:
        current_match = node.get("match")
        if current_match is not None:
            current_order, current_payload = current_match
            if best_order is None or current_order < best_order:
                best_order = current_order
                best_payload = current_payload

        child = node.get("children", {}).get(char)
        if child is None:
            break
        node = child

    current_match = node.get("match")
    if current_match is not None:
        current_order, current_payload = current_match
        if best_order is None or current_order < best_order:
            best_order = current_order
            best_payload = current_payload

    for regex_order, regex_pattern, regex_payload in regex_matchers:
        if best_order is not None and regex_order > best_order:
            break
        if regex_pattern.fullmatch(certname):
            if best_order is None or regex_order < best_order:
                best_order = regex_order
                best_payload = regex_payload
            break

    if best_payload is None:
        return None
    return best_payload


def get_puppetdb_nodes() -> list[str]:
    """Fetch and return sorted node certnames from PuppetDB."""
    values = _puppetdb_runtime_values()
    errors = validate_puppetdb_settings(values)
    if errors:
        raise EncSyncError(
            "PuppetDB settings are incomplete or invalid: " + "; ".join(errors)
        )

    url = _puppetdb_nodes_url()
    request_kwargs = _puppetdb_request_kwargs(values)

    try:
        response = requests.get(url, **request_kwargs)
    except requests.RequestException as err:
        raise EncSyncError(f"Failed to query PuppetDB nodes: {err}") from err

    if response.status_code != 200:
        raise EncSyncError(
            f"PuppetDB query failed ({response.status_code}): {response.text[:200]}"
        )

    try:
        payload = response.json()
    except ValueError as err:
        raise EncSyncError("PuppetDB returned invalid JSON payload") from err

    if not isinstance(payload, list):
        raise EncSyncError("PuppetDB nodes payload is not a list")

    certnames = {
        str(item.get("certname", "")).strip()
        for item in payload
        if isinstance(item, dict)
    }
    certnames.discard("")
    return sorted(certnames)


def list_unclassified_hosts() -> dict:
    """Return PuppetDB nodes whose ENC resolved profile matches the default profile."""
    nodes = get_puppetdb_nodes()
    hosts = enc_data.load_map("hosts")
    groups = enc_data.load_map("groups")
    prefix_trie, regex_matchers = _build_group_matchers(groups)

    default_profile = groups.get("default", {})
    if not isinstance(default_profile, dict):
        default_profile = {}
    default_profile = default_profile.copy()
    default_profile.pop("hosts", None)

    default_canonical = _canonical_profile(default_profile)
    unclassified = []

    for certname in nodes:
        resolved = hosts.get(certname)
        if resolved is None:
            resolved = _resolve_group_match(certname, prefix_trie, regex_matchers)
        if resolved is None:
            resolved = default_profile

        if _canonical_profile(resolved) == default_canonical:
            unclassified.append(certname)

    return {
        "nodes": nodes,
        "unclassified": unclassified,
        "default_profile": default_profile,
        "puppetdb_url": _puppetdb_nodes_url(),
    }
