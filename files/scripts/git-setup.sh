#!/usr/bin/env bash
#
# variables:
# - GIT_REPO_URL: URL of the Git repository
# - GIT_REPO_BRANCH: branch of the Git repository
# - SSH_KEY_TYPE: type of the SSH key (rsa, ed25519, ecdsa)
# - GIT_REPO_PRIVATE_SSH_KEY: SSH key for accessing the Git repository
# - GIT_REPO_PRIVATE_SSH_KEY_FILE: path to a file containing the SSH key
# - GIT_REPO_USERNAME: username for accessing the Git repository
#
set -e

GIT_REPO="${GIT_REPO:-}"
if [ -z "$GIT_REPO" ] && [ -n "${GIT_REPO_URL:-}" ]; then
    GIT_REPO="$GIT_REPO_URL"
fi
if [ -z "$GIT_REPO" ] && [ -n "${GIT_HOST:-}" ] && [ -n "${GIT_REPO_PATH:-}" ] && [ -n "${GIT_REPO_USERNAME:-}" ]; then
    GIT_REPO="ssh://${GIT_REPO_USERNAME}@${GIT_HOST}/${GIT_REPO_PATH}"
fi

KEY_FILE="${KEY_FILE:-/root/.ssh/id_${SSH_KEY_TYPE:-}}"

if [ -z "${GIT_REPO_PRIVATE_SSH_KEY:-}" ] && [ -n "${GIT_REPO_PRIVATE_SSH_KEY_FILE:-}" ]; then
    if [ ! -r "$GIT_REPO_PRIVATE_SSH_KEY_FILE" ]; then
        echo "==> Git-setup: [ERROR] GIT_REPO_PRIVATE_SSH_KEY_FILE is set but not readable: $GIT_REPO_PRIVATE_SSH_KEY_FILE"
        exit 1
    fi
    GIT_REPO_PRIVATE_SSH_KEY="$(cat "$GIT_REPO_PRIVATE_SSH_KEY_FILE")"
fi

# check that all required variables are set and valid
if [ -n "$GIT_REPO" ] && [ -n "${GIT_REPO_BRANCH:-}" ] && [ -n "${SSH_KEY_TYPE:-}" ] && [ -n "${GIT_REPO_PRIVATE_SSH_KEY:-}" ] && [ -n "${GIT_REPO_USERNAME:-}" ] && [ -n "${GIT_HOST:-}" ]; then
    echo "==> Git-setup: Setting up Git authentication variables..."
else
    echo "==> Git-setup: [ERROR] Missing required Git authentication variables"
    echo "==> Git-setup: [ERROR] Please set GIT_REPO_BRANCH, SSH_KEY_TYPE, GIT_REPO_USERNAME, GIT_HOST, and either GIT_REPO_PRIVATE_SSH_KEY or GIT_REPO_PRIVATE_SSH_KEY_FILE, plus either GIT_REPO or GIT_REPO_URL (or GIT_REPO_PATH with GIT_HOST and GIT_REPO_USERNAME)"
    exit 1
fi
case "$SSH_KEY_TYPE" in
rsa | ed25519 | ecdsa) ;;
*)
    echo "==> Git-setup: [ERROR] Unsupported SSH_KEY_TYPE: $SSH_KEY_TYPE. Supported types are: rsa, ed25519, ecdsa"
    exit 1
    ;;
esac

mkdir -p /root/.ssh /root/.ssh/cm
chmod 700 /root/.ssh

# inject the SSH key into the container
printf '%s\n' "$GIT_REPO_PRIVATE_SSH_KEY" >"$KEY_FILE"
chmod 600 "$KEY_FILE"

touch /root/.ssh/known_hosts
chmod 600 /root/.ssh/known_hosts
if ! ssh-keygen -F "$GIT_HOST" -f /root/.ssh/known_hosts >/dev/null 2>&1; then
    ssh-keyscan -H "$GIT_HOST" >>/root/.ssh/known_hosts 2>/dev/null || true
fi

# create a basic SSH config
install -d -m 700 /root/.ssh/conf.d
cat <<EOF >/root/.ssh/conf.d/git.conf
Host $GIT_HOST
    HostName $GIT_HOST
    User $GIT_REPO_USERNAME
    IdentityFile $KEY_FILE
EOF
chmod 600 /root/.ssh/conf.d/git.conf

# clone and test the Git repository
if [ -d /data/.git ]; then
    echo "==> Git-setup: Existing Git repository found in /data, updating..."
    git -C /data remote set-url origin "$GIT_REPO"
    git -C /data fetch origin "$GIT_REPO_BRANCH"
    git -C /data checkout "$GIT_REPO_BRANCH"
    git -C /data reset --hard "origin/$GIT_REPO_BRANCH"
else
    if ! git clone --branch "$GIT_REPO_BRANCH" "$GIT_REPO" /data; then
        echo "==> Git-setup: [ERROR] Failed to clone Git repository"
        exit 1
    fi
fi

# inject the hosts.yaml and groups.yaml if they don't exist
cd /data
[ -f hosts.yaml ] || echo "---" >hosts.yaml
[ -f groups.yaml ] || cp /root/.groups.yaml groups.yaml
cmp -s /root/.README.md README.md || cp -f /root/.README.md README.md

# clean up alien files and directories
find . -maxdepth 1 -mindepth 1 -type d -not -path ./.git -exec rm -rf {} +
find . -type f ! -name hosts.yaml ! -name groups.yaml \
    ! -name README.md -not -path "./.git/*" ! -name .git -exec rm -f {} +

# add and commit the initial files if there are changes
git add hosts.yaml groups.yaml README.md
git config user.name "${GIT_COMMIT_NAME:-encompass-bot}"
git config user.email "${GIT_COMMIT_EMAIL:-encompass@local}"

if [ -z "$(git status -s)" ]; then
    echo "==> Git-setup: No changes to commit, skipping commit and push"
else
    git commit -m "Initial commit of hosts.yaml, groups.yaml, and README.md"
    if git push origin "$GIT_REPO_BRANCH"; then
        echo "==> Git-setup: Successfully pushed initial commit to Git repository"
    else
        echo "==> Git-setup: [ERROR] Failed to push initial commit to Git repository"
        exit 1
    fi
fi
