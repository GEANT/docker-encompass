#!/usr/bin/bash
#
# This script is the entrypoint for the Nginx container.
# It waits for the enCapsule server to ensure that when NGINX starts
# serving requests, it does not return 503 Service Unavailable.
#
set -e

until test -S /run/encapsule.sock; do
    echo "==> Nginx: Waiting for enCapsule server..."
    sleep .3
done

echo "==> Nginx: enCapsule server is available"
echo "==> Nginx: Starting Nginx..."
exec /usr/sbin/nginx -g "daemon off;"
