#!/usr/bin/env bash
#
# NOTE: a compiled Go binary (puppet-enc) is available as a faster, dependency-free"
# drop-in replacement for this script. Pre-built binaries for Linux and macOS can be"
# fetched from Codeberg:"
# https://codeberg.org/GEANT/-/packages"
#
set -o errexit
set -o nounset
set -o pipefail

RED='\033[0;31m'
NC='\033[0m'

for cmd in dig curl; do
    if ! command -v "$cmd" &> /dev/null; then
        echo -e "${RED}Error${NC}: $cmd is required but not installed. Please install $cmd and try again."
        exit 1
    fi
done

usage() {
    [[ "$#" -eq 2 ]] && echo -e "$2" # print a message passed as argument
    echo ""
    echo "Usage: $(basename "$0") --node <node> --server <hostname> [--srv | --rrdns --port <port> | --port <port>] [--user <username> --password <password>]"
    echo "       $(basename "$0") -h | --help"
    echo ""
    echo "  -n | --node      Node to query"
    echo "  -s | --server    Server hostname/IP to connect"
    echo "  -u | --user      Username (jointly required with --password)"
    echo "  -p | --password  Password (jointly required with --user)"
    echo "  --srv            Resolve endpoint via SRV record _enc-server._tcp.example.org"
    echo "  --rrdns          Resolve <server> to multiple A/AAAA records and try each with --port"
    echo "  --port           Static port (required for non-SRV mode)"
    echo ""
    echo "  NOTE: a compiled Go binary (puppet-enc) is available as a faster, dependency-free"
    echo "  drop-in replacement for this script. Pre-built binaries for Linux and macOS can be"
    echo "  fetched from Codeberg:"
    echo "  https://codeberg.org/GEANT/-/packages"
    echo ""
    [[ "$#" -gt 0 ]] && exit "$1"
    exit
}

ERR=$(getopt -Q -o "hn:s:u:p:" --longoptions "help,node:,server:,user:,password:,srv,rrdns,port:" -- "$@" 2>&1)
[ $? -ne 0 ] && usage 3 "\n${RED}Error${NC}: $ERR"
OPTS=$(getopt -o "hn:s:u:p:" --longoptions "help,node:,server:,user:,password:,srv,rrdns,port:" -- "$@")
eval set -- "$OPTS"

while true; do
    case "$1" in
    -h | --help)
        usage 3
        ;;
    -n | --node)
        shift
        ENC_NODE="$1"
        ;;
    -s | --server)
        shift
        ENC_SERVER="$1"
        ;;
    -u | --user)
        shift
        ENC_USER="$1"
        ;;
    -p | --password)
        shift
        ENC_PASSWORD="$1"
        ;;
    --srv)
        ENC_SRV="true"
        ;;
    --rrdns)
        ENC_RRDNS="true"
        ;;
    --port)
        shift
        ENC_PORT="$1"
        ;;
    --)
        shift
        break
        ;;
    esac
    shift
done

[ -z "${ENC_SERVER:-}" ] && usage 3 "\n${RED}Error${NC}: --server option must be provided"
[ -z "${ENC_NODE:-}" ] && usage 3 "\n${RED}Error${NC}: --node option must be provided"

if { [ -n "${ENC_USER:-}" ] && [ -z "${ENC_PASSWORD:-}" ]; } || \
    { [ -z "${ENC_USER:-}" ] && [ -n "${ENC_PASSWORD:-}" ]; }; then
    usage 3 "\n${RED}Error${NC}: Both --user and --password options must be provided together"
fi

if { [ -n "${ENC_SRV:-}" ] && [ -n "${ENC_RRDNS:-}" ]; }; then
    usage 3 "\n${RED}Error${NC}: --srv and --rrdns are mutually exclusive"
fi

if { [ -n "${ENC_SRV:-}" ] && [ -n "${ENC_PORT:-}" ]; }; then
    usage 3 "\n${RED}Error${NC}: --srv and --port are mutually exclusive"
fi

if [ -z "${ENC_SRV:-}" ] && [ -z "${ENC_PORT:-}" ]; then
    usage 3 "\n${RED}Error${NC}: --port is required unless --srv is used"
fi

if [ -n "${ENC_PORT:-}" ] && ! [[ "$ENC_PORT" =~ ^[0-9]+$ ]] ; then
    usage 3 "\n${RED}Error${NC}: --port must be numeric"
fi

if [ -n "${ENC_SRV:-}" ]; then
    record=$(dig +short _puppet8._tcp."$ENC_SERVER" SRV | shuf -n 1)
    host=$(echo "$record" | awk '{print $4}' | sed 's/\.$//')
    port=$(echo "$record" | awk '{print $3}')
else
    host="$ENC_SERVER"
    port="$ENC_PORT"
fi

if [ -z "${host:-}" ] || [ -z "${port:-}" ]; then
    usage 3 "\n${RED}Error${NC}: Failed to resolve server address and port"
fi

declare -a targets
if [ -n "${ENC_RRDNS:-}" ]; then
    while IFS= read -r ip; do
        [ -n "$ip" ] && targets+=("$ip")
    done < <(dig +short "$ENC_SERVER" A)
    while IFS= read -r ip6; do
        [ -n "$ip6" ] && targets+=("[$ip6]")
    done < <(dig +short "$ENC_SERVER" AAAA)

    if [ "${#targets[@]}" -eq 0 ]; then
        usage 3 "\n${RED}Error${NC}: --rrdns enabled but no A/AAAA records found for $ENC_SERVER"
    fi
else
    targets=("$host")
fi

curl_enc() {
    local target="$1"
    local url="http://${target}:${port}/hosts/${ENC_NODE}"
    if [ -n "${ENC_USER:-}" ]; then
        curl -fsS --connect-timeout 5 --max-time 20 -u "$ENC_USER:$ENC_PASSWORD" "$url"
    else
        curl -fsS --connect-timeout 5 --max-time 20 "$url"
    fi
}

last_error=""
for target in "${targets[@]}"; do
    if output=$(curl_enc "$target" 2>&1); then
        printf '%s\n' "$output"
        exit 0
    fi
    last_error="$output"
done

usage 2 "\n${RED}Error${NC}: Failed to query ENC (${last_error})"
