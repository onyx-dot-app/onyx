"""
Integration tests for Personal Access Token (PAT) API.

Test Suite:
1. test_pat_lifecycle_happy_path - Complete PAT lifecycle (create, auth, revoke)
2. test_pat_user_isolation_and_authentication - User authentication and multi-user isolation
3. test_pat_expiration_flow - Expiration logic (end-of-day UTC, never-expiring)
4. test_pat_validation_errors - Input validation and error handling
5. test_pat_sorting_and_last_used - Sorting and last_used_at tracking
6. test_pat_role_based_access_control - Admin vs Basic vs Curator permissions
"""

import time
from datetime import datetime
from datetime import timedelta
from datetime import timezone

import requests

from onyx.auth.schemas import UserRole
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.managers.pat import PATManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.test_models import DATestUser


def test_pat_lifecycle_happy_path(reset: None) -> None:
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


def test_pat_user_isolation_and_authentication(reset: None) -> None:
    """
    PATs authenticate as real users, and users can only see/manage their own tokens.
    """
    user_a: DATestUser = UserManager.create(name="user_a")
    user_b: DATestUser = UserManager.create(name="user_b")

    # Create tokens for both users
    user_a_pats = []
    for i in range(2):
        pat = PATManager.create(
            name=f"User A Token {i+1}",
            expiration_days=30,
            user_performing_action=user_a,
        )
        user_a_pats.append(pat)

    user_b_pats = []
    for i in range(2):
        pat = PATManager.create(
            name=f"User B Token {i+1}",
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


def test_pat_expiration_flow(reset: None) -> None:
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


def test_pat_validation_errors(reset: None) -> None:
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


def test_pat_sorting_and_last_used(reset: None) -> None:
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


def test_pat_role_based_access_control(reset: None) -> None:
    """
    PATs inherit user roles and permissions:
    - Admin PAT: Full access to admin-only endpoints
    - Curator/Global Curator PATs: Access to management endpoints
    - Basic PAT: Denied access to admin and management endpoints
    """
    # Create users with different roles
    admin_user: DATestUser = UserManager.create(name="admin_user")
    assert admin_user.role == UserRole.ADMIN

    basic_user: DATestUser = UserManager.create(name="basic_user")
    assert basic_user.role == UserRole.BASIC

    curator_user: DATestUser = UserManager.create(name="curator_user")
    curator_user = UserManager.set_role(
        user_to_set=curator_user,
        target_role=UserRole.CURATOR,
        user_performing_action=admin_user,
        explicit_override=True,
    )
    assert curator_user.role == UserRole.CURATOR

    global_curator_user: DATestUser = UserManager.create(name="global_curator_user")
    global_curator_user = UserManager.set_role(
        user_to_set=global_curator_user,
        target_role=UserRole.GLOBAL_CURATOR,
        user_performing_action=admin_user,
        explicit_override=True,
    )
    assert global_curator_user.role == UserRole.GLOBAL_CURATOR

    # Create PATs for each user
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

    curator_pat = PATManager.create(
        name="Curator Token",
        expiration_days=7,
        user_performing_action=curator_user,
    )

    global_curator_pat = PATManager.create(
        name="Global Curator Token",
        expiration_days=7,
        user_performing_action=global_curator_user,
    )

    # Verify all tokens are present (type narrowing for mypy)
    assert admin_pat.token is not None
    assert basic_pat.token is not None
    assert curator_pat.token is not None
    assert global_curator_pat.token is not None

    # Test admin-only endpoint access
    print("\n[Test] Admin PAT accessing admin-only endpoint...")
    admin_endpoint_response = requests.get(
        f"{API_SERVER_URL}/admin/api-key",
        headers=PATManager.get_auth_headers(admin_pat.token),
        timeout=60,
    )
    assert admin_endpoint_response.status_code == 200
    print("[✓] Admin PAT successfully accessed /admin/api-key")

    print("\n[Test] Basic PAT accessing admin endpoint...")
    basic_admin_response = requests.get(
        f"{API_SERVER_URL}/admin/api-key",
        headers=PATManager.get_auth_headers(basic_pat.token),
        timeout=60,
    )
    assert basic_admin_response.status_code == 403
    print("[✓] Basic PAT correctly denied access (403) to /admin/api-key")

    print("\n[Test] Curator PAT accessing admin-only endpoint...")
    curator_admin_response = requests.get(
        f"{API_SERVER_URL}/admin/api-key",
        headers=PATManager.get_auth_headers(curator_pat.token),
        timeout=60,
    )
    assert curator_admin_response.status_code == 403
    print("[✓] Curator PAT correctly denied access (403) to /admin/api-key")

    print("\n[Test] Global Curator PAT accessing admin-only endpoint...")
    global_curator_admin_response = requests.get(
        f"{API_SERVER_URL}/admin/api-key",
        headers=PATManager.get_auth_headers(global_curator_pat.token),
        timeout=60,
    )
    assert global_curator_admin_response.status_code == 403
    print("[✓] Global Curator PAT correctly denied access (403) to /admin/api-key")

    # Test management endpoint access
    print("\n[Test] Testing management endpoint access for curators...")

    admin_manage_response = requests.get(
        f"{API_SERVER_URL}/manage/admin/connector",
        headers=PATManager.get_auth_headers(admin_pat.token),
        timeout=60,
    )
    assert admin_manage_response.status_code == 200
    print("[✓] Admin PAT can access /manage/admin/connector")

    curator_manage_response = requests.get(
        f"{API_SERVER_URL}/manage/admin/connector",
        headers=PATManager.get_auth_headers(curator_pat.token),
        timeout=60,
    )
    assert curator_manage_response.status_code == 200
    print("[✓] Curator PAT can access /manage/admin/connector")

    global_curator_manage_response = requests.get(
        f"{API_SERVER_URL}/manage/admin/connector",
        headers=PATManager.get_auth_headers(global_curator_pat.token),
        timeout=60,
    )
    assert global_curator_manage_response.status_code == 200
    print("[✓] Global Curator PAT can access /manage/admin/connector")

    basic_manage_response = requests.get(
        f"{API_SERVER_URL}/manage/admin/connector",
        headers=PATManager.get_auth_headers(basic_pat.token),
        timeout=60,
    )
    assert basic_manage_response.status_code in [403, 401]
    print(
        f"[✓] Basic PAT correctly denied access ({basic_manage_response.status_code}) "
        "to /manage/admin/connector"
    )

    # Verify PATs authenticate with correct identity and role
    print("\n[Test] Verifying PATs authenticate as correct users with correct roles...")

    admin_me = PATManager.authenticate(admin_pat.token)
    assert admin_me.status_code == 200
    assert admin_me.json()["email"] == admin_user.email
    assert admin_me.json()["role"] == UserRole.ADMIN.value

    basic_me = PATManager.authenticate(basic_pat.token)
    assert basic_me.status_code == 200
    assert basic_me.json()["email"] == basic_user.email
    assert basic_me.json()["role"] == UserRole.BASIC.value

    curator_me = PATManager.authenticate(curator_pat.token)
    assert curator_me.status_code == 200
    assert curator_me.json()["email"] == curator_user.email
    assert curator_me.json()["role"] == UserRole.CURATOR.value

    global_curator_me = PATManager.authenticate(global_curator_pat.token)
    assert global_curator_me.status_code == 200
    assert global_curator_me.json()["email"] == global_curator_user.email
    assert global_curator_me.json()["role"] == UserRole.GLOBAL_CURATOR.value

    print("[✓] All PATs authenticate with correct user identity and role")

    # Verify all PATs can access basic endpoints
    print("\n[Test] All PATs can access basic endpoints...")
    for pat, user_name in [
        (admin_pat, "Admin"),
        (basic_pat, "Basic"),
        (curator_pat, "Curator"),
        (global_curator_pat, "Global Curator"),
    ]:
        assert pat.token is not None
        persona_response = requests.get(
            f"{API_SERVER_URL}/persona",
            headers=PATManager.get_auth_headers(pat.token),
            timeout=60,
        )
        assert persona_response.status_code == 200
        print(f"[✓] {user_name} PAT can access /persona endpoint")

    print("\n[✓] All role-based access control tests passed!")
    print("Summary:")
    print(
        "  - Admin PAT: Full access to admin-only endpoints (/admin/*, /manage/admin/*)"
    )
    print(
        "  - Curator PAT: Access to management endpoints (/manage/admin/*), "
        "denied on admin-only (/admin/*)"
    )
    print(
        "  - Global Curator PAT: Access to management endpoints (/manage/admin/*), "
        "denied on admin-only (/admin/*)"
    )
    print("  - Basic PAT: Denied access to admin and management endpoints")
    print("  - All PATs: Can access basic endpoints (/persona, /me, etc.)")
    print("  - All PATs: Authenticate with correct user identity and role")
