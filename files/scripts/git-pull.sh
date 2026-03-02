#!/usr/bin/env bash
#
# Pull-only Git sync for an existing checkout in /data.
# This script never creates branches and never pushes.
#
# variables:
# - GIT_BRANCH: branch of the Git repository to sync (default: main)
# - GIT_REPO / GIT_REPO_URL: optional origin URL override
#
set -e

GIT_BRANCH="${GIT_BRANCH:-main}"
GIT_REPO="${GIT_REPO:-}"
if [ -z "$GIT_REPO" ] && [ -n "${GIT_REPO_URL:-}" ]; then
    GIT_REPO="$GIT_REPO_URL"
fi
if [ -z "$GIT_REPO" ] && [ -n "${GIT_HOST:-}" ] && [ -n "${GIT_REPO_PATH:-}" ] && [ -n "${GIT_REPO_USERNAME:-}" ]; then
    GIT_REPO="ssh://${GIT_REPO_USERNAME}@${GIT_HOST}/${GIT_REPO_PATH}"
fi

if [ ! -d /data/.git ]; then
    echo "==> Git-pull: [ERROR] /data is not a Git repository. Run git-setup.sh first"
    exit 1
fi

if [ -n "$GIT_REPO" ]; then
    git -C /data remote set-url origin "$GIT_REPO"
fi

if ! git -C /data ls-remote --exit-code --heads origin "$GIT_BRANCH" >/dev/null 2>&1; then
    echo "==> Git-pull: [ERROR] Branch '$GIT_BRANCH' does not exist on origin"
    exit 1
fi

git -C /data fetch --quiet origin "$GIT_BRANCH"

if [ "$(git -C /data branch --show-current)" = "$GIT_BRANCH" ]; then
    echo "==> Git-pull: Already on branch '$GIT_BRANCH'" >&2  # django is using stderr to print the message
else
    git -C /data checkout "$GIT_BRANCH" || git -C /data checkout -b "$GIT_BRANCH" "origin/$GIT_BRANCH"
fi

LOCAL_HEAD="$(git -C /data rev-parse HEAD)"
REMOTE_HEAD="$(git -C /data rev-parse "origin/$GIT_BRANCH")"

if [ "$LOCAL_HEAD" = "$REMOTE_HEAD" ]; then
    echo "==> Git-pull: Branch '$GIT_BRANCH' is already up to date" >&2  # django is using stderr to print the message
else
    git -C /data reset --hard "origin/$GIT_BRANCH"
    echo "==> Git-pull: Updated branch '$GIT_BRANCH' from ${LOCAL_HEAD:0:12} to ${REMOTE_HEAD:0:12}" >&2
fi
