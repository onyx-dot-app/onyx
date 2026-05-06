"""Shared fixtures for permission integration tests.

Creates six user types that cover the full access spectrum:
  - admin_user:               STANDARD account, ADMIN role
  - basic_user:               STANDARD account, BASIC role
  - limited_service_account:  SERVICE_ACCOUNT, LIMITED role (no group)
  - bot_user:                 BOT account, SLACK_USER role
  - ext_perm_user:            EXT_PERM_USER account, EXT_PERM_USER role
  - anonymous (no fixture):   unauthenticated request (empty headers)

All fixtures are module-scoped because permission tests are read-only
(GET requests checking status codes) and don't mutate state between tests.
This avoids a costly full reset per test.
"""

import pytest

from onyx.auth.schemas import UserRole
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.pat import create_pat
from onyx.db.users import add_slack_user_if_not_exists
from onyx.db.users import batch_add_ext_perm_user_if_not_exists
from tests.integration.common_utils.managers.api_key import APIKeyManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.reset import reset_all
from tests.integration.common_utils.test_models import DATestAPIKey
from tests.integration.common_utils.test_models import DATestUser


@pytest.fixture(scope="module")
def module_reset() -> None:
    """Reset once per test module instead of per test."""
    reset_all()


@pytest.fixture(scope="module")
def permission_admin_user(module_reset: None) -> DATestUser:  # noqa: ARG001
    """First registered user — automatically gets ADMIN role."""
    return UserManager.create(name="perm_admin")


@pytest.fixture(scope="module")
def permission_basic_user(
    permission_admin_user: DATestUser,  # noqa: ARG001
) -> DATestUser:
    """Second registered user — gets BASIC role."""
    return UserManager.create(name="perm_basic")


@pytest.fixture(scope="module")
def limited_service_account(
    permission_admin_user: DATestUser,
) -> DATestAPIKey:
    """API key with LIMITED role — creates a SERVICE_ACCOUNT with no group membership."""
    return APIKeyManager.create(
        api_key_role=UserRole.LIMITED,
        user_performing_action=permission_admin_user,
        name="limited_svc_key",
    )


@pytest.fixture(scope="module")
def bot_user_headers(
    permission_admin_user: DATestUser,  # noqa: ARG001
) -> dict[str, str]:
    """BOT account (SLACK_USER role) authenticated via PAT.

    BOT users can't log in via web — we create one in the DB directly
    and issue a PAT for authentication.
    """
    with get_session_with_current_tenant() as db_session:
        user = add_slack_user_if_not_exists(db_session, email="bot_test@example.com")
        _, raw_token = create_pat(
            db_session=db_session,
            user_id=user.id,
            name="bot_test_pat",
            expiration_days=None,
        )
    return {"Authorization": f"Bearer {raw_token}"}


@pytest.fixture(scope="module")
def ext_perm_user_headers(
    permission_admin_user: DATestUser,  # noqa: ARG001
) -> dict[str, str]:
    """EXT_PERM_USER account authenticated via PAT.

    EXT_PERM_USER users can't log in via web — we create one in the DB
    directly and issue a PAT for authentication.
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
    return {"Authorization": f"Bearer {raw_token}"}
