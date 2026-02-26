"""Integration tests for SCIM token management.

Covers the admin token API and SCIM bearer-token authentication:
1. Token lifecycle: create, retrieve metadata, use for SCIM requests
2. Token rotation: creating a new token revokes previous tokens
3. Revoked tokens are rejected by SCIM endpoints
4. Non-admin users cannot manage SCIM tokens
5. SCIM requests without a token are rejected
6. Service discovery endpoints work without authentication
7. last_used_at is updated after a SCIM request
"""

import time

import requests

from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.managers.scim_token import ScimTokenManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.test_models import DATestUser


def test_scim_token_lifecycle(admin_user: DATestUser) -> None:
    """Create token → retrieve metadata → use for SCIM request."""
    token = ScimTokenManager.create(
        name="Test SCIM Token",
        user_performing_action=admin_user,
    )

    assert token.raw_token is not None
    assert token.raw_token.startswith("onyx_scim_")
    assert token.is_active is True
    assert "****" in token.token_display

    # GET returns the same metadata but raw_token is None because the
    # server only reveals the raw token once at creation time (it stores
    # only the SHA-256 hash).
    active = ScimTokenManager.get_active(user_performing_action=admin_user)
    assert active == token.model_copy(update={"raw_token": None})

    # Token works for SCIM requests
    response = ScimTokenManager.scim_get("/Users", token.raw_token)
    assert response.status_code == 200
    body = response.json()
    assert "Resources" in body
    assert body["totalResults"] >= 0


def test_scim_token_rotation_revokes_previous(admin_user: DATestUser) -> None:
    """Creating a new token automatically revokes the previous one."""
    first = ScimTokenManager.create(
        name="First Token",
        user_performing_action=admin_user,
    )
    assert first.raw_token is not None

    response = ScimTokenManager.scim_get("/Users", first.raw_token)
    assert response.status_code == 200

    # Create second token — should revoke first
    second = ScimTokenManager.create(
        name="Second Token",
        user_performing_action=admin_user,
    )
    assert second.raw_token is not None

    # Active token should now be the second one
    active = ScimTokenManager.get_active(user_performing_action=admin_user)
    assert active == second.model_copy(update={"raw_token": None})

    # First token rejected, second works
    assert ScimTokenManager.scim_get("/Users", first.raw_token).status_code == 401
    assert ScimTokenManager.scim_get("/Users", second.raw_token).status_code == 200


def test_scim_request_without_token_rejected(
    admin_user: DATestUser,  # noqa: ARG001
) -> None:
    """SCIM endpoints reject requests with no Authorization header."""
    assert ScimTokenManager.scim_get_no_auth("/Users").status_code == 401


def test_scim_request_with_bad_token_rejected(
    admin_user: DATestUser,  # noqa: ARG001
) -> None:
    """SCIM endpoints reject requests with an invalid token."""
    assert (
        ScimTokenManager.scim_get("/Users", "onyx_scim_bogus_token_value").status_code
        == 401
    )


def test_non_admin_cannot_create_token(
    admin_user: DATestUser,  # noqa: ARG001
) -> None:
    """Non-admin users get 403 when trying to create a SCIM token."""
    basic_user = UserManager.create(name="scim_basic_user")

    response = requests.post(
        f"{API_SERVER_URL}/admin/enterprise-settings/scim/token",
        json={"name": "Should Fail"},
        headers=basic_user.headers,
        timeout=60,
    )
    assert response.status_code == 403


def test_non_admin_cannot_get_token(
    admin_user: DATestUser,  # noqa: ARG001
) -> None:
    """Non-admin users get 403 when trying to retrieve SCIM token metadata."""
    basic_user = UserManager.create(name="scim_basic_user2")

    response = requests.get(
        f"{API_SERVER_URL}/admin/enterprise-settings/scim/token",
        headers=basic_user.headers,
        timeout=60,
    )
    assert response.status_code == 403


def test_no_active_token_returns_404(new_admin_user: DATestUser) -> None:
    """GET active token returns 404 when no token exists."""
    # new_admin_user depends on the reset fixture, ensuring a clean DB
    # with no active SCIM tokens.
    active = ScimTokenManager.get_active(user_performing_action=new_admin_user)
    assert active is None

    response = requests.get(
        f"{API_SERVER_URL}/admin/enterprise-settings/scim/token",
        headers=new_admin_user.headers,
        timeout=60,
    )
    assert response.status_code == 404


def test_service_discovery_no_auth_required(
    admin_user: DATestUser,  # noqa: ARG001
) -> None:
    """Service discovery endpoints work without any authentication."""
    for path in ["/ServiceProviderConfig", "/ResourceTypes", "/Schemas"]:
        response = ScimTokenManager.scim_get_no_auth(path)
        assert response.status_code == 200, f"{path} returned {response.status_code}"


def test_last_used_at_updated_after_scim_request(
    admin_user: DATestUser,
) -> None:
    """last_used_at timestamp is updated after using the token."""
    token = ScimTokenManager.create(
        name="Last Used Token",
        user_performing_action=admin_user,
    )
    assert token.raw_token is not None

    active = ScimTokenManager.get_active(user_performing_action=admin_user)
    assert active is not None
    assert active.last_used_at is None

    # Make a SCIM request, then verify last_used_at is set
    assert ScimTokenManager.scim_get("/Users", token.raw_token).status_code == 200
    time.sleep(0.5)

    active_after = ScimTokenManager.get_active(user_performing_action=admin_user)
    assert active_after is not None
    assert active_after.last_used_at is not None
