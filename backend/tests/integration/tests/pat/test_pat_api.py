"""
Integration tests for Personal Access Token (PAT) API.

Test Suite:
1. test_pat_lifecycle_happy_path - Complete PAT lifecycle (create, auth, revoke)
2. test_pat_user_isolation_and_authentication - User authentication and multi-user isolation
3. test_pat_expiration_flow - Expiration logic (end-of-day UTC, never-expiring)
4. test_pat_validation_errors - Input validation and error handling
5. test_pat_sorting_and_last_used - Sorting and last_used_at tracking
6. test_pat_role_based_access_control - Admin vs Basic permissions
"""

import os
import time
from datetime import datetime
from datetime import timedelta
from datetime import timezone

import pytest
import requests

from onyx.db.enums import Permission
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.managers.pat import PATManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.managers.user_group import UserGroupManager
from tests.integration.common_utils.test_models import DATestUser


def _grant_create_pat_permission(
    user: DATestUser,
    admin_user: DATestUser,
) -> None:
    """Grant CREATE_USER_API_KEYS to a non-admin user via a temp group.

    PAT creation is gated by Permission.CREATE_USER_API_KEYS; non-admin test
    users must be placed in a group that grants it before they can call
    POST /user/pats.
    """
    group = UserGroupManager.create(
        name=f"pat_creator_{user.id[:8]}",
        user_ids=[user.id],
        cc_pair_ids=[],
        user_performing_action=admin_user,
    )
    response = UserGroupManager.set_permissions(
        user_group=group,
        permissions=[Permission.CREATE_USER_API_KEYS.value],
        user_performing_action=admin_user,
    )
    response.raise_for_status()


def test_pat_lifecycle_happy_path(reset: None) -> None:  # noqa: ARG001
    """Complete PAT lifecycle: create, authenticate, revoke."""
    user: DATestUser = UserManager.create(name="pat_user")

    # Create PAT
    pat = PATManager.create(
        name="My Integration Token",
        expiration_days=30,
        user_performing_action=user,
    )

    assert pat.id is not None
    assert pat.name == "My Integration Token"
    assert pat.token is not None  # Raw token only returned on creation
    assert pat.token_display is not None
    assert pat.created_at is not None
    assert pat.expires_at is not None

    assert pat.token.startswith("onyx_pat_")
    assert len(pat.token) > 20

    assert "****" in pat.token_display
    assert pat.token_display.startswith("onyx_pat_")

    # List PATs
    tokens = PATManager.list(user)
    assert len(tokens) == 1
    assert tokens[0].id == pat.id
    assert tokens[0].name == "My Integration Token"
    assert tokens[0].token_display == pat.token_display
    assert tokens[0].token is None

    # Authenticate with PAT
    auth_response = PATManager.authenticate(pat.token)
    assert auth_response.status_code == 200
    me_data = auth_response.json()
    assert me_data["email"] == user.email
    assert me_data["id"] == user.id

    # Revoke PAT
    PATManager.revoke(pat.id, user)

    # Verify revoked token fails authentication
    revoked_auth_response = PATManager.authenticate(pat.token)
    assert revoked_auth_response.status_code == 403  # Revoked token returns 403

    # Verify token is no longer listed
    tokens_after_revoke = PATManager.list(user)
    assert len(tokens_after_revoke) == 0


