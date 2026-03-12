"""
Migration to add Encapsule sync settings to runtime_setting model.
"""

# pylint: disable=invalid-name
import os
from django.db import migrations


def seed_encapsule_sync_settings(apps, _schema_editor):
    """Seed initial enCapsule sync settings with environment variable overrides."""
    runtime_setting = apps.get_model("encompass", "runtime_setting")
    defaults = {
        "ENCAPSULE_SYNC_SCHEME": str(
            os.environ.get("ENCAPSULE_SYNC_SCHEME", "http")
        ).strip()
        or "http",
        "ENCAPSULE_SYNC_TIMEOUT": str(
            os.environ.get("ENCAPSULE_SYNC_TIMEOUT", "5")
        ).strip()
        or "5",
        "ENCAPSULE_SYNC_PORT": str(os.environ.get("ENCAPSULE_SYNC_PORT", "8081")).strip()
        or "8081",
        "ENCAPSULE_SYNC_USE_SRV": str(
            os.environ.get("ENCAPSULE_SYNC_USE_SRV", "false")
        ).strip().lower()
        or "false",
        "ENCAPSULE_SYNC_HOST": str(
            os.environ.get("ENCAPSULE_SYNC_HOST", "encapsule.example.org")
        ).strip()
        or "encapsule.example.org",
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
    """Migration to add enCapsule sync settings to runtime_setting model."""

    dependencies = [
        ("encompass", "0004_runtime_settings_clear_seeded_puppetdb_values"),
    ]

    operations = [
        migrations.RunPython(seed_encapsule_sync_settings, migrations.RunPython.noop),
    ]
