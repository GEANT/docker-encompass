#!/usr/bin/bash
#
set -e

if [ "$DEBUG" = "true" ]; then
    until nc -z 127.0.0.1 8000 >/dev/null 2>&1; do
        echo "==> Nginx: Waiting for enCompass development server..."
        sleep 1
    done
    echo "==> Nginx: enCompass development server is available"
else
    until test -S /run/encompass.sock; do
        echo "==> Nginx: Waiting for enCompass server..."
        sleep 1
    done
    echo "==> Nginx: enCompass server is available"
fi

if [ "$USE_SQLITE_WEB" = "true" ]; then
    until nc -z 127.0.0.1 8002 >/dev/null 2>&1; do
        echo "==> Nginx: Waiting for sqlite-web service..."
        sleep 1
    done
    echo "==> Nginx: sqlite-web service is available"
fi

echo "==> Nginx: Starting Nginx..."
exec /usr/sbin/nginx -g "daemon off;"