from uuid import UUID

from onyx.auth.schemas import UserRole
from onyx.db.enums import AccountType
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.api_key import APIKeyManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.managers.user_group import UserGroupManager
from tests.integration.common_utils.test_models import DATestAPIKey
from tests.integration.common_utils.test_models import DATestUser


def test_limited(reset: None) -> None:  # noqa: ARG001
    """Verify that with a limited role key, limited endpoints are accessible and
    others are not."""

    # Creating an admin user (first user created is automatically an admin)
    admin_user: DATestUser = UserManager.create(name="admin_user")

    api_key: DATestAPIKey = APIKeyManager.create(
        api_key_role=UserRole.LIMITED,
        user_performing_action=admin_user,
    )

    # test limited endpoint
    response = client.get(
        f"{API_SERVER_URL}/persona/0",
        headers=api_key.headers,
    )
    assert response.status_code == 200

    # test admin endpoints
    response = client.get(
        f"{API_SERVER_URL}/admin/api-key",
        headers=api_key.headers,
    )
    assert response.status_code == 403


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
    all_groups = UserGroupManager.get_all(
        user_performing_action=admin_user,
        include_default=True,
    )
    admin_group = next(
        (g for g in all_groups if g.name == "Admin" and g.is_default), None
    )
    basic_group = next(
        (g for g in all_groups if g.name == "Basic" and g.is_default), None
    )
    assert admin_group is not None, "Admin default group not found"
    assert basic_group is not None, "Basic default group not found"

    admin_ids = {str(u.id) for u in admin_group.users}
    basic_ids = {str(u.id) for u in basic_group.users}
    return admin_ids, basic_ids


def test_api_key_limited_service_account(reset: None) -> None:  # noqa: ARG001
    """LIMITED role API key: account_type is SERVICE_ACCOUNT, no group membership."""
    admin_user: DATestUser = UserManager.create(name="admin_user")

    api_key: DATestAPIKey = APIKeyManager.create(
        api_key_role=UserRole.LIMITED,
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
        "LIMITED API key should NOT be in Admin default group"
    )
    assert user_id_str not in basic_ids, (
        "LIMITED API key should NOT be in Basic default group"
    )


def test_api_key_basic_service_account(reset: None) -> None:  # noqa: ARG001
    """BASIC role API key: account_type is SERVICE_ACCOUNT, in Basic group only."""
    admin_user: DATestUser = UserManager.create(name="admin_user")

    api_key: DATestAPIKey = APIKeyManager.create(
        api_key_role=UserRole.BASIC,
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
    assert user_id_str in basic_ids, "BASIC API key should be in Basic default group"
    assert user_id_str not in admin_ids, (
        "BASIC API key should NOT be in Admin default group"
    )


def test_api_key_admin_service_account(reset: None) -> None:  # noqa: ARG001
    """ADMIN role API key: account_type is SERVICE_ACCOUNT, in Admin group only."""
    admin_user: DATestUser = UserManager.create(name="admin_user")

    api_key: DATestAPIKey = APIKeyManager.create(
        api_key_role=UserRole.ADMIN,
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
    assert user_id_str in admin_ids, "ADMIN API key should be in Admin default group"
    assert user_id_str not in basic_ids, (
        "ADMIN API key should NOT be in Basic default group"
    )


def test_limited_key_blocked_by_current_user(reset: None) -> None:  # noqa: ARG001
    """A LIMITED API key (service account, chat scope only) should be rejected
    by BASIC_ACCESS-scoped endpoints but allowed through current_limited_user."""
    admin_user: DATestUser = UserManager.create(name="admin_user")

    limited_key: DATestAPIKey = APIKeyManager.create(
        api_key_role=UserRole.LIMITED,
        user_performing_action=admin_user,
    )

    # current_limited_user endpoint → should succeed
    resp = client.get(
        f"{API_SERVER_URL}/persona/0",
        headers=limited_key.headers,
    )
    assert resp.status_code == 200, (
        f"Limited key should access /persona/0, got {resp.status_code}: {resp.text}"
    )

    # current_user endpoint → should be blocked
    resp = client.get(
        f"{API_SERVER_URL}/query/valid-tags",
        headers=limited_key.headers,
    )
    assert resp.status_code == 403, (
        f"Limited key should be blocked from /query/valid-tags, got {resp.status_code}: {resp.text}"
    )


def test_basic_key_passes_current_user(reset: None) -> None:  # noqa: ARG001
    """A BASIC API key should pass the current_user dependency."""
    admin_user: DATestUser = UserManager.create(name="admin_user")

    basic_key: DATestAPIKey = APIKeyManager.create(
        api_key_role=UserRole.BASIC,
        user_performing_action=admin_user,
    )

    resp = client.get(
        f"{API_SERVER_URL}/query/valid-tags",
        headers=basic_key.headers,
    )
    assert resp.status_code == 200, (
        f"Basic key should access /query/valid-tags, got {resp.status_code}: {resp.text}"
    )


def test_admin_key_passes_current_user(reset: None) -> None:  # noqa: ARG001
    """An ADMIN API key should pass the current_user dependency."""
    admin_user: DATestUser = UserManager.create(name="admin_user")

    admin_key: DATestAPIKey = APIKeyManager.create(
        api_key_role=UserRole.ADMIN,
        user_performing_action=admin_user,
    )

    resp = client.get(
        f"{API_SERVER_URL}/query/valid-tags",
        headers=admin_key.headers,
    )
    assert resp.status_code == 200, (
        f"Admin key should access /query/valid-tags, got {resp.status_code}: {resp.text}"
    )


def test_delete_admin_api_key_with_group_membership(reset: None) -> None:  # noqa: ARG001
    """Deleting an ADMIN API key must clean up its default-group membership.

    Regression test for #11118: the synthetic SERVICE_ACCOUNT user backing an
    ADMIN/BASIC API key is auto-assigned to a default group at creation, so
    deleting the key must remove that user__user_group row before the user is
    deleted — otherwise the FK constraint fires.
    """
    admin_user: DATestUser = UserManager.create(name="admin_user")

    admin_key: DATestAPIKey = APIKeyManager.create(
        api_key_role=UserRole.ADMIN,
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
    """Same regression as the ADMIN case, but for BASIC role / Basic group."""
    admin_user: DATestUser = UserManager.create(name="admin_user")

    basic_key: DATestAPIKey = APIKeyManager.create(
        api_key_role=UserRole.BASIC,
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
