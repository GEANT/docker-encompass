#!/usr/bin/bash
#
# Start HAProxy only in multi-node mode.
# We cannot use /etc/haproxy/haproxy.cfg existence as a signal because that file
# is shipped by the haproxy package.
#
set -e

trimmed_node_count=$(echo "${MYSQL_NODES:-}" | tr -d '[:space:]' | tr ',' '\n' | grep -c .)

if [ "$trimmed_node_count" -le 1 ]; then
    echo "==> HAProxy: single-node mode detected, skipping"
    exit 0
fi

echo "==> HAProxy: starting for Galera cluster..."
exec /usr/sbin/haproxy -f /etc/haproxy/haproxy.cfg -db
