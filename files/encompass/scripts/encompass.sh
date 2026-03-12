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

echo "==> enCompass: Ensuring default local auth groups/users exist..."

# shellcheck disable=SC2140,1078,1079
python manage.py shell -c "
from django.contrib.auth.models import User, Group

enc_admin, _ = Group.objects.get_or_create(name='enc_admin')
enc_viewer, _ = Group.objects.get_or_create(name='enc_viewer')

admin_password = 'admin'
viewer_password = 'viewer'

admin_user, admin_created = User.objects.get_or_create(username='admin')
if admin_created:
    admin_user.set_password(admin_password)
    admin_user.email = 'admin@local'
    admin_user.is_staff = True
    admin_user.is_superuser = True
    admin_user.save()
admin_user.groups.add(enc_admin)
if admin_created:
    print('==> WARNING: admin user was created with initial password "admin"')

viewer_user, viewer_created = User.objects.get_or_create(username='viewer')
if viewer_created:
    viewer_user.set_password(viewer_password)
    viewer_user.email = 'user@local'
    viewer_user.is_staff = False
    viewer_user.is_superuser = False
    viewer_user.save()
viewer_user.groups.add(enc_viewer)
if viewer_created:
    print('==> WARNING: viewer user was created with initial password "viewer"')

print('Local auth bootstrap complete')
print(' - admin user: %s' % ('created' if admin_created else 'existing'))
print(' - viewer user: %s' % ('created' if viewer_created else 'existing'))
if admin_created or viewer_created:
    print('==> WARNING: Change initial local passwords immediately from User Settings.')
"

echo "==> enCompass: Collecting static files..."
python manage.py collectstatic --noinput
chmod a+rx /code /code/static /code/static/static
chmod -R a+rX /code/static/static
echo "==> enCompass: Static files collected"

if [ "$DEBUG" = "true" ]; then
    echo "==> enCompass: Debug mode enabled: starting Django development server"
    python3 manage.py runserver "127.0.0.1:8000"
else
    echo "==> enCompass: Starting Gunicorn server..."
    gunicorn --log-level info -b unix:/run/encompass.sock -t 100 --worker-tmp-dir=/dev/shm -w 3 --threads=3 -k gthread encompass.wsgi:application
fi
