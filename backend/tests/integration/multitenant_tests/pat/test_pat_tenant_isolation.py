"""
Multi-tenant integration tests for Personal Access Token (PAT) API.

Verifies PATs are properly isolated between tenants.
"""

from uuid import uuid4

import requests

from onyx.db.models import UserRole
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.managers.pat import PATManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.test_models import DATestUser


def test_pat_tenant_isolation(reset_multitenant: None) -> None:
    """
    Test that PATs are fully isolated between tenants:
    - Users only see their own tenant's PATs
    - Users cannot revoke another tenant's PATs
    - Revoking in one tenant doesn't affect another
    """
    unique = uuid4().hex

    # Create admin users for two tenants
    admin_user1: DATestUser = UserManager.create(
        email=f"pat_admin1+{unique}@onyx-test.com",
    )
    assert UserManager.is_role(admin_user1, UserRole.ADMIN)

    admin_user2: DATestUser = UserManager.create(
        email=f"pat_admin2+{unique}@onyx-test.com",
    )
    assert UserManager.is_role(admin_user2, UserRole.ADMIN)

    # Create PATs for each tenant
    pat1 = PATManager.create(
        name="Tenant 1 Token",
        expiration_days=30,
        user_performing_action=admin_user1,
    )
    assert pat1.token is not None

    pat2 = PATManager.create(
        name="Tenant 2 Token",
        expiration_days=30,
        user_performing_action=admin_user2,
    )
    assert pat2.token is not None

    # Verify list isolation - each user only sees their own PATs
    tenant1_pats = PATManager.list(admin_user1)
    tenant2_pats = PATManager.list(admin_user2)
    assert len(tenant1_pats) == 1 and tenant1_pats[0].name == "Tenant 1 Token"
    assert len(tenant2_pats) == 1 and tenant2_pats[0].name == "Tenant 2 Token"

    # Verify PAT1 cannot access tenant 2's data:
    # When authenticating with PAT1, we should only see tenant 1's user and PATs
    auth1 = PATManager.authenticate(pat1.token)
    assert auth1.status_code == 200
    assert auth1.json()["email"] == admin_user1.email  # Returns tenant 1's user
    assert auth1.json()["email"] != admin_user2.email  # NOT tenant 2's user

    # Use PAT1 to list PATs - should only see tenant 1's PATs, not tenant 2's
    pat1_list_response = requests.get(
        f"{API_SERVER_URL}/user/pats",
        headers=PATManager.get_auth_headers(pat1.token),
        timeout=60,
    )
    assert pat1_list_response.status_code == 200
    pat1_visible_pats = pat1_list_response.json()
    assert len(pat1_visible_pats) == 1
    assert pat1_visible_pats[0]["name"] == "Tenant 1 Token"
    # PAT1 cannot see PAT2 (tenant 2's data is inaccessible)
    assert all(p["name"] != "Tenant 2 Token" for p in pat1_visible_pats)

    # Verify cross-tenant revoke fails (404 - PAT doesn't exist in other tenant)
    cross_revoke = requests.delete(
        f"{API_SERVER_URL}/user/pats/{pat2.id}",
        headers=admin_user1.headers,
        cookies=admin_user1.cookies,
        timeout=60,
    )
    assert cross_revoke.status_code == 404

    # Verify PAT2 still exists after failed cross-tenant revoke
    assert len(PATManager.list(admin_user2)) == 1

    # Revoke PAT1 in tenant 1
    PATManager.revoke(pat1.id, admin_user1)

    # Verify tenant isolation after revoke - PAT2 unaffected
    assert PATManager.authenticate(pat1.token).status_code == 403  # Revoked
    assert PATManager.authenticate(pat2.token).status_code == 200  # Still works
    assert len(PATManager.list(admin_user1)) == 0
    assert len(PATManager.list(admin_user2)) == 1
