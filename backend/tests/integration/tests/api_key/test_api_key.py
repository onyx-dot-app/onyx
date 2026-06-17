from uuid import UUID

from onyx.db.enums import AccountType
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.api_key import APIKeyManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.managers.user_group import UserGroupManager
from tests.integration.common_utils.test_models import DATestAPIKey
from tests.integration.common_utils.test_models import DATestUser


def _get_default_group_ids(
    admin_user: DATestUser,
) -> tuple[int, int]:
    """Return (admin_group_id, basic_group_id) from default groups."""
    admin_group = UserGroupManager.get_default(
        user_performing_action=admin_user, name="Admin"
    )
    basic_group = UserGroupManager.get_default(
        user_performing_action=admin_user, name="Basic"
    )
    return admin_group.id, basic_group.id


def _get_service_account_account_type(
    admin_user: DATestUser,
    api_key_user_id: UUID,
) -> AccountType:
    """Fetch the account_type of a service account user via the user listing API."""
    response = client.get(
        f"{API_SERVER_URL}/manage/users",
        headers=admin_user.headers,
        params={"include_api_keys": "true"},
    )
    response.raise_for_status()
    data = response.json()
    user_id_str = str(api_key_user_id)
    for user in data["accepted"]:
        if user["id"] == user_id_str:
            return AccountType(user["account_type"])
    raise AssertionError(
        f"Service account user {user_id_str} not found in user listing"
    )


def _get_default_group_user_ids(
    admin_user: DATestUser,
) -> tuple[set[str], set[str]]:
    """Return (admin_group_user_ids, basic_group_user_ids) from default groups."""
    admin_group = UserGroupManager.get_default(
        user_performing_action=admin_user, name="Admin"
    )
    basic_group = UserGroupManager.get_default(
        user_performing_action=admin_user, name="Basic"
    )
    admin_ids = {str(u.id) for u in admin_group.users}
    basic_ids = {str(u.id) for u in basic_group.users}
    return admin_ids, basic_ids


def test_no_groups(reset: None) -> None:  # noqa: ARG001
    """Verify that an API key with no group membership has limited access."""

    admin_user: DATestUser = UserManager.create(name="admin_user")

    api_key: DATestAPIKey = APIKeyManager.create(
        group_ids=[],
        user_performing_action=admin_user,
    )

    # test limited endpoint (accessible without groups)
    response = client.get(
        f"{API_SERVER_URL}/persona/0",
        headers=api_key.headers,
    )
    assert response.status_code == 200

    # test admin endpoints (should be blocked)
    response = client.get(
        f"{API_SERVER_URL}/admin/api-key",
        headers=api_key.headers,
    )
    assert response.status_code == 403


def test_api_key_no_groups_service_account(reset: None) -> None:  # noqa: ARG001
    """API key with no groups: account_type is SERVICE_ACCOUNT, no group membership."""
    admin_user: DATestUser = UserManager.create(name="admin_user")

    api_key: DATestAPIKey = APIKeyManager.create(
        group_ids=[],
        user_performing_action=admin_user,
    )

    # Verify account_type
    account_type = _get_service_account_account_type(admin_user, api_key.user_id)
    assert account_type == AccountType.SERVICE_ACCOUNT, (
        f"Expected account_type={AccountType.SERVICE_ACCOUNT}, got {account_type}"
    )

    # Verify no group membership
    admin_ids, basic_ids = _get_default_group_user_ids(admin_user)
    user_id_str = str(api_key.user_id)
    assert user_id_str not in admin_ids, (
        "No-groups API key should NOT be in Admin default group"
    )
    assert user_id_str not in basic_ids, (
        "No-groups API key should NOT be in Basic default group"
    )


def test_api_key_basic_group_service_account(reset: None) -> None:  # noqa: ARG001
    """API key in Basic group: account_type is SERVICE_ACCOUNT, in Basic group only."""
    admin_user: DATestUser = UserManager.create(name="admin_user")
    _admin_group_id, basic_group_id = _get_default_group_ids(admin_user)

    api_key: DATestAPIKey = APIKeyManager.create(
        group_ids=[basic_group_id],
        user_performing_action=admin_user,
    )

    # Verify account_type
    account_type = _get_service_account_account_type(admin_user, api_key.user_id)
    assert account_type == AccountType.SERVICE_ACCOUNT, (
        f"Expected account_type={AccountType.SERVICE_ACCOUNT}, got {account_type}"
    )

    # Verify Basic group membership
    admin_ids, basic_ids = _get_default_group_user_ids(admin_user)
    user_id_str = str(api_key.user_id)
    assert user_id_str in basic_ids, (
        "Basic-group API key should be in Basic default group"
    )
    assert user_id_str not in admin_ids, (
        "Basic-group API key should NOT be in Admin default group"
    )


