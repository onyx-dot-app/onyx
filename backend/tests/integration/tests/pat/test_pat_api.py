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

from datetime import datetime
from datetime import timedelta

import requests

from onyx.auth.schemas import UserRole
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.test_models import DATestUser


def test_pat_lifecycle_happy_path(reset: None) -> None:
    """Complete PAT lifecycle: create, authenticate, revoke."""
    user: DATestUser = UserManager.create(name="pat_user")

    create_response = requests.post(
        f"{API_SERVER_URL}/user/pats",
        json={"name": "My Integration Token", "expiration_days": 30},
        headers=user.headers,
    )
    assert create_response.status_code == 200
    created_data = create_response.json()

    assert "id" in created_data
    assert "name" in created_data
    assert created_data["name"] == "My Integration Token"
    assert "token" in created_data  # Raw token only returned on creation
    assert "token_display" in created_data
    assert "created_at" in created_data
    assert "expires_at" in created_data

    raw_token = created_data["token"]
    token_id = created_data["id"]
    token_display = created_data["token_display"]

    assert raw_token.startswith("onyx_pat_")
    assert len(raw_token) > 20

    assert "****" in token_display
    assert token_display.startswith("onyx_pat_")

    list_response = requests.get(
        f"{API_SERVER_URL}/user/pats",
        headers=user.headers,
    )
    assert list_response.status_code == 200
    tokens = list_response.json()
    assert len(tokens) == 1
    assert tokens[0]["id"] == token_id
    assert tokens[0]["name"] == "My Integration Token"
    assert tokens[0]["token_display"] == token_display
    assert "token" not in tokens[0]

    auth_response = requests.get(
        f"{API_SERVER_URL}/me",
        headers={"Authorization": f"Bearer {raw_token}"},
    )
    assert auth_response.status_code == 200
    me_data = auth_response.json()
    assert me_data["email"] == user.email
    assert me_data["id"] == user.id

    revoke_response = requests.delete(
        f"{API_SERVER_URL}/user/pats/{token_id}",
        headers=user.headers,
    )
    assert revoke_response.status_code == 200

    revoked_auth_response = requests.get(
        f"{API_SERVER_URL}/me",
        headers={"Authorization": f"Bearer {raw_token}"},
    )
    assert revoked_auth_response.status_code == 403  # Revoked token returns 403

    list_after_revoke = requests.get(
        f"{API_SERVER_URL}/user/pats",
        headers=user.headers,
    )
    assert list_after_revoke.status_code == 200
    assert len(list_after_revoke.json()) == 0


def test_pat_user_isolation_and_authentication(reset: None) -> None:
    """
    PATs authenticate as real users, and users can only see/manage their own tokens.
    """
    user_a: DATestUser = UserManager.create(name="user_a")
    user_b: DATestUser = UserManager.create(name="user_b")

    user_a_tokens = []
    for i in range(2):
        response = requests.post(
            f"{API_SERVER_URL}/user/pats",
            json={"name": f"User A Token {i+1}", "expiration_days": 30},
            headers=user_a.headers,
        )
        assert response.status_code == 200
        user_a_tokens.append(
            {
                "id": response.json()["id"],
                "token": response.json()["token"],
            }
        )

    user_b_tokens = []
    for i in range(2):
        response = requests.post(
            f"{API_SERVER_URL}/user/pats",
            json={"name": f"User B Token {i+1}", "expiration_days": 30},
            headers=user_b.headers,
        )
        assert response.status_code == 200
        user_b_tokens.append(
            {
                "id": response.json()["id"],
                "token": response.json()["token"],
            }
        )

    for user, token_info in [(user_a, user_a_tokens[0]), (user_b, user_b_tokens[0])]:
        me_response = requests.get(
            f"{API_SERVER_URL}/me",
            headers={"Authorization": f"Bearer {token_info['token']}"},
        )
        assert me_response.status_code == 200
        me_data = me_response.json()
        assert me_data["email"] == user.email
        assert me_data["id"] == user.id

    user_a_list = requests.get(
        f"{API_SERVER_URL}/user/pats",
        headers=user_a.headers,
    )
    assert user_a_list.status_code == 200
    assert len(user_a_list.json()) == 2

    user_b_list = requests.get(
        f"{API_SERVER_URL}/user/pats",
        headers=user_b.headers,
    )
    assert user_b_list.status_code == 200
    assert len(user_b_list.json()) == 2

    delete_response = requests.delete(
        f"{API_SERVER_URL}/user/pats/{user_b_tokens[0]['id']}",
        headers={"Authorization": f"Bearer {user_a_tokens[0]['token']}"},
    )
    assert delete_response.status_code == 404

    user_b_list_after = requests.get(
        f"{API_SERVER_URL}/user/pats",
        headers=user_b.headers,
    )
    assert user_b_list_after.status_code == 200
    assert len(user_b_list_after.json()) == 2

    delete_fake = requests.delete(
        f"{API_SERVER_URL}/user/pats/999999",
        headers=user_a.headers,
    )
    assert delete_fake.status_code == 404


