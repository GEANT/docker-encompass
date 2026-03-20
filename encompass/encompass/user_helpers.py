"""
User helper functions to abstract authentication backends
Supports both LDAP and MySQL authentication
"""

from django.conf import settings


def get_user_email(user):
    """
    Get user email regardless of authentication backend
    Returns None if email is not available
    """
    try:
        if settings.USE_AUTH_LDAP and hasattr(user, 'ldap_user'):
            return user.ldap_user.attrs.get("mail", [None])[0]

        # MySQL or ModelBackend
        return user.email
    except (AttributeError, IndexError, KeyError):
        return None


def get_user_display_name(user):
    """
    Get user display name regardless of authentication backend
    Returns settings.UNLOGGED if display name is not available
    """
    try:
        if settings.USE_AUTH_LDAP and hasattr(user, 'ldap_user'):
            return user.ldap_user.attrs.get("displayName", [settings.UNLOGGED])[0]

        # MySQL or ModelBackend
        full_name = f"{user.first_name} {user.last_name}".strip()
        return full_name if full_name else user.username
    except (AttributeError, IndexError, KeyError):
        return settings.UNLOGGED


def get_user_groups(user):
    """
    Get user groups regardless of authentication backend
    Returns an empty list if groups are not available
    """
    try:
        if settings.USE_AUTH_LDAP and hasattr(user, 'ldap_user'):
            return user.ldap_user.attrs.get("memberOf", [])

        # MySQL or ModelBackend - use Django groups
        return list(user.groups.values_list('name', flat=True))
    except (AttributeError, IndexError, KeyError):
        return []


def get_user_username(user):
    """
    Get username/sAMAccountName regardless of authentication backend
    Returns "unknown" if username is not available
    """
    try:
        if settings.USE_AUTH_LDAP and hasattr(user, 'ldap_user'):
            return user.ldap_user.attrs.get("sAMAccountName", [user.username])[0]

        return user.username
    except (AttributeError, IndexError, KeyError):
        return "unknown"


def get_user_commit_info(user):
    """
    Get user info formatted for Git commits
    Returns a dictionary with 'name', 'email', and 'username' keys
    """
    email = get_user_email(user)
    name = get_user_display_name(user)
    username = get_user_username(user)

    return {
        'name': name or username,
        'email': email or f"{username}@encompass.local",
        'username': username
    }