def test_api_key_admin_group_service_account(reset: None) -> None:  # noqa: ARG001
    """API key in Admin group: account_type is SERVICE_ACCOUNT, in Admin group only."""
    admin_user: DATestUser = UserManager.create(name="admin_user")
    admin_group_id, _basic_group_id = _get_default_group_ids(admin_user)

    api_key: DATestAPIKey = APIKeyManager.create(
        group_ids=[admin_group_id],
        user_performing_action=admin_user,
    )

    # Verify account_type
    account_type = _get_service_account_account_type(admin_user, api_key.user_id)
    assert account_type == AccountType.SERVICE_ACCOUNT, (
        f"Expected account_type={AccountType.SERVICE_ACCOUNT}, got {account_type}"
    )

    # Verify Admin group membership
    admin_ids, basic_ids = _get_default_group_user_ids(admin_user)
    user_id_str = str(api_key.user_id)
    assert user_id_str in admin_ids, (
        "Admin-group API key should be in Admin default group"
    )
    assert user_id_str not in basic_ids, (
        "Admin-group API key should NOT be in Basic default group"
    )


def test_no_groups_key_blocked_by_current_user(reset: None) -> None:  # noqa: ARG001
    """An API key with no groups (no permissions) should be rejected
    by endpoints behind current_user but allowed through current_limited_user."""
    admin_user: DATestUser = UserManager.create(name="admin_user")

    limited_key: DATestAPIKey = APIKeyManager.create(
        group_ids=[],
        user_performing_action=admin_user,
    )

    # current_limited_user endpoint → should succeed
    resp = client.get(
        f"{API_SERVER_URL}/persona/0",
        headers=limited_key.headers,
    )
    assert resp.status_code == 200, (
        f"No-groups key should access /persona/0, got {resp.status_code}: {resp.text}"
    )

    # current_user endpoint → should be blocked
    resp = client.get(
        f"{API_SERVER_URL}/query/valid-tags",
        headers=limited_key.headers,
    )
    assert resp.status_code == 403, (
        f"No-groups key should be blocked from /query/valid-tags, got {resp.status_code}: {resp.text}"
    )


def test_basic_group_key_passes_current_user(reset: None) -> None:  # noqa: ARG001
    """An API key in the Basic group should pass the current_user dependency."""
    admin_user: DATestUser = UserManager.create(name="admin_user")
    _admin_group_id, basic_group_id = _get_default_group_ids(admin_user)

    basic_key: DATestAPIKey = APIKeyManager.create(
        group_ids=[basic_group_id],
        user_performing_action=admin_user,
    )

    resp = client.get(
        f"{API_SERVER_URL}/query/valid-tags",
        headers=basic_key.headers,
    )
    assert resp.status_code == 200, (
        f"Basic-group key should access /query/valid-tags, got {resp.status_code}: {resp.text}"
    )


def test_admin_group_key_passes_current_user(reset: None) -> None:  # noqa: ARG001
    """An API key in the Admin group should pass the current_user dependency."""
    admin_user: DATestUser = UserManager.create(name="admin_user")
    admin_group_id, _basic_group_id = _get_default_group_ids(admin_user)

    admin_key: DATestAPIKey = APIKeyManager.create(
        group_ids=[admin_group_id],
        user_performing_action=admin_user,
    )

    resp = client.get(
        f"{API_SERVER_URL}/query/valid-tags",
        headers=admin_key.headers,
    )
    assert resp.status_code == 200, (
        f"Admin-group key should access /query/valid-tags, got {resp.status_code}: {resp.text}"
    )


def test_delete_admin_api_key_with_group_membership(reset: None) -> None:  # noqa: ARG001
    """Deleting an Admin-group API key must clean up its default-group membership.

    Regression test for #11118: the synthetic SERVICE_ACCOUNT user backing an
    API key is auto-assigned to its group(s) at creation, so deleting the key
    must remove that user__user_group row before the user is deleted —
    otherwise the FK constraint fires.
    """
    admin_user: DATestUser = UserManager.create(name="admin_user")
    admin_group_id, _ = _get_default_group_ids(admin_user)

    admin_key: DATestAPIKey = APIKeyManager.create(
        group_ids=[admin_group_id],
        user_performing_action=admin_user,
    )

    admin_ids_before, _ = _get_default_group_user_ids(admin_user)
    assert str(admin_key.user_id) in admin_ids_before

    APIKeyManager.delete(api_key=admin_key, user_performing_action=admin_user)
    APIKeyManager.verify(
        api_key=admin_key,
        user_performing_action=admin_user,
        verify_deleted=True,
    )

    admin_ids_after, _ = _get_default_group_user_ids(admin_user)
    assert str(admin_key.user_id) not in admin_ids_after


def test_delete_basic_api_key_with_group_membership(reset: None) -> None:  # noqa: ARG001
    """Same regression as the Admin-group case, but for the Basic group."""
    admin_user: DATestUser = UserManager.create(name="admin_user")
    _, basic_group_id = _get_default_group_ids(admin_user)

    basic_key: DATestAPIKey = APIKeyManager.create(
        group_ids=[basic_group_id],
        user_performing_action=admin_user,
    )

    _, basic_ids_before = _get_default_group_user_ids(admin_user)
    assert str(basic_key.user_id) in basic_ids_before

    APIKeyManager.delete(api_key=basic_key, user_performing_action=admin_user)
    APIKeyManager.verify(
        api_key=basic_key,
        user_performing_action=admin_user,
        verify_deleted=True,
    )

    _, basic_ids_after = _get_default_group_user_ids(admin_user)
    assert str(basic_key.user_id) not in basic_ids_after
