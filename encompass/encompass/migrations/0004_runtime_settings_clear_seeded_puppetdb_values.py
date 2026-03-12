"""
Migration to clear seeded PuppetDB values from runtime_setting model.
"""

# pylint: disable=invalid-name
from django.db import migrations


def clear_seeded_puppetdb_values(apps, _schema_editor):
    """Clear seeded PuppetDB values from runtime_setting model."""
    runtime_setting = apps.get_model("encompass", "runtime_setting")
    keys = [
        "PUPPETDB_SCHEMA",
        "PUPPETDB_HOST",
        "PUPPETDB_PORT",
        "PUPPETDB_TIMEOUT",
    ]
    runtime_setting.objects.filter(
        key__in=keys,
        updated_by="migration",
    ).update(value_text="")


class Migration(migrations.Migration):
    """Migration to clear seeded PuppetDB values from runtime_setting model."""

    dependencies = [
        ("encompass", "0003_runtime_settings_puppetdb_settings"),
    ]

    operations = [
        migrations.RunPython(clear_seeded_puppetdb_values, migrations.RunPython.noop),
    ]