def test_pat_user_isolation_and_authentication(
    reset: None,  # noqa: ARG001
) -> None:  # noqa: ARG001
    """
    PATs authenticate as real users, and users can only see/manage their own tokens.
    """
    user_a: DATestUser = UserManager.create(name="user_a")
    user_b: DATestUser = UserManager.create(name="user_b")

    # user_a is the first registered user and lands in Admin → has
    # FULL_ADMIN_PANEL_ACCESS which short-circuits the PAT-creation gate.
    # user_b is basic and needs CREATE_USER_API_KEYS via a group grant.
    _grant_create_pat_permission(user_b, user_a)

    # Create tokens for both users
    user_a_pats = []
    for i in range(2):
        pat = PATManager.create(
            name=f"User A Token {i + 1}",
            expiration_days=30,
            user_performing_action=user_a,
        )
        user_a_pats.append(pat)

    user_b_pats = []
    for i in range(2):
        pat = PATManager.create(
            name=f"User B Token {i + 1}",
            expiration_days=30,
            user_performing_action=user_b,
        )
        user_b_pats.append(pat)

    # Verify PATs authenticate as the correct users
    for user, pat in [(user_a, user_a_pats[0]), (user_b, user_b_pats[0])]:
        assert pat.token is not None
        me_response = PATManager.authenticate(pat.token)
        assert me_response.status_code == 200
        me_data = me_response.json()
        assert me_data["email"] == user.email
        assert me_data["id"] == user.id

    # Verify each user only sees their own tokens
    user_a_list = PATManager.list(user_a)
    assert len(user_a_list) == 2

    user_b_list = PATManager.list(user_b)
    assert len(user_b_list) == 2

    # Verify user A cannot delete user B's token using their PAT
    assert user_a_pats[0].token is not None
    delete_response = requests.delete(
        f"{API_SERVER_URL}/user/pats/{user_b_pats[0].id}",
        headers=PATManager.get_auth_headers(user_a_pats[0].token),
        timeout=60,
    )
    assert delete_response.status_code == 404

    # Verify user B's token still exists
    user_b_list_after = PATManager.list(user_b)
    assert len(user_b_list_after) == 2

    # Verify deleting non-existent token returns 404
    delete_fake = requests.delete(
        f"{API_SERVER_URL}/user/pats/999999",
        headers=user_a.headers,
        timeout=60,
    )
    assert delete_fake.status_code == 404


def test_pat_expiration_flow(reset: None) -> None:  # noqa: ARG001
    """Expiration timestamp is end-of-day (23:59:59 UTC); never-expiring tokens work; revoked tokens fail."""
    user: DATestUser = UserManager.create(name="expiration_user")

    # Create expiring token
    pat = PATManager.create(
        name="Expiring Token",
        expiration_days=7,
        user_performing_action=user,
    )

    assert pat.expires_at is not None
    expires_at = datetime.fromisoformat(pat.expires_at.replace("Z", "+00:00"))

    # Verify end-of-day expiration
    assert expires_at.hour == 23
    assert expires_at.minute == 59
    assert expires_at.second == 59

    # Calculate expected end-of-day 7 days from now
    now = datetime.now(timezone.utc)
    expected_date = (now + timedelta(days=7)).date()
    expected_expiry = datetime.combine(expected_date, datetime.max.time()).replace(
        tzinfo=timezone.utc
    )
    # Allow for small timing differences (within a day)
    assert abs((expires_at - expected_expiry).total_seconds()) < 86400  # 1 day

    # Create never-expiring token
    never_expiring_pat = PATManager.create(
        name="Never Expiring Token",
        expiration_days=None,
        user_performing_action=user,
    )
    assert never_expiring_pat.expires_at is None

    # Verify never-expiring token works
    assert never_expiring_pat.token is not None
    auth_response = PATManager.authenticate(never_expiring_pat.token)
    assert auth_response.status_code == 200

    # Revoke the never-expiring token
    PATManager.revoke(never_expiring_pat.id, user)

    # Verify revoked token fails (token var still holds the revoked value)
    revoked_auth_response = PATManager.authenticate(never_expiring_pat.token)
    assert revoked_auth_response.status_code == 403


