"""Seed PuppetDB auth and TLS runtime settings."""

# pylint: disable=invalid-name
from django.db import migrations


def seed_puppetdb_auth_and_tls_settings(apps, _schema_editor):
    """Seed initial PuppetDB auth and TLS settings."""
    runtime_setting = apps.get_model("encompass", "RuntimeSetting")
    defaults = {
        "PUPPETDB_AUTH_METHOD": "none",
        "PUPPETDB_AUTH_HEADER": "Authorization",
        "PUPPETDB_AUTH_TOKEN": "",
        "PUPPETDB_BASIC_USERNAME": "",
        "PUPPETDB_BASIC_PASSWORD": "",
        "PUPPETDB_CLIENT_CERT_PATH": "",
        "PUPPETDB_CLIENT_KEY_PATH": "",
        "PUPPETDB_CA_CERT_PATH": "",
        "PUPPETDB_TLS_SKIP_VERIFY": "false",
    }
    for key, value in defaults.items():
        runtime_setting.objects.update_or_create(
            key=key,
            defaults={
                "value_text": value,
                "updated_by": "migration",
            },
        )


class Migration(migrations.Migration):
    """Add PuppetDB auth and TLS runtime settings keys."""

    dependencies = [
        ("encompass", "0006_rename_runtime_setting_model"),
    ]

    operations = [
        migrations.RunPython(
            seed_puppetdb_auth_and_tls_settings,
            migrations.RunPython.noop,
        ),
    ]
