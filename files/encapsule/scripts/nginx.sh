#!/usr/bin/bash
#
# This script is the entrypoint for the Nginx container.
# It waits for the enCapsule server to ensure that when NGINX starts
# serving requests, it does not return 503 Service Unavailable.
#
set -e

echo "==> Nginx: Waiting for enCapsule server..."
COUNTER=$SECONDS

until test -S /run/encapsule.sock; do
    sleep .1
    if [ "$SECONDS" -gt "$COUNTER" ]; then
        COUNTER=$SECONDS
        echo "==> Nginx: Still waiting for enCapsule server..."
    fi
done

echo "==> Nginx: enCapsule server is available"
echo "==> Nginx: Starting Nginx..."
exec /usr/sbin/nginx -g "daemon off;"
