"""
Tests for encompass.urls._encompass_admin_has_permission.
"""

import tempfile
from pathlib import Path
from types import SimpleNamespace
from contextlib import nullcontext
from unittest.mock import patch
from django.test import RequestFactory
from django.test import SimpleTestCase, override_settings
from csr_store import csr_attributes
from . import enc_views
from . import tools
from .urls import _encompass_admin_has_permission


class _FakeUser:
    def __init__(self, username, is_active=True, is_staff=True, is_superuser=True):
        self._username = username
        self.is_active = is_active
        self.is_staff = is_staff
        self.is_superuser = is_superuser

    def get_username(self):
        """
        Return the username for this User.
        """
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


class ManualEncapsuleSyncTests(SimpleTestCase):
    """
    Tests for manual enCapsule sync trigger helper.
    """

    @patch("encompass.tests.tools._sync_with_retries")
    @patch("encompass.tests.tools.encapsule_sync_enabled", return_value=True)
    def test_manual_sync_triggers_retries_when_enabled(
        self, _enabled_mock, sync_with_retries_mock
    ):
        """
        When enCapsule sync is enabled, the manual trigger should call the retry logic.
        """
        tools.trigger_encapsule_sync_now()
        sync_with_retries_mock.assert_called_once_with(force_trigger_start=True)

    @patch("encompass.tests.tools._sync_with_retries")
    @patch("encompass.tests.tools.encapsule_sync_enabled", return_value=False)
    def test_manual_sync_skips_retries_when_disabled(
        self, _enabled_mock, sync_with_retries_mock
    ):
        """
        When enCapsule sync is disabled, the manual trigger should not call the retry logic.
        """
        tools.trigger_encapsule_sync_now()
        sync_with_retries_mock.assert_not_called()


class CSRChallengeStoreTests(SimpleTestCase):
    """Tests for encrypted CSR challengePassword storage helpers."""

    @patch("encompass.tests.csr_attributes._db_lock", return_value=nullcontext())
    def test_get_or_create_is_idempotent(self, _lock_mock):
        """get_or_create returns existing value when entity already exists."""
        with tempfile.TemporaryDirectory() as temp_dir:
            store_path = Path(temp_dir) / "csr_challenges.yaml"
            with patch.object(csr_attributes, "CSR_DATA_PATH", store_path):
                with patch.dict("os.environ", {"CSR_CHALLENGE_KEY": "test-key"}):
                    first_value, created_first = csr_attributes.get_or_create(
                        "host/node1.example.org"
                    )
                    second_value, created_second = csr_attributes.get_or_create(
                        "host/node1.example.org"
                    )

        self.assertTrue(created_first)
        self.assertFalse(created_second)
        self.assertEqual(first_value, second_value)

    @patch("encompass.tests.csr_attributes._db_lock", return_value=nullcontext())
    def test_rotate_replaces_value(self, _lock_mock):
        """rotate changes an existing challengePassword value."""
        with tempfile.TemporaryDirectory() as temp_dir:
            store_path = Path(temp_dir) / "csr_challenges.yaml"
            with patch.object(csr_attributes, "CSR_DATA_PATH", store_path):
                with patch.dict("os.environ", {"CSR_CHALLENGE_KEY": "test-key"}):
                    initial, _ = csr_attributes.get_or_create("group/default")
                    rotated = csr_attributes.rotate("group/default")

        self.assertNotEqual(initial, rotated)


class CSRChallengeLifecycleHookTests(SimpleTestCase):
    """Tests ensuring host/group writes create CSR challenge entries."""

    @patch("encompass.tests.tools._sync_after_write")
    @patch("encompass.tests.tools.csr_attributes.get_or_create")
    @patch("encompass.tests.tools.enc_data.save_map")
    @patch("encompass.tests.tools.enc_data.load_map", return_value={"node1": {}})
    @patch("encompass.tests.tools.enc_data.data_lock", return_value=nullcontext())
    def test_update_host_calls_get_or_create(
        self,
        _lock_mock,
        _load_map_mock,
        _save_map_mock,
        get_or_create_mock,
        _sync_mock,
    ):
        """Updating a host creates the CSR challenge entry only if missing."""
        tools.update_host("node1", {"environment": "production"})
        get_or_create_mock.assert_called_once_with("host/node1")

    @patch("encompass.tests.tools._sync_after_write")
    @patch("encompass.tests.tools.csr_attributes.get_or_create")
    @patch("encompass.tests.tools.validate_group_selector_overlaps")
    @patch("encompass.tests.tools.enc_data.save_map")
    @patch("encompass.tests.tools.enc_data.load_map", return_value={"default": {}})
    @patch("encompass.tests.tools.enc_data.data_lock", return_value=nullcontext())
    def test_update_group_calls_get_or_create(
        self,
        _lock_mock,
        _load_map_mock,
        _save_map_mock,
        _validate_overlap_mock,
        get_or_create_mock,
        _sync_mock,
    ):
        """Updating a group creates the CSR challenge entry only if missing."""
        tools.update_group(
            "default",
            {"environment": "production", "classes": [], "hosts": []},
        )
        get_or_create_mock.assert_called_once_with("group/default")


