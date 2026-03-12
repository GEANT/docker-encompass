"""Database models for enCompass runtime configuration."""

from django.db import models


class RuntimeSetting(models.Model):
    """Stores boolean runtime toggles managed from the UI."""

    objects = models.Manager()

    key = models.CharField(max_length=64, unique=True)
    value_bool = models.BooleanField(default=False)
    updated_by = models.CharField(max_length=150, blank=True, default="system")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "runtime_settings"
        verbose_name = "Runtime setting"
        verbose_name_plural = "Runtime settings"

    def __str__(self):
        return f"{self.key}={self.value_bool}"
