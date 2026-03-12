"""Authentication forms for enCompass."""

from __future__ import annotations

from django.contrib.auth.models import Group
from django.contrib.auth.forms import AuthenticationForm


class EncompassAuthenticationForm(AuthenticationForm):
    """Login form that syncs local groups for LDAP-authenticated users."""

    def clean(self):
        cleaned_data = super().clean()
        self._sync_local_groups_from_ldap()
        return cleaned_data

    def _sync_local_groups_from_ldap(self):
        """Mirror LDAP auth result into local Django groups without extra LDAP queries."""
        user = getattr(self, "user_cache", None)
        if user is None:
            return

        backend = str(getattr(user, "backend", "")).strip()
        if backend != "django_auth_ldap.backend.LDAPBackend":
            return

        admin_match = bool(getattr(user, "is_superuser", False))
        viewer_match = bool(getattr(user, "is_viewer", False))
        if not admin_match and not viewer_match:
            # AUTH_LDAP_REQUIRE_GROUP already enforces membership in admin/viewer.
            # If only is_superuser is mapped, treat non-admin LDAP users as viewers.
            viewer_match = True

        enc_admin_group, _ = Group.objects.get_or_create(name="enc_admin")
        enc_viewer_group, _ = Group.objects.get_or_create(name="enc_viewer")

        if admin_match:
            user.groups.add(enc_admin_group)
        else:
            user.groups.remove(enc_admin_group)

        if viewer_match:
            user.groups.add(enc_viewer_group)
        else:
            user.groups.remove(enc_viewer_group)
