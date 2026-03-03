"""Authentication forms for enCompass."""

from __future__ import annotations

import os
import re

import ldap
import ldap.filter
from django.contrib.auth.forms import AuthenticationForm
from django.core.exceptions import ValidationError


LDAP_OPT_PROTOCOL_VERSION = getattr(ldap, "OPT_PROTOCOL_VERSION", 3)
LDAP_OPT_REFERRALS = getattr(ldap, "OPT_REFERRALS", 0)
LDAP_SCOPE_SUBTREE = getattr(ldap, "SCOPE_SUBTREE", 2)


class EncompassAuthenticationForm(AuthenticationForm):
    """Login form with best-effort LDAP password-expiry detection for AD."""

    def clean(self):
        username = str(self.data.get("username", "")).strip()
        password = str(self.data.get("password", ""))

        try:
            return super().clean()
        except ValidationError as exc:
            if self._is_password_expired(username, password):
                raise ValidationError(self._expired_password_message()) from exc
            raise

    def _expired_password_message(self) -> str:
        reset_url = str(os.environ.get("LDAP_PASSWORD_RESET_URL", "")).strip()
        if reset_url:
            return (
                "Your directory password appears expired. "
                f"Reset it here: {reset_url}"
            )

        fallback_help = str(
            os.environ.get(
                "LDAP_PASSWORD_RESET_HELP",
                "Your directory password appears expired. Contact your directory administrator.",
            )
        ).strip()
        return fallback_help or (
            "Your directory password appears expired. Contact your directory administrator."
        )

    def _is_password_expired(self, username: str, password: str) -> bool:
        if not username or not password:
            return False
        if str(os.environ.get("AUTH_LDAP_ENABLED", "false")).strip().lower() != "true":
            return False
        if str(os.environ.get("LDAP_PROFILE", "ad")).strip().lower() != "ad":
            return False

        try:
            server_uri = self._server_uri()
            user_dn = self._find_user_dn(server_uri, username)
            if not user_dn:
                return False

            conn = ldap.initialize(server_uri)
            conn.set_option(LDAP_OPT_PROTOCOL_VERSION, 3)
            conn.set_option(LDAP_OPT_REFERRALS, 0)
            try:
                conn.simple_bind_s(user_dn, password)
                return False
            except Exception as err:  # pylint: disable=broad-except
                detail = self._ldap_error_detail(err)
                return self._is_ad_password_expired_detail(detail)
            finally:
                try:
                    conn.unbind_s()
                except Exception:  # pylint: disable=broad-except
                    pass
        except Exception:  # pylint: disable=broad-except
            return False

    def _server_uri(self) -> str:
        proto = str(os.environ.get("LDAP_PROTO", "ldaps")).strip()
        host = str(os.environ.get("LDAP_SERVER", "")).strip()
        port = str(os.environ.get("LDAP_PORT", "636")).strip()
        return f"{proto}://{host}:{port}"

    def _find_user_dn(self, server_uri: str, username: str) -> str:
        conn = ldap.initialize(server_uri)
        conn.set_option(LDAP_OPT_PROTOCOL_VERSION, 3)
        conn.set_option(LDAP_OPT_REFERRALS, 0)

        bind_dn = str(os.environ.get("LDAP_BIND_DN", "")).strip()
        bind_password = str(os.environ.get("LDAP_BIND_PASSWORD", ""))
        if bind_dn:
            conn.simple_bind_s(bind_dn, bind_password)
        else:
            conn.simple_bind_s()

        base_dn = str(os.environ.get("LDAP_USER_BASE_DN", "")).strip()
        custom_filter = str(os.environ.get("LDAP_USER_SEARCH_FILTER", "")).strip()
        filter_template = custom_filter or "(sAMAccountName=%(user)s)"
        escaped_user = ldap.filter.escape_filter_chars(username)
        search_filter = filter_template.replace("%(user)s", escaped_user)

        try:
            result = conn.search_s(
                base_dn, LDAP_SCOPE_SUBTREE, search_filter, attrlist=[]
            )
        finally:
            try:
                conn.unbind_s()
            except Exception:  # pylint: disable=broad-except
                pass

        for dn, _attrs in result:
            if dn:
                return str(dn)
        return ""

    @staticmethod
    def _ldap_error_detail(err: Exception) -> str:
        if not getattr(err, "args", None):
            return ""
        first = err.args[0]
        if isinstance(first, dict):
            desc = str(first.get("desc", "")).strip()
            info = str(first.get("info", "")).strip()
            return " ".join(part for part in (desc, info) if part)
        return str(first).strip()

    @staticmethod
    def _is_ad_password_expired_detail(detail: str) -> bool:
        normalized = str(detail or "").lower()
        if not normalized:
            return False

        # Active Directory invalid-credentials diagnostic subcodes.
        # 532 = password expired, 773 = user must reset password at next logon.
        match = re.search(r"\bdata\s+([0-9a-f]{3,})\b", normalized)
        if match:
            return match.group(1) in {"532", "773"}

        # Fallback for non-standard messages.
        return "password" in normalized and "expired" in normalized
