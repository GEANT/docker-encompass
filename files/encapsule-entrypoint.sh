#!/usr/bin/bash
set -e

export GIT_READ_ONLY=true
/usr/local/bin/git-setup.sh

cd /code/encapsule
export DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-encapsule.settings}"
ENCAPSULE_PORT="${ENCAPSULE_PORT:-8081}"

echo "==> enCapsule: Starting read-only ENC runtime on ${ENCAPSULE_PORT}"
echo "==> enCapsule: Settings module ${DJANGO_SETTINGS_MODULE}"

echo "==> enCapsule: Starting Gunicorn server..."
exec gunicorn --log-level info -b "0.0.0.0:${ENCAPSULE_PORT}" -t 100 --worker-tmp-dir=/dev/shm -w 2 --threads=2 -k gthread encapsule.wsgi:application
