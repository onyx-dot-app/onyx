"""Shared fixtures for permission integration tests.

Creates six user types that cover the full access spectrum:
  - admin_user:               STANDARD account, Admin group
  - basic_user:               STANDARD account, Basic group
  - limited_service_account:  SERVICE_ACCOUNT, no groups
  - bot_user:                 BOT account type (no web login)
  - ext_perm_user:            EXT_PERM_USER account type (no web login)
  - anonymous (no fixture):   unauthenticated request (empty headers)

Plus a ``permission_holder_user_factory`` fixture used by the custom-
permission test files to materialize a 7th user type per test module:
a STANDARD user whose only non-BASIC permission is the one under test,
granted via a fresh user group.

All fixtures are module-scoped because permission tests are read-only
(GET requests checking status codes) and don't mutate state between tests.
This avoids a costly full reset per test.
"""

from collections.abc import Callable

import pytest

from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.pat import create_pat
from onyx.db.users import add_slack_user_if_not_exists
from onyx.db.users import batch_add_ext_perm_user_if_not_exists
from tests.integration.common_utils.managers.api_key import APIKeyManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.managers.user_group import UserGroupManager
from tests.integration.common_utils.reset import reset_all
from tests.integration.common_utils.test_models import DATestAPIKey
from tests.integration.common_utils.test_models import DATestUser


def _attach_group_with_permission(
    *,
    permission: str,
    admin_user: DATestUser,
    user_ids: list[str],
    group_name: str,
) -> None:
    """Create a fresh user group containing ``user_ids`` and grant it exactly
    one permission. Synchronous: permission is written to every member's
    ``effective_permissions`` column before this returns — no celery sync
    needed because ``set_group_permissions_bulk__no_commit`` calls
    ``recompute_permissions_for_group__no_commit`` in-process.
    """
    group = UserGroupManager.create(
        name=group_name,
        user_ids=user_ids,
        cc_pair_ids=[],
        user_performing_action=admin_user,
    )
    set_resp = UserGroupManager.set_permissions(
        user_group=group,
        permissions=[permission],
        user_performing_action=admin_user,
    )
    set_resp.raise_for_status()


@pytest.fixture(scope="module")
def module_reset() -> None:
    """Reset once per test module instead of per test."""
    reset_all()


@pytest.fixture(scope="module")
def permission_admin_user(module_reset: None) -> DATestUser:  # noqa: ARG001
    """First registered user — automatically promoted to admin (full_admin_panel_access)."""
    return UserManager.create(name="perm_admin")


@pytest.fixture(scope="module")
def permission_basic_user(
    permission_admin_user: DATestUser,  # noqa: ARG001
) -> DATestUser:
    """Second registered user — joins the default Basic user group with only basic permissions."""
    return UserManager.create(name="perm_basic")


@pytest.fixture(scope="module")
def limited_service_account(
    permission_admin_user: DATestUser,
) -> DATestAPIKey:
    """API key with no groups — creates a SERVICE_ACCOUNT with no group membership."""
    return APIKeyManager.create(
        group_ids=[],
        user_performing_action=permission_admin_user,
        name="limited_svc_key",
    )


@pytest.fixture(scope="module")
def bot_user_headers(
    permission_admin_user: DATestUser,  # noqa: ARG001
) -> dict[str, str]:
    """Authorization headers that authenticate as a BOT account type user.

    BOT users can't log in via web, so we create one in the DB directly.
    """
    with get_session_with_current_tenant() as db_session:
        user = add_slack_user_if_not_exists(db_session, email="bot_test@example.com")
        _, raw_token = create_pat(
            db_session=db_session,
            user_id=user.id,
            name="bot_test_pat",
            expiration_days=None,
        )
        db_session.commit()
    return {"Authorization": f"Bearer {raw_token}"}


@pytest.fixture(scope="module")
def ext_perm_user_headers(
    permission_admin_user: DATestUser,  # noqa: ARG001
) -> dict[str, str]:
    """Authorization headers that authenticate as an EXT_PERM_USER account type user.

    EXT_PERM_USER users can't log in via web, so we create one in the DB directly.
    """
    with get_session_with_current_tenant() as db_session:
        users = batch_add_ext_perm_user_if_not_exists(
            db_session, emails=["ext_perm_test@example.com"]
        )
        _, raw_token = create_pat(
            db_session=db_session,
            user_id=users[0].id,
            name="ext_perm_test_pat",
            expiration_days=None,
        )
        db_session.commit()
    return {"Authorization": f"Bearer {raw_token}"}


@pytest.fixture(scope="module")
def permission_holder_user_factory(
    permission_admin_user: DATestUser,
) -> Callable[[str], DATestUser]:
    """Factory: STANDARD user whose only non-BASIC permission is ``permission``.

    Each call creates a fresh user group containing only that user and
    grants the group exactly one permission. This is the end-to-end path a
    real admin uses to delegate a capability, so the test exercises the
    group → effective_permissions expansion rather than stubbing it.

    Module-scoped and memoized by permission string. Requires the
    user-group permission API (Enterprise-only) — callers must guard their
    module with the ``ENABLE_PAID_ENTERPRISE_EDITION_FEATURES`` skipif.
    """

    cache: dict[str, DATestUser] = {}

    def _make(permission: str) -> DATestUser:
        if permission in cache:
            return cache[permission]

        slug = permission.replace(":", "_")
        user = UserManager.create(name=f"perm_{slug}_holder")
        _attach_group_with_permission(
            permission=permission,
            admin_user=permission_admin_user,
            user_ids=[user.id],
            group_name=f"perm-{slug}",
        )
        cache[permission] = user
        return user

    return _make


@pytest.fixture(scope="module")
def permission_holder_service_account_factory(
    permission_admin_user: DATestUser,
) -> Callable[[str], DATestAPIKey]:
    """Factory: SERVICE_ACCOUNT whose only non-BASIC permission is ``permission``.

    Service accounts are part of the same group-based permission model as
    standard users. We create an API key (which creates a backing SA User)
    and add that User to a fresh group granting exactly one permission.

    Module-scoped and memoized by permission string. EE-only, same guard
    as ``permission_holder_user_factory``.
    """

    cache: dict[str, DATestAPIKey] = {}

    def _make(permission: str) -> DATestAPIKey:
        if permission in cache:
            return cache[permission]

        slug = permission.replace(":", "_")
        # Create SA with no initial group membership; we add it to a
        # custom group immediately afterwards to avoid a 2-step API flow
        # of (create with group, then set permissions on that group).
        api_key = APIKeyManager.create(
            group_ids=[],
            user_performing_action=permission_admin_user,
            name=f"perm_{slug}_sa",
        )
        _attach_group_with_permission(
            permission=permission,
            admin_user=permission_admin_user,
            user_ids=[str(api_key.user_id)],
            group_name=f"perm-sa-{slug}",
        )
        cache[permission] = api_key
        return api_key

    return _make
