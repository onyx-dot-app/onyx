"""Integration test for runtime-configurable security settings.

Toggles ``user_directory_admin_only`` via PUT /admin/security and verifies
that a basic user's access to /users flips accordingly. The integration
api_server runs as a single uvicorn worker; ``store_overrides()`` clears
that worker's local cache synchronously inside the PUT handler, so the
very next request observes the new effective value without any TTL wait.
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


# Every override key on SecuritySettingsOverrides. Sending all of them as
# null in the teardown PUT clears the entire blob so the tenant is left in
# pure env-defaults state regardless of which fields the test mutated.
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
    """Always restore an empty override blob after the test so other suites
    aren't affected by tenant-persistent state. Clears every override key,
    not just the one the test touched, so adding new fields to a test won't
    require updating this fixture."""
    yield
    try:
        _put_security(dict(_ALL_OVERRIDE_KEYS_NULL), admin_user)
    except Exception:
        # Best-effort cleanup; do not mask the underlying test failure.
        pass


def test_user_directory_admin_only_toggle_flips_basic_access(
    admin_user: DATestUser,
    basic_user: DATestUser,
    reset_security_settings: None,  # noqa: ARG001
) -> None:
    """Toggling ``user_directory_admin_only`` at runtime must immediately
    affect a basic user's access to /users. ``store_overrides()`` clears
    the api_server's local cache as part of the PUT, so the next request
    sees the new value without waiting on TTL expiry."""
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
    """A PUT then GET must reflect the persisted override merged with env
    defaults. All other fields must remain at their env-derived value."""
    # Capture the current effective state to compare against after the write.
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
    # All other fields should be untouched relative to baseline.
    for key in baseline:
        if key == "track_external_idp_expiry":
            continue
        assert after[key] == baseline[key], (
            f"Field {key!r} unexpectedly changed: {baseline[key]!r} -> {after[key]!r}"
        )