def test_pat_expiration_flow(reset: None) -> None:
    """Expiration timestamp is end-of-day (23:59:59 UTC); never-expiring tokens work; revoked tokens fail."""
    user: DATestUser = UserManager.create(name="expiration_user")

    create_response = requests.post(
        f"{API_SERVER_URL}/user/pats",
        json={"name": "Expiring Token", "expiration_days": 7},
        headers=user.headers,
    )
    assert create_response.status_code == 200
    token_data = create_response.json()

    assert token_data["expires_at"] is not None
    expires_at = datetime.fromisoformat(token_data["expires_at"].replace("Z", "+00:00"))

    assert expires_at.hour == 23
    assert expires_at.minute == 59
    assert expires_at.second == 59

    from datetime import timezone

    # Calculate expected end-of-day 7 days from now
    now = datetime.now(timezone.utc)
    expected_date = (now + timedelta(days=7)).date()
    expected_expiry = datetime.combine(expected_date, datetime.max.time()).replace(
        tzinfo=timezone.utc
    )
    # Allow for small timing differences (within a day)
    assert (
        abs((expires_at - expected_expiry).total_seconds()) < 86400
    )  # 1 day in seconds

    no_expiry_response = requests.post(
        f"{API_SERVER_URL}/user/pats",
        json={"name": "Never Expiring Token", "expiration_days": None},
        headers=user.headers,
    )
    assert no_expiry_response.status_code == 200
    no_expiry_data = no_expiry_response.json()
    assert no_expiry_data["expires_at"] is None

    never_expiring_token = no_expiry_data["token"]
    never_expiring_token_id = no_expiry_data["id"]
    auth_response = requests.get(
        f"{API_SERVER_URL}/me",
        headers={"Authorization": f"Bearer {never_expiring_token}"},
    )
    assert auth_response.status_code == 200

    revoke_response = requests.delete(
        f"{API_SERVER_URL}/user/pats/{never_expiring_token_id}",
        headers=user.headers,
    )
    assert revoke_response.status_code == 200

    revoked_auth_response = requests.get(
        f"{API_SERVER_URL}/me",
        headers={"Authorization": f"Bearer {never_expiring_token}"},
    )
    assert revoked_auth_response.status_code == 403  # Revoked token returns 403


def test_pat_validation_errors(reset: None) -> None:
    """Validate input errors: empty name, name too long, negative/zero expiration."""
    user: DATestUser = UserManager.create(name="validation_user")

    empty_name_response = requests.post(
        f"{API_SERVER_URL}/user/pats",
        json={"name": "", "expiration_days": 30},
        headers=user.headers,
    )
    assert empty_name_response.status_code == 422

    long_name = "a" * 101
    long_name_response = requests.post(
        f"{API_SERVER_URL}/user/pats",
        json={"name": long_name, "expiration_days": 30},
        headers=user.headers,
    )
    assert long_name_response.status_code == 422

    negative_exp_response = requests.post(
        f"{API_SERVER_URL}/user/pats",
        json={"name": "Test Token", "expiration_days": -1},
        headers=user.headers,
    )
    assert negative_exp_response.status_code == 422

    zero_exp_response = requests.post(
        f"{API_SERVER_URL}/user/pats",
        json={"name": "Test Token", "expiration_days": 0},
        headers=user.headers,
    )
    assert zero_exp_response.status_code == 422

    valid_name = "a" * 100
    valid_response = requests.post(
        f"{API_SERVER_URL}/user/pats",
        json={"name": valid_name, "expiration_days": 7},
        headers=user.headers,
    )
    assert valid_response.status_code == 200

    missing_name_response = requests.post(
        f"{API_SERVER_URL}/user/pats",
        json={"expiration_days": 30},
        headers=user.headers,
    )
    assert missing_name_response.status_code == 422


