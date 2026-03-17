"""Clear seeded enCapsule sync text values to rely on UI placeholders."""

# pylint: disable=invalid-name
from django.db import migrations


ENCAPSULE_SYNC_KEYS = [
    "ENCAPSULE_SYNC_SCHEME",
    "ENCAPSULE_SYNC_TIMEOUT",
    "ENCAPSULE_SYNC_PORT",
    "ENCAPSULE_SYNC_USE_SRV",
    "ENCAPSULE_SYNC_HOST",
]


def clear_seeded_encapsule_sync_values(apps, _schema_editor):
    """Clear migration-seeded enCapsule sync text values."""
    runtime_setting = apps.get_model("encompass", "RuntimeSetting")
    runtime_setting.objects.filter(
        key__in=ENCAPSULE_SYNC_KEYS,
        updated_by="migration",
    ).update(value_text="")


class Migration(migrations.Migration):
    """Clear seeded enCapsule sync text values from runtime settings."""

    dependencies = [
        ("encompass", "0008_runtime_settings_csr_default_profile_password"),
    ]

    operations = [
        migrations.RunPython(
            clear_seeded_encapsule_sync_values,
            migrations.RunPython.noop,
        ),
    ]
