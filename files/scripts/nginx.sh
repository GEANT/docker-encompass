#!/usr/bin/bash
#
set -e

if [ "$DEBUG" = "true" ]; then
    echo "==> Nginx: Waiting for enCompass development server..."
    until nc -z 127.0.0.1 8000 >/dev/null 2>&1; do
        echo "==> Nginx: Waiting for enCompass development server..."
        sleep .3
    done
    echo "==> Nginx: enCompass development server is available"
else
    echo "==> Nginx: Waiting for enCompass server..."
    until test -S /run/encompass.sock; do
        echo "==> Nginx: Waiting for enCompass server..."
        sleep .3
    done
    echo "==> Nginx: enCompass server is available"
fi

echo "==> Nginx: Starting Nginx..."
exec /usr/sbin/nginx -g "daemon off;"
