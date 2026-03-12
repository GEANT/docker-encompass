"""
Migration to add value_text field to runtime_setting and seed PUPPET_ENVIRONMENTS.
"""

# pylint: disable=invalid-name
import json
from django.db import migrations, models


def seed_puppet_environments(apps, _schema_editor):
    """Seed initial puppet environments setting."""
    runtime_setting = apps.get_model("encompass", "runtime_setting")
    runtime_setting.objects.update_or_create(
        key="PUPPET_ENVIRONMENTS",
        defaults={
            "value_text": json.dumps(["production"]),
            "updated_by": "migration",
        },
    )


class Migration(migrations.Migration):
    """Migration to add value_text field to runtime_setting and seed PUPPET_ENVIRONMENTS."""

    dependencies = [
        ("encompass", "0001_runtime_settings"),
    ]

    operations = [
        migrations.AddField(
            model_name="runtime_setting",
            name="value_text",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.RunPython(seed_puppet_environments, migrations.RunPython.noop),
    ]
