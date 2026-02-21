#!/usr/bin/bash
#
set -e
cd /code/encompass

echo "==> enCompass: Using MySQL database backend (${MYSQL_HOST:-undefined}:${MYSQL_PORT:-3306}/${MYSQL_DB:-undefined})"

# apply migrations if needed
if python manage.py showmigrations | grep -q '\[ \]'; then
    echo "==> enCompass: Applying database migrations..."
    python manage.py migrate --noinput
    echo "==> enCompass: Database migrations applied"
else
    echo "==> enCompass: No pending database migrations"
fi

# bootstrap local auth users/groups (idempotent)
if [ "$AUTH_MYSQL_ENABLED" = "true" ]; then
    ADMIN_BOOTSTRAP_PASSWORD="${ENC_BOOTSTRAP_ADMIN_PASSWORD:-admin}"
    VIEWER_BOOTSTRAP_PASSWORD="${ENC_BOOTSTRAP_VIEWER_PASSWORD:-viewer}"
    export ENC_BOOTSTRAP_ADMIN_PASSWORD="$ADMIN_BOOTSTRAP_PASSWORD"
    export ENC_BOOTSTRAP_VIEWER_PASSWORD="$VIEWER_BOOTSTRAP_PASSWORD"

    echo "==> enCompass: Ensuring default local auth groups/users exist..."

    python manage.py shell -c "
import os
from django.contrib.auth.models import User, Group

enc_admin, _ = Group.objects.get_or_create(name='enc_admin')
enc_viewer, _ = Group.objects.get_or_create(name='enc_viewer')

admin_password = os.environ.get('ENC_BOOTSTRAP_ADMIN_PASSWORD', 'admin')
viewer_password = os.environ.get('ENC_BOOTSTRAP_VIEWER_PASSWORD', 'viewer')

admin_user, admin_created = User.objects.get_or_create(username='admin')
if admin_created:
    admin_user.set_password(admin_password)
    admin_user.email = 'admin@local'
    admin_user.is_staff = True
    admin_user.is_superuser = True
    admin_user.save()
admin_user.groups.add(enc_admin)
if admin_created and admin_password == 'admin':
    print('==> WARNING: admin user was created with default password \"admin\"')

viewer_user, viewer_created = User.objects.get_or_create(username='viewer')
if viewer_created:
    viewer_user.set_password(viewer_password)
    viewer_user.email = 'user@local'
    viewer_user.is_staff = False
    viewer_user.is_superuser = False
    viewer_user.save()
viewer_user.groups.add(enc_viewer)
if viewer_created and viewer_password == 'viewer':
    print('==> WARNING: viewer user was created with default password "viewer"')

print('Local auth bootstrap complete')
print(' - admin user: %s' % ('created' if admin_created else 'existing'))
print(' - viewer user: %s' % ('created' if viewer_created else 'existing'))
if (admin_created and admin_password == 'admin') or (viewer_created and viewer_password == 'viewer'):
    print('==> WARNING: Set ENC_BOOTSTRAP_ADMIN_PASSWORD and ENC_BOOTSTRAP_VIEWER_PASSWORD in non-dev environments.')
"
fi

echo "==> enCompass: Collecting static files..."
python manage.py collectstatic --noinput
echo "==> enCompass: Static files collected"

if [ "$DEBUG" = "true" ]; then
    echo "==> enCompass: Debug mode enabled: starting Django development server"
    python3 manage.py runserver "127.0.0.1:8000"
else
    echo "==> enCompass: Starting Gunicorn server..."
    gunicorn --log-level info -b unix:/run/encompass.sock -t 100 --worker-tmp-dir=/dev/shm -w 3 --threads=3 -k gthread encompass.wsgi:application
fi
