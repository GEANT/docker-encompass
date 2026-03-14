"""Seed CSR default-profile password runtime setting."""

# pylint: disable=invalid-name
import os
from django.db import migrations


def _env_bool(name, default):
    raw = str(default if default is not None else "false")
    raw = str(os.environ.get(name, raw)).strip().lower()
    return raw in {"1", "true", "yes", "on"}


def seed_csr_default_profile_password_setting(apps, _schema_editor):
    """Seed initial CSR default-profile password runtime setting."""
    runtime_setting = apps.get_model("encompass", "RuntimeSetting")
    runtime_setting.objects.update_or_create(
        key="CSR_PASSWORD_DEFAULT_PROFILE_ENABLED",
        defaults={
            "value_bool": _env_bool("CSR_PASSWORD_DEFAULT_PROFILE_ENABLED", True),
            "updated_by": "migration",
        },
    )


class Migration(migrations.Migration):
    """Add CSR default-profile password runtime setting key."""

    dependencies = [
        ("encompass", "0007_runtime_settings_puppetdb_auth_and_tls"),
    ]

    operations = [
        migrations.RunPython(
            seed_csr_default_profile_password_setting,
            migrations.RunPython.noop,
        ),
    ]
