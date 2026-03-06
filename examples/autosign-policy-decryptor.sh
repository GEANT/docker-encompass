#!/usr/bin/env bash
set -euo pipefail

CERTNAME="${1:-}"
if [[ -z "$CERTNAME" ]]; then
  exit 1
fi

exec /usr/local/bin/decryptor "$CERTNAME"
