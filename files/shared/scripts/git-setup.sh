#!/usr/bin/env bash
#
# variables:
# - GIT_BRANCH: branch of the Git repository to use (default: main)
# - GIT_REPO_URL: URL of the Git repository
# - GIT_HOST: Git host (used for ssh host key bootstrap)
# - GIT_REPO_PATH: Git repository path on host
# - GIT_REPO_USERNAME: username for accessing the Git repository
# - GIT_READ_ONLY: when true, disallow any git writes (push/commit/branch creation)
# - GIT_SSH_KEY_TYPE: type of the SSH key (rsa, ed25519, ecdsa)
# - GIT_SSH_PRIVATE_KEY: SSH key for accessing the Git repository
# - GIT_SSH_PRIVATE_KEY_FILE: path to a file containing the SSH key
#
set -e

GIT_BRANCH="${GIT_BRANCH:-main}"
GIT_READ_ONLY="${GIT_READ_ONLY:-false}"
GIT_REPO=""
if [ -n "${GIT_REPO_URL:-}" ]; then
    GIT_REPO="$GIT_REPO_URL"
elif [ -n "${GIT_HOST:-}" ] && [ -n "${GIT_REPO_PATH:-}" ] && [ -n "${GIT_REPO_USERNAME:-}" ]; then
    GIT_REPO="ssh://${GIT_REPO_USERNAME}@${GIT_HOST}/${GIT_REPO_PATH}"
fi

GIT_SSH_KEY_FILE="${GIT_SSH_KEY_FILE:-/root/.ssh/id_${GIT_SSH_KEY_TYPE:-}}"

if [ -n "${GIT_SSH_PRIVATE_KEY:-}" ] && [ -n "${GIT_SSH_PRIVATE_KEY_FILE:-}" ]; then
    echo "==> Git-setup: [ERROR] GIT_SSH_PRIVATE_KEY and GIT_SSH_PRIVATE_KEY_FILE are mutually exclusive"
    exit 1
fi

if [ -z "${GIT_SSH_PRIVATE_KEY:-}" ] && [ -n "${GIT_SSH_PRIVATE_KEY_FILE:-}" ]; then
    if [ ! -r "$GIT_SSH_PRIVATE_KEY_FILE" ]; then
        echo "==> Git-setup: [ERROR] GIT_SSH_PRIVATE_KEY_FILE is set but not readable: $GIT_SSH_PRIVATE_KEY_FILE"
        exit 1
    fi
    GIT_SSH_PRIVATE_KEY="$(cat "$GIT_SSH_PRIVATE_KEY_FILE")"
fi

# check that all required variables are set and valid
if [ -n "$GIT_REPO" ] && [ -n "${GIT_SSH_KEY_TYPE:-}" ] && [ -n "${GIT_SSH_PRIVATE_KEY:-}" ] && [ -n "${GIT_REPO_USERNAME:-}" ] && [ -n "${GIT_HOST:-}" ]; then
    echo "==> Git-setup: Setting up Git authentication variables..."
else
    echo "==> Git-setup: [ERROR] Missing required Git authentication variables"
    echo "==> Git-setup: [ERROR] Please set GIT_SSH_KEY_TYPE, GIT_REPO_USERNAME, GIT_HOST, and one of GIT_SSH_PRIVATE_KEY or GIT_SSH_PRIVATE_KEY_FILE, plus GIT_REPO_URL or GIT_REPO_PATH"
    exit 1
fi
case "$GIT_SSH_KEY_TYPE" in
rsa)
    SSH_KEYSCAN_TYPE="rsa"
    SSH_HOST_KEY_ALGORITHMS="ssh-rsa"
    ;;
ed25519)
    SSH_KEYSCAN_TYPE="ed25519"
    SSH_HOST_KEY_ALGORITHMS="ssh-ed25519"
    ;;
ecdsa)
    SSH_KEYSCAN_TYPE="ecdsa"
    SSH_HOST_KEY_ALGORITHMS="ecdsa-sha2-nistp256,ecdsa-sha2-nistp384,ecdsa-sha2-nistp521"
    ;;
*)
    echo "==> Git-setup: [ERROR] Unsupported GIT_SSH_KEY_TYPE: $GIT_SSH_KEY_TYPE. Supported types are: rsa, ed25519, ecdsa"
    exit 1
    ;;
esac

case "$GIT_READ_ONLY" in
true | false) ;;
*)
    echo "==> Git-setup: [ERROR] GIT_READ_ONLY must be either 'true' or 'false'"
    exit 1
    ;;
esac

# inject the SSH key into the container
printf '%s\n' "$GIT_SSH_PRIVATE_KEY" >"$GIT_SSH_KEY_FILE"
chmod 600 "$GIT_SSH_KEY_FILE"

ssh-keygen -R "$GIT_HOST" -f /root/.ssh/known_hosts >/dev/null 2>&1 || true
SCANNED_HOST_KEY="$(ssh-keyscan -H -t "$SSH_KEYSCAN_TYPE" "$GIT_HOST" 2>/dev/null | grep -v '^#' || true)"
if [ -z "$SCANNED_HOST_KEY" ]; then
    echo "==> Git-setup: [ERROR] No $SSH_KEYSCAN_TYPE host key found on $GIT_HOST"
    exit 1
