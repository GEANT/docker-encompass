"""Seed Git sync runtime settings."""

# pylint: disable=invalid-name
from django.db import migrations


GIT_SYNC_DEFAULTS = {
    "GIT_SYNC_MODE": "sync",
    "GIT_SYNC_TIMEOUT": "30",
    "GIT_SYNC_RETRIES": "2",
    "GIT_SYNC_RETRY_DELAY": "2",
}


def seed_git_sync_settings(apps, _schema_editor):
    """Create missing Git sync runtime settings with safe defaults."""
    runtime_setting = apps.get_model("encompass", "RuntimeSetting")
    for key, value in GIT_SYNC_DEFAULTS.items():
        runtime_setting.objects.get_or_create(
            key=key,
            defaults={
                "value_text": value,
                "updated_by": "migration",
            },
        )


class Migration(migrations.Migration):
    """Add Git sync runtime setting keys."""

    dependencies = [
        ("encompass", "0009_runtime_settings_clear_seeded_encapsule_sync_values"),
    ]

    operations = [
        migrations.RunPython(seed_git_sync_settings, migrations.RunPython.noop),
    ]
