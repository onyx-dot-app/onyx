"""Integration test for runtime-configurable security settings.

The integration api_server runs as a single uvicorn worker, so the PUT
handler's local-cache invalidation takes effect on the very next request
without any TTL wait.
"""

from collections.abc import Generator

import pytest

from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.test_models import DATestUser

SECURITY_URL = f"{API_SERVER_URL}/admin/security"
USERS_URL = f"{API_SERVER_URL}/users"


def _put_security(payload: dict, user: DATestUser) -> dict:
    response = client.put(
        SECURITY_URL,
        json=payload,
        headers=user.headers,
        cookies=user.cookies,
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


# Sending every override key as null clears the row to pure env defaults,
# so teardown doesn't need to know which fields a test touched.
_ALL_OVERRIDE_KEYS_NULL: dict[str, None] = {
    "user_directory_admin_only": None,
    "track_external_idp_expiry": None,
    "mask_credential_prefix": None,
    "valid_email_domains": None,
    "password_min_length": None,
    "password_max_length": None,
    "password_require_uppercase": None,
    "password_require_lowercase": None,
    "password_require_digit": None,
    "password_require_special_char": None,
}


@pytest.fixture
def reset_security_settings(
    admin_user: DATestUser,
) -> Generator[None, None, None]:
    """Restore env defaults after the test — overrides are tenant-persistent."""
    yield
    try:
        _put_security(dict(_ALL_OVERRIDE_KEYS_NULL), admin_user)
    except Exception:
        # Best-effort cleanup; don't mask the underlying test failure.
        pass


def test_user_directory_admin_only_toggle_flips_basic_access(
    admin_user: DATestUser,
    basic_user: DATestUser,
    reset_security_settings: None,  # noqa: ARG001
) -> None:
    """Toggling ``user_directory_admin_only`` must immediately flip a basic
    user's /users access."""
    # Baseline: with the flag off, a basic user can list users.
    _put_security({"user_directory_admin_only": False}, admin_user)

    resp_before = client.get(
        USERS_URL,
        headers=basic_user.headers,
        cookies=basic_user.cookies,
        timeout=30,
    )
    assert resp_before.status_code == 200, (
        f"Expected basic user to list /users when flag is off, "
        f"got {resp_before.status_code}: {resp_before.text}"
    )

    # Flip the flag on. Basic user should now be rejected.
    _put_security({"user_directory_admin_only": True}, admin_user)

    resp_blocked = client.get(
        USERS_URL,
        headers=basic_user.headers,
        cookies=basic_user.cookies,
        timeout=30,
    )
    assert resp_blocked.status_code == 403, (
        f"Expected basic user to be denied /users when flag is on, "
        f"got {resp_blocked.status_code}: {resp_blocked.text}"
    )

    # Admin should still see the directory.
    resp_admin = client.get(
        USERS_URL,
        headers=admin_user.headers,
        cookies=admin_user.cookies,
        timeout=30,
    )
    assert resp_admin.status_code == 200

    # Flip back off. Basic user regains access immediately.
    _put_security({"user_directory_admin_only": False}, admin_user)

    resp_after = client.get(
        USERS_URL,
        headers=basic_user.headers,
        cookies=basic_user.cookies,
        timeout=30,
    )
    assert resp_after.status_code == 200, (
        f"Expected basic user to regain /users access after flag is off, "
        f"got {resp_after.status_code}: {resp_after.text}"
    )


def test_get_security_settings_round_trip_persists(
    admin_user: DATestUser,
    reset_security_settings: None,  # noqa: ARG001
) -> None:
    """PUT then GET reflects the persisted override; other fields unchanged."""
    baseline = client.get(
        SECURITY_URL,
        headers=admin_user.headers,
        cookies=admin_user.cookies,
        timeout=30,
    ).json()

    desired = not baseline["track_external_idp_expiry"]
    _put_security({"track_external_idp_expiry": desired}, admin_user)

    after = client.get(
        SECURITY_URL,
        headers=admin_user.headers,
        cookies=admin_user.cookies,
        timeout=30,
    ).json()

    assert after["track_external_idp_expiry"] is desired
    for key in baseline:
        if key == "track_external_idp_expiry":
            continue
        assert after[key] == baseline[key], (
            f"Field {key!r} unexpectedly changed: {baseline[key]!r} -> {after[key]!r}"
        )
