#!/usr/bin/env bash

set -euo pipefail

if git symbolic-ref --quiet HEAD >/dev/null 2>&1; then
    branch_name="$(git branch --show-current)"
    echo "Running on ${branch_name} branch"
    cat <<'EOF' >files/deployment-stuff/watermark
<li class="nav-item">
  <a class="nav-link disabled text-danger" href="#">&nbsp;&nbsp;&nbsp;&nbsp;DEV Env.</a>
</li>
EOF
    echo "dev-version" >files/deployment-stuff/version
else
    tag_name="$(git describe --tags --exact-match 2>/dev/null || true)"
    if [ -z "$tag_name" ]; then
        echo "Error: HEAD is detached but no exact tag points to this commit" >&2
        exit 1
    fi
    echo "Running on ${tag_name} tag"
    echo '<!-- I_AM_A_PLACE_HOLDER -->' >files/deployment-stuff/watermark
    echo "$tag_name" >files/deployment-stuff/version
fi
