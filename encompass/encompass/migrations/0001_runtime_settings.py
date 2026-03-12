from django.db import migrations, models


def _env_bool(name, default):
    raw = str(default if default is not None else "false")
    raw = str(__import__("os").environ.get(name, raw)).strip().lower()
    return raw in {"1", "true", "yes", "on"}


def seed_runtime_settings(apps, _schema_editor):
    RuntimeSetting = apps.get_model("encompass", "RuntimeSetting")
    defaults = {
        "UNCLASSIFIED_HOSTS_ENABLED": _env_bool("UNCLASSIFIED_HOSTS_ENABLED", True),
        "FEATURE_BRANCH": _env_bool("FEATURE_BRANCH", False),
        "ENC_OVERLAPPING_DEFINITIONS_ENABLED": _env_bool(
            "ENC_OVERLAPPING_DEFINITIONS_ENABLED", False
        ),
        "USE_ENCAPSULE": _env_bool("USE_ENCAPSULE", True),
        "AUTH_LDAP_ENABLED": _env_bool("AUTH_LDAP_ENABLED", False),
        "LDAP_TLS_SKIP_VERIFY": _env_bool("LDAP_TLS_SKIP_VERIFY", False),
    }
    for key, value in defaults.items():
        RuntimeSetting.objects.update_or_create(
            key=key,
            defaults={"value_bool": value, "updated_by": "migration"},
        )


def noop_reverse(_apps, _schema_editor):
    pass


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="RuntimeSetting",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("key", models.CharField(max_length=64, unique=True)),
                ("value_bool", models.BooleanField(default=False)),
                (
                    "updated_by",
                    models.CharField(blank=True, default="system", max_length=150),
                ),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Runtime setting",
                "verbose_name_plural": "Runtime settings",
                "db_table": "runtime_settings",
            },
        ),
        migrations.RunPython(seed_runtime_settings, noop_reverse),
    ]
