#!/usr/bin/bash
#
# This script is the entrypoint for the Nginx container.
# It waits for the enCompass server to ensure that when NGINX starts
# serving requests, it does not return 503 Service Unavailable.
#
set -e

if [ "$DEBUG" = "true" ]; then
    until nc -z 127.0.0.1 8000 >/dev/null 2>&1; do
        echo "==> Nginx: Waiting for enCompass development server..."
        sleep .5
    done
    echo "==> Nginx: enCompass development server is available"
else
    until test -S /run/encompass.sock; do
        echo "==> Nginx: Waiting for enCompass server..."
        sleep .5
    done
    echo "==> Nginx: enCompass server is available"
fi

echo "==> Nginx: Starting Nginx..."
exec /usr/sbin/nginx -g "daemon off;"