def test_pat_validation_errors(reset: None) -> None:  # noqa: ARG001
    """Validate input errors: empty name, name too long, negative/zero expiration."""
    user: DATestUser = UserManager.create(name="validation_user")

    # Empty name should fail
    empty_name_response = requests.post(
        f"{API_SERVER_URL}/user/pats",
        json={"name": "", "expiration_days": 30},
        headers=user.headers,
        timeout=60,
    )
    assert empty_name_response.status_code == 422

    # Name too long should fail
    long_name = "a" * 101
    long_name_response = requests.post(
        f"{API_SERVER_URL}/user/pats",
        json={"name": long_name, "expiration_days": 30},
        headers=user.headers,
        timeout=60,
    )
    assert long_name_response.status_code == 422

    # Negative expiration should fail
    negative_exp_response = requests.post(
        f"{API_SERVER_URL}/user/pats",
        json={"name": "Test Token", "expiration_days": -1},
        headers=user.headers,
        timeout=60,
    )
    assert negative_exp_response.status_code == 422

    # Zero expiration should fail
    zero_exp_response = requests.post(
        f"{API_SERVER_URL}/user/pats",
        json={"name": "Test Token", "expiration_days": 0},
        headers=user.headers,
        timeout=60,
    )
    assert zero_exp_response.status_code == 422

    # Max length name (100 chars) should succeed
    valid_name = "a" * 100
    valid_pat = PATManager.create(
        name=valid_name,
        expiration_days=7,
        user_performing_action=user,
    )
    assert valid_pat.id is not None

    # Missing name should fail
    missing_name_response = requests.post(
        f"{API_SERVER_URL}/user/pats",
        json={"expiration_days": 30},
        headers=user.headers,
        timeout=60,
    )
    assert missing_name_response.status_code == 422


def test_pat_sorting_and_last_used(reset: None) -> None:  # noqa: ARG001
    """PATs are sorted by created_at DESC; last_used_at updates after authentication."""
    user: DATestUser = UserManager.create(name="sorting_user")

    # Create tokens with small delays to ensure different timestamps
    token1 = PATManager.create(
        name="First Token",
        expiration_days=30,
        user_performing_action=user,
    )

    time.sleep(0.1)

    PATManager.create(
        name="Second Token",
        expiration_days=30,
        user_performing_action=user,
    )

    time.sleep(0.1)

    PATManager.create(
        name="Third Token",
        expiration_days=30,
        user_performing_action=user,
    )

    # Verify sorted by created_at DESC (newest first)
    tokens = PATManager.list(user)
    assert len(tokens) == 3

    assert tokens[0].name == "Third Token"
    assert tokens[1].name == "Second Token"
    assert tokens[2].name == "First Token"

    # Verify all tokens have no last_used_at initially
    for token in tokens:
        assert token.last_used_at is None

    # Use the first token (oldest)
    assert token1.token is not None
    auth_response = PATManager.authenticate(token1.token)
    assert auth_response.status_code == 200

    time.sleep(0.5)

    # Verify last_used_at is updated for the used token only
    tokens_after_use = PATManager.list(user)

    token1_after_use = next(t for t in tokens_after_use if t.name == "First Token")
    assert token1_after_use.last_used_at is not None

    token2_after_use = next(t for t in tokens_after_use if t.name == "Second Token")
    token3_after_use = next(t for t in tokens_after_use if t.name == "Third Token")
    assert token2_after_use.last_used_at is None
    assert token3_after_use.last_used_at is None


def test_pat_role_based_access_control(reset: None) -> None:  # noqa: ARG001
    """PATs inherit the issuing user's effective permissions.

    - Admin PAT: full access to admin-only endpoints
    - Basic PAT: denied on admin and management endpoints
    """
    admin_user: DATestUser = UserManager.create(name="admin_user")
    assert admin_user.is_admin

    basic_user: DATestUser = UserManager.create(name="basic_user")
    assert not basic_user.is_admin

    _grant_create_pat_permission(basic_user, admin_user)

    admin_pat = PATManager.create(
        name="Admin Token",
        expiration_days=7,
        user_performing_action=admin_user,
    )
    basic_pat = PATManager.create(
        name="Basic Token",
        expiration_days=7,
        user_performing_action=basic_user,
    )

    assert admin_pat.token is not None
    assert basic_pat.token is not None

    # Admin-only endpoint
    admin_endpoint_response = requests.get(
        f"{API_SERVER_URL}/admin/api-key",
        headers=PATManager.get_auth_headers(admin_pat.token),
        timeout=60,
    )
    assert admin_endpoint_response.status_code == 200

    basic_admin_response = requests.get(
        f"{API_SERVER_URL}/admin/api-key",
        headers=PATManager.get_auth_headers(basic_pat.token),
        timeout=60,
    )
    assert basic_admin_response.status_code == 403

    # Management endpoint
    admin_manage_response = requests.get(
        f"{API_SERVER_URL}/manage/admin/connector",
        headers=PATManager.get_auth_headers(admin_pat.token),
        timeout=60,
    )
    assert admin_manage_response.status_code == 200

    basic_manage_response = requests.get(
        f"{API_SERVER_URL}/manage/admin/connector",
        headers=PATManager.get_auth_headers(basic_pat.token),
        timeout=60,
    )
    assert basic_manage_response.status_code in [401, 403]

    # Identity + permission surface on /me
    admin_me = PATManager.authenticate(admin_pat.token)
    assert admin_me.status_code == 200
    assert admin_me.json()["email"] == admin_user.email
    assert (
        Permission.FULL_ADMIN_PANEL_ACCESS.value
        in admin_me.json()["effective_permissions"]
    )

    basic_me = PATManager.authenticate(basic_pat.token)
    assert basic_me.status_code == 200
    assert basic_me.json()["email"] == basic_user.email
    assert Permission.FULL_ADMIN_PANEL_ACCESS.value not in basic_me.json().get(
        "effective_permissions", []
    )

    # Both PATs can hit basic endpoints
    for pat in (admin_pat, basic_pat):
        assert pat.token is not None
        persona_response = requests.get(
            f"{API_SERVER_URL}/persona",
            headers=PATManager.get_auth_headers(pat.token),
            timeout=60,
        )
        assert persona_response.status_code == 200


