from django.db import migrations, models
import json


def seed_puppet_environments(apps, _schema_editor):
    RuntimeSetting = apps.get_model("encompass", "RuntimeSetting")
    RuntimeSetting.objects.update_or_create(
        key="PUPPET_ENVIRONMENTS",
        defaults={
            "value_text": json.dumps(["production"]),
            "updated_by": "migration",
        },
    )


def noop_reverse(_apps, _schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("encompass", "0001_runtime_settings"),
    ]

    operations = [
        migrations.AddField(
            model_name="runtimesetting",
            name="value_text",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.RunPython(seed_puppet_environments, noop_reverse),
    ]
