#!/usr/bin/env bash

set -euo pipefail

SCHEME="${ENCAPSULE_SYNC_SCHEME:-http}"
DEFAULT_PORT="${ENCAPSULE_SYNC_PORT:-8081}"
PATH_SUFFIX="${ENCAPSULE_SYNC_PATH:-/sync}"
TIMEOUT="${ENCAPSULE_SYNC_TIMEOUT:-5}"
TOKEN="${ENCAPSULE_SYNC_TOKEN:-}"
HOST_INPUT="${ENCAPSULE_SYNC_HOST:-}"

USE_ENCAPSULE="${USE_ENCAPSULE:-true}"
case "${USE_ENCAPSULE,,}" in
0|false|no|off)
    echo "[INFO] USE_ENCAPSULE disabled, skipping sync"
    exit 0
    ;;
esac

if [ -z "$TOKEN" ]; then
    echo "[ERROR] ENCAPSULE_SYNC_TOKEN is required"
    exit 1
fi

if [ -z "$HOST_INPUT" ]; then
    echo "[INFO] ENCAPSULE_SYNC_HOST is empty, nothing to sync"
    exit 0
fi

if [[ "$PATH_SUFFIX" != /* ]]; then
    PATH_SUFFIX="/${PATH_SUFFIX}"
fi

declare -a targets=()

add_target() {
    local url="$1"
    if [ -n "$url" ]; then
        targets+=("$url")
    fi
}

IFS=',' read -r -a entries <<<"$HOST_INPUT"
for raw in "${entries[@]}"; do
    entry="$(echo "$raw" | xargs)"
    [ -z "$entry" ] && continue

    if [[ "$entry" =~ ^https?:// ]]; then
        add_target "$entry"
        continue
    fi

    if [[ "$entry" == _* ]]; then
        if ! command -v dig >/dev/null 2>&1; then
            echo "[ERROR] SRV-style entry '$entry' requires 'dig'"
            exit 1
        fi
        while read -r _priority _weight port target; do
            target="${target%.}"
            [ -z "$target" ] && continue
            add_target "${SCHEME}://${target}:${port}${PATH_SUFFIX}"
        done < <(dig +short SRV "$entry")
        continue
    fi

    if [[ "$entry" == *:* ]]; then
        add_target "${SCHEME}://${entry}${PATH_SUFFIX}"
    else
        add_target "${SCHEME}://${entry}:${DEFAULT_PORT}${PATH_SUFFIX}"
    fi
done

if [ "${#targets[@]}" -eq 0 ]; then
    echo "[ERROR] No encapsule targets resolved"
    exit 1
fi

tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT

pids=()
for idx in "${!targets[@]}"; do
    url="${targets[$idx]}"
    echo "[INFO] Triggering $url"
    (
        curl -fsS -m "$TIMEOUT" -X POST -H "X-Encapsule-Token: $TOKEN" "$url" >/dev/null
    ) >"$tmp_dir/${idx}.out" 2>"$tmp_dir/${idx}.err" &
    pids+=("$!")
done

failed=0
for idx in "${!pids[@]}"; do
    if ! wait "${pids[$idx]}"; then
        echo "[ERROR] Failed to trigger ${targets[$idx]}"
        if [ -s "$tmp_dir/${idx}.err" ]; then
            sed 's/^/[ERROR] /' "$tmp_dir/${idx}.err"
        fi
        failed=1
    fi
done

[ "$failed" -eq 0 ] || {
    echo "[ERROR] One or more encapsule sync targets failed"
    exit 1
}

echo "[INFO] Sync trigger delivered to all encapsule targets"