@pytest.mark.skipif(
    os.environ.get("ENABLE_PAID_ENTERPRISE_EDITION_FEATURES", "").lower() != "true",
    reason="User-group permission wiring is enterprise only",
)
def test_pat_group_permission_access_control(reset: None) -> None:  # noqa: ARG001
    """A PAT issued to a user in a group granting manage:connectors should
    reach admin connector endpoints (the new-model replacement for the old
    GLOBAL_CURATOR coverage)."""
    admin_user: DATestUser = UserManager.create(name="admin_user")
    assert admin_user.is_admin

    group_user: DATestUser = UserManager.create(name="group_user")
    assert not group_user.is_admin

    connector_managers = UserGroupManager.create(
        name="connector_managers",
        user_ids=[group_user.id],
        cc_pair_ids=[],
        user_performing_action=admin_user,
    )
    set_perms_response = UserGroupManager.set_permissions(
        user_group=connector_managers,
        permissions=[
            Permission.MANAGE_CONNECTORS.value,
            Permission.MANAGE_USER_GROUPS.value,
            Permission.CREATE_USER_API_KEYS.value,
        ],
        user_performing_action=admin_user,
    )
    set_perms_response.raise_for_status()
    UserGroupManager.wait_for_sync(
        user_groups_to_check=[connector_managers],
        user_performing_action=admin_user,
    )

    group_pat = PATManager.create(
        name="Group Token",
        expiration_days=7,
        user_performing_action=group_user,
    )
    assert group_pat.token is not None

    # /me should reflect the group-granted permissions
    me_response = PATManager.authenticate(group_pat.token)
    assert me_response.status_code == 200
    effective_permissions = me_response.json()["effective_permissions"]
    assert Permission.MANAGE_CONNECTORS.value in effective_permissions
    assert Permission.MANAGE_USER_GROUPS.value in effective_permissions
    assert Permission.FULL_ADMIN_PANEL_ACCESS.value not in effective_permissions

    # Admin connector management surface is reachable via the PAT
    manage_response = requests.get(
        f"{API_SERVER_URL}/manage/admin/connector",
        headers=PATManager.get_auth_headers(group_pat.token),
        timeout=60,
    )
    assert manage_response.status_code == 200

    # Sanity: a plain basic user's PAT still cannot reach that endpoint
    plain_basic: DATestUser = UserManager.create(name="plain_basic")
    _grant_create_pat_permission(plain_basic, admin_user)
    plain_pat = PATManager.create(
        name="Plain Basic Token",
        expiration_days=7,
        user_performing_action=plain_basic,
    )
    assert plain_pat.token is not None
    plain_response = requests.get(
        f"{API_SERVER_URL}/manage/admin/connector",
        headers=PATManager.get_auth_headers(plain_pat.token),
        timeout=60,
    )
    assert plain_response.status_code in (401, 403)
