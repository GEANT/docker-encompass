# enCompass Development

enCompass is a Django-based Puppet External Node Classifier (ENC) packaged for Docker.
It provides a web UI to manage hosts and groups, plus read-only ENC endpoints for external consumers.

Demo site: [encompass-demo.geant.org](https://encompass-demo.geant.org/)

## Index

- [Development Notes](#development-notes)
- [Local Python Run (Optional)](#local-python-run-optional)
- [Troubleshooting](#troubleshooting)
- [ToDo](#todo)

## Development Notes

- In debug mode, Django dev server is used internally.
- In non-debug mode, Gunicorn serves Django behind Nginx.
- Static files are collected automatically on container startup.
- Database migrations are applied automatically when pending.

## Local Python Run (Optional)

Use this only if you are developing outside Docker:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cd encompass
python manage.py migrate
python manage.py runserver
```

## Troubleshooting

- `403` on `/hosts` or `/groups` via ENC endpoint:
  expected behavior for external proxy paths.
- `409 Conflict` on `/hosts` or `/groups` writes:
  another write operation currently holds the lock; retry the request.
- Login issues with LDAP:
  verify `LDAP_*` values and directory reachability from the container.
- SSL startup failure:
  confirm certificate/key files exist and are readable in container paths.
- Nginx error `stat() ... /code/static/static/... failed (13: Permission denied)` and broken CSS:
  static permissions were too restrictive; startup now normalizes `/code/static/static` with `a+rX` after `collectstatic` (common with strict Nomad/Kubernetes `umask`).

## ToDo

- git commit on save and git pull before rendering the tables
- regex for hosts in groups.yaml
