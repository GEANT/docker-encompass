"""
Tests for encompass.urls._encompass_admin_has_permission.
"""

from types import SimpleNamespace
from django.test import SimpleTestCase, override_settings
from .urls import _encompass_admin_has_permission


class _FakeUser:
    def __init__(self, username, is_active=True, is_staff=True, is_superuser=True):
        self._username = username
        self.is_active = is_active
        self.is_staff = is_staff
        self.is_superuser = is_superuser

    def get_username(self):
        """Return the username for this User."""
        return self._username


class AdminAccessPermissionTests(SimpleTestCase):
    """
    Tests for the custom admin permission logic in encompass.urls._encompass_admin_has_permission.
    """

    @override_settings(USE_AUTH_MYSQL=True)
    def test_db_auth_allows_only_admin_username(self):
        """
        With DB auth enabled, only the user with username "admin" should have admin access.
        """
        admin_request = SimpleNamespace(user=_FakeUser("admin"))
        alice_request = SimpleNamespace(user=_FakeUser("alice"))

        self.assertTrue(_encompass_admin_has_permission(admin_request))
        self.assertFalse(_encompass_admin_has_permission(alice_request))

    @override_settings(USE_AUTH_MYSQL=False)
    def test_non_db_auth_keeps_default_superuser_behavior(self):
        """
        With DB auth disabled, the default superuser behavior should be maintained.
        """
        ldap_request = SimpleNamespace(user=_FakeUser("alice"))
        self.assertTrue(_encompass_admin_has_permission(ldap_request))

    @override_settings(USE_AUTH_MYSQL=True)
    def test_inactive_or_non_staff_or_non_superuser_are_denied(self):
        """
        Even with DB auth enabled, users that are inactive, non-staff
        or non-superusers should be denied access.
        """
        inactive_request = SimpleNamespace(user=_FakeUser("admin", is_active=False))
        non_staff_request = SimpleNamespace(user=_FakeUser("admin", is_staff=False))
        non_superuser_request = SimpleNamespace(
            user=_FakeUser("admin", is_superuser=False)
        )

        self.assertFalse(_encompass_admin_has_permission(inactive_request))
        self.assertFalse(_encompass_admin_has_permission(non_staff_request))
        self.assertFalse(_encompass_admin_has_permission(non_superuser_request))
