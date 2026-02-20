#!/usr/bin/bash
#
set -e

until test -S /run/static.sock; do
    echo "==> HAProxy: Waiting for Static service..."
    sleep 1
done
echo "==> HAProxy: Static service is available"

until test -S /run/enc.sock; do
    echo "==> HAProxy: Waiting for ENC service..."
    sleep 1
done
echo "==> HAProxy: ENC service is available"

if [ "$DEBUG" = "true" ]; then
    until nc -z 127.0.0.1 8000 &>/dev/null; do
        echo "==> HAProxy: Waiting for enCompass development server..."
        sleep 1
    done
    echo "==> HAProxy: enCompass development server is available"
else
    until test -S /run/encompass.sock; do
        echo "==> HAProxy: Waiting for enCompass server..."
        sleep 1
    done
    echo "==> HAProxy: enCompass server is available"
fi

if [ "$USE_SQLITE_WEB" = "true" ]; then
    until nc -z 127.0.0.1 8002 &>/dev/null; do
        echo "==> HAProxy: Waiting for Sqlite-web service..."
        sleep 1
    done
    echo "==> HAProxy: Sqlite-web service is available"
fi

echo "==> HAProxy: Starting HAProxy..."
/usr/sbin/haproxy -W -f /etc/haproxy/haproxy.cfg
