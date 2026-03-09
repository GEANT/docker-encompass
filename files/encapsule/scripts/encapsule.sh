#!/usr/bin/bash
set -e

cd /code/encapsule
export DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-encapsule.settings}"

echo "==> enCapsule: Starting read-only ENC runtime on unix:/run/encapsule.sock"
echo "==> enCapsule: Settings module ${DJANGO_SETTINGS_MODULE}"
echo "==> enCapsule: Starting Gunicorn server..."

exec gunicorn --log-level info -b unix:/run/encapsule.sock -t 100 --worker-tmp-dir=/dev/shm -w 3 --threads=3 -k gthread encapsule.wsgi:application
