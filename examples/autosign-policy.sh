#!/usr/bin/env bash
#
set -euo pipefail

CERTNAME="${1:-}"
if [[ -z "$CERTNAME" ]]; then
  exit 1
fi

# Store secrets root-only
CSR_API_KEY_FILE="/etc/puppetlabs/puppet/csr_api_key"
ENC_HOST="enc.example.org"
ENC_PORT="8081"

if [[ ! -r "$CSR_API_KEY_FILE" ]]; then
  exit 1
fi
CSR_API_KEY="$(<"$CSR_API_KEY_FILE")"

tmp_csr="$(mktemp)"
trap 'rm -f "$tmp_csr"' EXIT
cat > "$tmp_csr"

# Extract challengePassword from incoming CSR
# (format can vary slightly by openssl version)
csr_challenge="$(openssl req -in "$tmp_csr" -noout -text \
  | awk -F': ' '/challengePassword/ {print $NF; gsub(/^[ \t]+|[ \t]+$/, "", $0); print $0; exit}')"

if [[ -z "$csr_challenge" ]]; then
  exit 1
fi

# Query expected challenge from enCompass/enCapsule
expected_challenge="$(
  timeout 5 /usr/local/bin/encryptor \
    -h "$ENC_HOST" -t "$CSR_API_KEY" --port "$ENC_PORT" --node "$CERTNAME" \
  | awk -F': ' '/challengePassword/ {print $2; gsub(/^[ \t"]+|[ \t"]+$/, "", $2); print $2; exit}'
)"

if [[ -z "$expected_challenge" ]]; then
  exit 1
fi

if [[ "$csr_challenge" == "$expected_challenge" ]]; then
  exit 0
fi

exit 1