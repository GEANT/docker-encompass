#!/usr/bin/bash
#
set -e
cd /code/encompass

# create DB if missing
if [ -f /sqlite/db.sqlite3 ]; then
    echo "==> enCompass: Database file found at /sqlite/db.sqlite3"
else
    echo "==> enCompass: Creating new database file..."
    sqlite3 /sqlite/db.sqlite3 "VACUUM;"
    echo "==> enCompass: Database file created at /sqlite/db.sqlite3"
fi

# apply migrations if needed
if python manage.py showmigrations | grep -q '\[ \]'; then
    echo "==> enCompass: Applying database migrations..."
    python manage.py migrate --noinput
    echo "==> enCompass: Database migrations applied"
else
    echo "==> enCompass: No pending database migrations"
fi

if [ "$DEBUG" = "true" ]; then
    echo "==> enCompass: Debug mode enabled: starting Django development server"
    python3 manage.py runserver "127.0.0.1:8000"
else
    echo "==> enCompass: Starting Gunicorn server..."
    gunicorn --log-level info -b unix:/run/encompass.sock -t 100 --worker-tmp-dir=/dev/shm -w 3 --threads=3 -k gthread encompass.wsgi:application
fi