def test_pat_sorting_and_last_used(reset: None) -> None:
    """PATs are sorted by created_at DESC; last_used_at updates after authentication."""
    user: DATestUser = UserManager.create(name="sorting_user")

    token1_response = requests.post(
        f"{API_SERVER_URL}/user/pats",
        json={"name": "First Token", "expiration_days": 30},
        headers=user.headers,
    )
    assert token1_response.status_code == 200
    token1_data = token1_response.json()
    token1_raw = token1_data["token"]

    import time

    time.sleep(0.1)

    token2_response = requests.post(
        f"{API_SERVER_URL}/user/pats",
        json={"name": "Second Token", "expiration_days": 30},
        headers=user.headers,
    )
    assert token2_response.status_code == 200

    time.sleep(0.1)

    token3_response = requests.post(
        f"{API_SERVER_URL}/user/pats",
        json={"name": "Third Token", "expiration_days": 30},
        headers=user.headers,
    )
    assert token3_response.status_code == 200

    list_response = requests.get(
        f"{API_SERVER_URL}/user/pats",
        headers=user.headers,
    )
    assert list_response.status_code == 200
    tokens = list_response.json()
    assert len(tokens) == 3

    assert tokens[0]["name"] == "Third Token"
    assert tokens[1]["name"] == "Second Token"
    assert tokens[2]["name"] == "First Token"

    for token in tokens:
        assert token["last_used_at"] is None

    auth_response = requests.get(
        f"{API_SERVER_URL}/me",
        headers={"Authorization": f"Bearer {token1_raw}"},
    )
    assert auth_response.status_code == 200

    time.sleep(0.5)

    list_after_use = requests.get(
        f"{API_SERVER_URL}/user/pats",
        headers=user.headers,
    )
    assert list_after_use.status_code == 200
    tokens_after_use = list_after_use.json()

    token1_after_use = next(t for t in tokens_after_use if t["name"] == "First Token")
    assert token1_after_use["last_used_at"] is not None

    token2_after_use = next(t for t in tokens_after_use if t["name"] == "Second Token")
    token3_after_use = next(t for t in tokens_after_use if t["name"] == "Third Token")
    assert token2_after_use["last_used_at"] is None
    assert token3_after_use["last_used_at"] is None


