"""Integration tests for MANAGE_BOTS permission gate.

MANAGE_BOTS protects the Slack-bot admin endpoints in
``backend/onyx/server/manage/slack_bot.py`` (router prefix ``/manage``)
and the Discord-bot admin endpoints in
``backend/onyx/server/manage/discord_bot/api.py`` (router prefix
``/manage/admin/discord-bot``).
"""

import os
from typing import Any

import pytest

from onyx.db.enums import Permission
from tests.integration.common_utils.test_models import DATestAPIKey
from tests.integration.common_utils.test_models import DATestUser
from tests.integration.tests.permissions._access_matrix import assert_response
from tests.integration.tests.permissions._access_matrix import call_endpoint
from tests.integration.tests.permissions._access_matrix import Endpoint
from tests.integration.tests.permissions._access_matrix import resolve_credentials
from tests.integration.tests.permissions._access_matrix import USER_KINDS

pytestmark = pytest.mark.skipif(
    os.environ.get("ENABLE_PAID_ENTERPRISE_EDITION_FEATURES", "").lower() != "true",
    reason="Custom group permission assignment is enterprise only",
)

PERMISSION = Permission.MANAGE_BOTS.value

ENDPOINTS: list[Endpoint] = [
    ("GET", "/manage/admin/slack-app/channel", None),
    ("GET", "/manage/admin/slack-app/bots", None),
    ("GET", "/manage/admin/discord-bot/guilds", None),
]


@pytest.fixture(scope="module")
def holder_user(permission_holder_user_factory: Any) -> DATestUser:
    return permission_holder_user_factory(PERMISSION)


@pytest.fixture(scope="module")
def holder_service_account(
    permission_holder_service_account_factory: Any,
) -> DATestAPIKey:
    return permission_holder_service_account_factory(PERMISSION)


@pytest.mark.parametrize("user_kind,expected", USER_KINDS)
@pytest.mark.parametrize("method,path,body", ENDPOINTS)
def test_access_matrix(
    user_kind: str,
    expected: str,
    method: str,
    path: str,
    body: dict[str, Any] | None,
    request: pytest.FixtureRequest,
    permission_admin_user: DATestUser,  # noqa: ARG001 -- ensures module_reset ran
) -> None:
    headers, cookies = resolve_credentials(user_kind, request)
    resp = call_endpoint(method, path, body, headers, cookies)
    assert_response(resp, method, path, user_kind, expected)
