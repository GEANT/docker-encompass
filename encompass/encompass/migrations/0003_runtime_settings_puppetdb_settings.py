"""
Add PuppetDB settings to runtime_setting model with initial seeding.
"""

# pylint: disable=invalid-name
from django.db import migrations


def seed_puppetdb_settings(apps, _schema_editor):
    """Seed initial PuppetDB settings."""
    runtime_setting = apps.get_model("encompass", "runtime_setting")
    defaults = {
        "PUPPETDB_SCHEMA": "http",
        "PUPPETDB_HOST": "puppetdb.example.org",
        "PUPPETDB_PORT": "8080",
        "PUPPETDB_TIMEOUT": "20",
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
    """Add PuppetDB settings to runtime_setting model with initial seeding."""

    dependencies = [
        ("encompass", "0002_runtime_settings_value_text_and_puppet_envs"),
    ]

    operations = [
        migrations.RunPython(seed_puppetdb_settings, migrations.RunPython.noop),
    ]