def test_pat_role_based_access_control(reset: None) -> None:
    """
    PATs inherit user roles and permissions:
    - Admin PAT: Full access to admin-only endpoints
    - Curator/Global Curator PATs: Access to management endpoints
    - Basic PAT: Denied access to admin and management endpoints
    """
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

    admin_pat_response = requests.post(
        f"{API_SERVER_URL}/user/pats",
        json={"name": "Admin Token", "expiration_days": 7},
        headers=admin_user.headers,
    )
    assert admin_pat_response.status_code == 200
    admin_token = admin_pat_response.json()["token"]

    basic_pat_response = requests.post(
        f"{API_SERVER_URL}/user/pats",
        json={"name": "Basic Token", "expiration_days": 7},
        headers=basic_user.headers,
    )
    assert basic_pat_response.status_code == 200
    basic_token = basic_pat_response.json()["token"]

    curator_pat_response = requests.post(
        f"{API_SERVER_URL}/user/pats",
        json={"name": "Curator Token", "expiration_days": 7},
        headers=curator_user.headers,
    )
    assert curator_pat_response.status_code == 200
    curator_token = curator_pat_response.json()["token"]

    global_curator_pat_response = requests.post(
        f"{API_SERVER_URL}/user/pats",
        json={"name": "Global Curator Token", "expiration_days": 7},
        headers=global_curator_user.headers,
    )
    assert global_curator_pat_response.status_code == 200
    global_curator_token = global_curator_pat_response.json()["token"]

    print("\n[Test] Admin PAT accessing admin-only endpoint...")
    admin_endpoint_response = requests.get(
        f"{API_SERVER_URL}/admin/api-key",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert admin_endpoint_response.status_code == 200
    print("[✓] Admin PAT successfully accessed /admin/api-key")

    print("\n[Test] Basic PAT accessing admin endpoint...")
    basic_admin_response = requests.get(
        f"{API_SERVER_URL}/admin/api-key",
        headers={"Authorization": f"Bearer {basic_token}"},
    )
    assert basic_admin_response.status_code == 403
    print("[✓] Basic PAT correctly denied access (403) to /admin/api-key")

    print("\n[Test] Curator PAT accessing admin-only endpoint...")
    curator_admin_response = requests.get(
        f"{API_SERVER_URL}/admin/api-key",
        headers={"Authorization": f"Bearer {curator_token}"},
    )
    assert curator_admin_response.status_code == 403
    print("[✓] Curator PAT correctly denied access (403) to /admin/api-key")

    print("\n[Test] Global Curator PAT accessing admin-only endpoint...")
    global_curator_admin_response = requests.get(
        f"{API_SERVER_URL}/admin/api-key",
        headers={"Authorization": f"Bearer {global_curator_token}"},
    )
    assert global_curator_admin_response.status_code == 403
    print("[✓] Global Curator PAT correctly denied access (403) to /admin/api-key")

    print("\n[Test] Testing management endpoint access for curators...")

    admin_manage_response = requests.get(
        f"{API_SERVER_URL}/manage/admin/connector",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert admin_manage_response.status_code == 200
    print("[✓] Admin PAT can access /manage/admin/connector")

    curator_manage_response = requests.get(
        f"{API_SERVER_URL}/manage/admin/connector",
        headers={"Authorization": f"Bearer {curator_token}"},
    )
    assert curator_manage_response.status_code == 200
    print("[✓] Curator PAT can access /manage/admin/connector")

    global_curator_manage_response = requests.get(
        f"{API_SERVER_URL}/manage/admin/connector",
        headers={"Authorization": f"Bearer {global_curator_token}"},
    )
    assert global_curator_manage_response.status_code == 200
    print("[✓] Global Curator PAT can access /manage/admin/connector")

    basic_manage_response = requests.get(
        f"{API_SERVER_URL}/manage/admin/connector",
        headers={"Authorization": f"Bearer {basic_token}"},
    )
    assert basic_manage_response.status_code in [403, 401]
    print(
        f"[✓] Basic PAT correctly denied access ({basic_manage_response.status_code}) to /manage/admin/connector"
    )

    print("\n[Test] Verifying PATs authenticate as correct users with correct roles...")

    admin_me = requests.get(
        f"{API_SERVER_URL}/me",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert admin_me.status_code == 200
    assert admin_me.json()["email"] == admin_user.email
    assert admin_me.json()["role"] == UserRole.ADMIN.value

    basic_me = requests.get(
        f"{API_SERVER_URL}/me",
        headers={"Authorization": f"Bearer {basic_token}"},
    )
    assert basic_me.status_code == 200
    assert basic_me.json()["email"] == basic_user.email
    assert basic_me.json()["role"] == UserRole.BASIC.value

    curator_me = requests.get(
        f"{API_SERVER_URL}/me",
        headers={"Authorization": f"Bearer {curator_token}"},
    )
    assert curator_me.status_code == 200
    assert curator_me.json()["email"] == curator_user.email
    assert curator_me.json()["role"] == UserRole.CURATOR.value

    global_curator_me = requests.get(
        f"{API_SERVER_URL}/me",
        headers={"Authorization": f"Bearer {global_curator_token}"},
    )
    assert global_curator_me.status_code == 200
    assert global_curator_me.json()["email"] == global_curator_user.email
    assert global_curator_me.json()["role"] == UserRole.GLOBAL_CURATOR.value

    print("[✓] All PATs authenticate with correct user identity and role")

    print("\n[Test] All PATs can access basic endpoints...")
    for token, user_name in [
        (admin_token, "Admin"),
        (basic_token, "Basic"),
        (curator_token, "Curator"),
        (global_curator_token, "Global Curator"),
    ]:
        persona_response = requests.get(
            f"{API_SERVER_URL}/persona",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert persona_response.status_code == 200
        print(f"[✓] {user_name} PAT can access /persona endpoint")

    print("\n[✓] All role-based access control tests passed!")
    print("Summary:")
    print(
        "  - Admin PAT: Full access to admin-only endpoints (/admin/*, /manage/admin/*)"
    )
    print(
        "  - Curator PAT: Access to management endpoints (/manage/admin/*), denied on admin-only (/admin/*)"
    )
    print(
        "  - Global Curator PAT: Access to management endpoints (/manage/admin/*), denied on admin-only (/admin/*)"
    )
    print("  - Basic PAT: Denied access to admin and management endpoints")
    print("  - All PATs: Can access basic endpoints (/persona, /me, etc.)")
    print("  - All PATs: Authenticate with correct user identity and role")
