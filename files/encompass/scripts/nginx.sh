#!/usr/bin/bash
#
# This script is the entrypoint for the Nginx container.
# It waits for the enCompass server to ensure that when NGINX starts
# serving requests, it does not return 503 Service Unavailable.
#
set -e

COUNTER=$SECONDS

if [ "$DEBUG" = "true" ]; then
    echo "==> Nginx: Waiting for enCompass development server..."
    until nc -z 127.0.0.1 8000 >/dev/null 2>&1; do
        sleep .1
        if [ "$SECONDS" -gt "$COUNTER" ]; then
            COUNTER=$SECONDS
            echo "==> Nginx: Still waiting for enCapsule server..."
        fi
    done
    echo "==> Nginx: enCompass development server is available"
else
    echo "==> Nginx: Waiting for enCompass server..."
    until test -S /run/encompass.sock; do
        sleep .1
        if [ "$SECONDS" -gt "$COUNTER" ]; then
            COUNTER=$SECONDS
            echo "==> Nginx: Still waiting for enCapsule server..."
        fi
    done
    echo "==> Nginx: enCompass server is available"
fi

echo "==> Nginx: Starting Nginx..."
exec /usr/sbin/nginx -g "daemon off;"
