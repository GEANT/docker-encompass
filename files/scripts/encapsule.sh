#!/usr/bin/bash
set -e

cd /code/encompass
export DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-encompass.agent_settings}"
ENCAPSULE_PORT="${ENCAPSULE_PORT:-8081}"

echo "==> enCapsule: Starting read-only ENC runtime on ${ENCAPSULE_PORT}"
echo "==> enCapsule: Settings module ${DJANGO_SETTINGS_MODULE}"

if [ "$DEBUG" = "true" ]; then
    echo "==> enCapsule: Debug mode enabled: starting Django development server"
    exec python3 manage.py runserver "0.0.0.0:${ENCAPSULE_PORT}"
fi

echo "==> enCapsule: Starting Gunicorn server..."
exec gunicorn --log-level info -b "0.0.0.0:${ENCAPSULE_PORT}" -t 100 --worker-tmp-dir=/dev/shm -w 2 --threads=2 -k gthread encompass.agent_wsgi:application
