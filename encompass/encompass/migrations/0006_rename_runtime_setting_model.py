"""
Rename runtime_setting model class to RuntimeSetting.
"""

# pylint: disable=invalid-name
from django.db import migrations


class Migration(migrations.Migration):
    """Rename runtime_setting to RuntimeSetting while keeping the same db_table."""

    dependencies = [
        ("encompass", "0005_runtime_settings_encapsule_sync_settings"),
    ]

    operations = [
        migrations.RenameModel(
            old_name="runtime_setting",
            new_name="RuntimeSetting",
        ),
    ]
