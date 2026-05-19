from typing import Any

import requests

from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.test_models import DATestUser

SECURITY_URL = f"{API_SERVER_URL}/admin/security"


def _get_settings(user: DATestUser) -> dict[str, Any]:
    response = requests.get(SECURITY_URL, headers=user.headers)
    response.raise_for_status()
    return response.json()


def _put_settings(user: DATestUser, body: dict[str, Any]) -> requests.Response:
    headers = dict(user.headers)
    headers["Content-Type"] = "application/json"
    return requests.put(SECURITY_URL, json=body, headers=headers)


def _reset_settings(admin_user: DATestUser) -> None:
    """Clear all overrides so subsequent tests start from env defaults."""
    response = _put_settings(
        admin_user,
        {
            "user_directory_admin_only": None,
            "track_external_idp_expiry": None,
            "require_email_verification": None,
            "mask_credential_prefix": None,
            "valid_email_domains": None,
            "password_min_length": None,
            "password_max_length": None,
            "password_require_uppercase": None,
            "password_require_lowercase": None,
            "password_require_digit": None,
            "password_require_special_char": None,
        },
    )
    response.raise_for_status()


def test_get_security_settings_returns_env_defaults(admin_user: DATestUser) -> None:
    _reset_settings(admin_user)
    settings = _get_settings(admin_user)

    # After reset, every field is populated from env fallbacks — none are null.
    assert settings["user_directory_admin_only"] is not None
    assert settings["password_min_length"] is not None
    assert settings["valid_email_domains"] is not None


def test_put_security_settings_round_trip(admin_user: DATestUser) -> None:
    _reset_settings(admin_user)
    response = _put_settings(
        admin_user,
        {
            "user_directory_admin_only": True,
            "password_min_length": 24,
        },
    )
    assert response.ok, response.text

    settings = _get_settings(admin_user)
    assert settings["user_directory_admin_only"] is True
    assert settings["password_min_length"] == 24

    _reset_settings(admin_user)


def test_put_security_settings_requires_admin(
    admin_user: DATestUser,
    basic_user: DATestUser,
) -> None:
    response = _put_settings(basic_user, {"user_directory_admin_only": True})
    assert response.status_code in (401, 403), response.text


def test_user_directory_admin_only_gates_list_users(
    admin_user: DATestUser,
    basic_user: DATestUser,
) -> None:
    """End-to-end behavioral check: setting user_directory_admin_only via the
    security API actually gates /users for non-admins.
    """
    _reset_settings(admin_user)

    # Default off — basic users can list users.
    response = requests.get(f"{API_SERVER_URL}/users", headers=basic_user.headers)
    assert response.ok, response.text

    # Flip on — basic users are now denied.
    assert _put_settings(
        admin_user, {"user_directory_admin_only": True}
    ).ok
    response = requests.get(f"{API_SERVER_URL}/users", headers=basic_user.headers)
    assert response.status_code in (401, 403), response.text

    # Flip off — restored.
    assert _put_settings(
        admin_user, {"user_directory_admin_only": False}
    ).ok
    response = requests.get(f"{API_SERVER_URL}/users", headers=basic_user.headers)
    assert response.ok, response.text

    _reset_settings(admin_user)