fi
printf '%s\n' "$SCANNED_HOST_KEY" >>/root/.ssh/known_hosts

# create a basic SSH config
install -d -m 700 /root/.ssh/conf.d
cat <<EOF >/root/.ssh/conf.d/git.conf
Host $GIT_HOST
    HostName $GIT_HOST
    User $GIT_REPO_USERNAME
    IdentityFile $GIT_SSH_KEY_FILE
    HostKeyAlgorithms $SSH_HOST_KEY_ALGORITHMS
EOF
chmod 600 /root/.ssh/conf.d/git.conf

# clone and test the Git repository
if [ -d /data/.git ]; then
    echo "==> Git-setup: Existing Git repository found in /data, updating..."
    git -C /data remote set-url origin "$GIT_REPO"
    if git -C /data ls-remote --exit-code --heads origin "$GIT_BRANCH" >/dev/null 2>&1; then
        git -C /data fetch origin "$GIT_BRANCH"
        if [ "$(git -C /data branch --show-current)" = "$GIT_BRANCH" ]; then
            echo "==> Git-setup: Already on branch '$GIT_BRANCH'"
        else
            git -C /data checkout "$GIT_BRANCH" || git -C /data checkout -b "$GIT_BRANCH" "origin/$GIT_BRANCH"
        fi
        git -C /data reset --hard "origin/$GIT_BRANCH"
    else
        echo "==> Git-setup: Branch '$GIT_BRANCH' does not exist on origin (yet); branch-creation logic will handle it"
    fi
else
    if git ls-remote --exit-code --heads "$GIT_REPO" "$GIT_BRANCH" >/dev/null 2>&1; then
        if ! git clone --branch "$GIT_BRANCH" "$GIT_REPO" /data; then
            echo "==> Git-setup: [ERROR] Failed to clone Git repository"
            exit 1
        fi
    elif ! git clone "$GIT_REPO" /data; then
        echo "==> Git-setup: [ERROR] Failed to clone Git repository"
        exit 1
    fi
fi

# change directory to the Git repository
cd /data

# ensure the specified branch exists and is checked out
if git show-ref --verify --quiet "refs/heads/$GIT_BRANCH"; then
    git checkout "$GIT_BRANCH"
elif git ls-remote --exit-code --heads origin "$GIT_BRANCH" >/dev/null 2>&1; then
    if [ "$(git branch --show-current)" = "$GIT_BRANCH" ]; then
        echo "==> Git-setup: Already on branch '$GIT_BRANCH'"
    else
        echo "==> Git-setup: Branch '$GIT_BRANCH' exists on origin but not locally, checking it out"
        git checkout -b "$GIT_BRANCH" "origin/$GIT_BRANCH"
    fi
else
    if [ "$GIT_READ_ONLY" = "true" ]; then
        echo "==> Git-setup: [ERROR] Branch '$GIT_BRANCH' does not exist on origin and GIT_READ_ONLY=true prevents creating it"
        exit 1
    elif [ ! -d /root/.templates ]; then
        echo "==> Git-setup: [ERROR] Branch '$GIT_BRANCH' does not exist on origin and this runtime is not allowed to create it"
        echo "==> Git-setup: [ERROR] Only enCompass bootstrap context can create missing branches"
        exit 1
    fi
    git checkout -b "$GIT_BRANCH"
    git push -u origin "$GIT_BRANCH"
fi

# we skip enCapsule here since it doesn't have write permissions to the Git repository
if [ "$GIT_READ_ONLY" = "true" ]; then
    echo "==> Git-setup: Read-only mode enabled; skipping bootstrap/commit/push steps"
elif [ -d /root/.templates ]; then
    # inject ENC data files if they don't exist
    [ -f hosts.yaml ] || echo "---" >hosts.yaml
    [ -f groups.yaml ] || cp /root/.templates/groups.yaml groups.yaml
    [ -f csr_challenges.yaml ] || cp /root/.templates/csr_challenges.yaml csr_challenges.yaml
    cmp -s /root/.templates/README.md README.md || cp -f /root/.templates/README.md README.md

    # clean up alien files and directories
    find . -maxdepth 1 -mindepth 1 -type d -not -path ./.git -exec rm -rf {} +
    find . -type f ! -name hosts.yaml ! -name groups.yaml ! -name csr_challenges.yaml \
        ! -name README.md -not -path "./.git/*" ! -name .git -exec rm -f {} +

    # add and commit the initial files if there are changes
    git add hosts.yaml groups.yaml csr_challenges.yaml README.md
    git config user.name "${GIT_COMMIT_NAME:-encompass-bot}"
    git config user.email "${GIT_COMMIT_EMAIL:-encompass@local}"

    # only commit and push if there are changes to avoid unnecessary commits
    if [ -z "$(git status -s)" ]; then
        echo "==> Git-setup: No changes to commit, skipping commit and push"
    else
        git commit -m "Initial commit of hosts.yaml, groups.yaml, csr_challenges.yaml, and README.md"
        if git push origin "$GIT_BRANCH"; then
            echo "==> Git-setup: Successfully pushed initial commit to branch '$GIT_BRANCH'"
        else
            echo "==> Git-setup: [ERROR] Failed to push initial commit to branch '$GIT_BRANCH'"
            exit 1
        fi
    fi
fi


