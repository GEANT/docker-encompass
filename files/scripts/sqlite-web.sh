#!/usr/bin/bash
#
set -e

[ "$USE_SQLITE_WEB" = "true" ] || exit 0

# wait for the database file to be available
until test -f /sqlite/db.sqlite3; do
    sleep 1
    echo "==> sqlite-web: Waiting for database file..."
done
echo "==> sqlite-web: Database file found at /sqlite/db.sqlite3"

if [ -n "$SQLITE_WEB_PASSWORD" ]; then
    echo "==> Sqlite-web: Starting Sqlite-web with authentication enabled"
    PASSWORD_OPTION="--password"
else
    echo "==> Sqlite-web: Starting Sqlite-web with authentication disabled"
fi

python /usr/local/bin/sqlite_wsgi -p 8002 --no-browser ${PASSWORD_OPTION:+-} /sqlite/db.sqlite3