class CSRAttributesApiTests(SimpleTestCase):
    """Tests for CSR custom_attributes API endpoints."""

    def setUp(self):
        self.factory = RequestFactory()

    @patch("encompass.tests.csr_attributes.get_or_create")
    def test_host_csr_attributes_returns_yaml_payload(self, get_or_create_mock):
        """Host CSR endpoint returns YAML with custom_attributes.challengePassword."""
        get_or_create_mock.return_value = ("secure_password", False)

        with patch.dict("os.environ", {"CSR_API_KEY": "test-token"}):
            response = enc_views.host_csr_attributes(
                self.factory.get(
                    "/hosts/node1.example.org/csr_attributes",
                    HTTP_X_CSR_API_KEY="test-token",
                ),
                "node1.example.org",
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/yaml")
        self.assertTrue(response.content.decode("utf-8").startswith("---\n"))
        self.assertIn("custom_attributes", response.content.decode("utf-8"))
        self.assertIn("challengePassword: secure_password", response.content.decode("utf-8"))
        get_or_create_mock.assert_called_once_with("host/node1.example.org")

    @patch("encompass.tests.csr_attributes.get_or_create")
    def test_group_csr_attributes_returns_yaml_payload(self, get_or_create_mock):
        """Group CSR endpoint returns YAML with custom_attributes.challengePassword."""
        get_or_create_mock.return_value = ("group_secret", False)

        with patch.dict("os.environ", {"CSR_API_KEY": "test-token"}):
            response = enc_views.group_csr_attributes(
                self.factory.get(
                    "/groups/default/csr_attributes",
                    HTTP_X_CSR_API_KEY="test-token",
                ),
                "default",
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content.decode("utf-8").startswith("---\n"))
        self.assertIn("challengePassword: group_secret", response.content.decode("utf-8"))
        get_or_create_mock.assert_called_once_with("group/default")

    def test_host_csr_attributes_rejects_non_get(self):
        """Host CSR endpoint only supports GET."""
        response = enc_views.host_csr_attributes(
            self.factory.post("/hosts/node1.example.org/csr_attributes"),
            "node1.example.org",
        )
        self.assertEqual(response.status_code, 405)

    @patch("encompass.tests.csr_attributes.get_or_create")
    def test_group_csr_attributes_allows_public_proxy(self, get_or_create_mock):
        """CSR endpoint remains reachable when requests come via public proxy."""
        get_or_create_mock.return_value = ("group_secret", False)
        with patch.dict("os.environ", {"CSR_API_KEY": "test-token"}):
            request = self.factory.get(
                "/groups/default/csr_attributes",
                HTTP_X_EXTERNAL_PROXY="1",
                HTTP_X_CSR_API_KEY="test-token",
            )
            response = enc_views.group_csr_attributes(request, "default")
        self.assertEqual(response.status_code, 200)
        self.assertIn("challengePassword: group_secret", response.content.decode("utf-8"))

    def test_host_csr_attributes_rejects_missing_token(self):
        """Host CSR endpoint rejects requests without API token."""
        with patch.dict("os.environ", {"CSR_API_KEY": "test-token"}):
            response = enc_views.host_csr_attributes(
                self.factory.get("/hosts/node1.example.org/csr_attributes"),
                "node1.example.org",
            )
        self.assertEqual(response.status_code, 403)

    def test_group_csr_attributes_rejects_invalid_token(self):
        """Group CSR endpoint rejects requests with wrong API token."""
        with patch.dict("os.environ", {"CSR_API_KEY": "test-token"}):
            response = enc_views.group_csr_attributes(
                self.factory.get(
                    "/groups/default/csr_attributes",
                    HTTP_X_CSR_API_KEY="wrong-token",
                ),
                "default",
            )
        self.assertEqual(response.status_code, 403)
