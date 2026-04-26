"""Integration tests for ADD_AGENTS permission gate.

ADD_AGENTS gates the "create / edit my own agent" endpoints on the
basic_router (prefix ``/persona``) and agents_router (prefix
``/agents``) in ``backend/onyx/server/features/persona/api.py``.

We target PATCH/DELETE endpoints with bogus persona IDs. The permission
check runs before the DB lookup, so allowed callers receive 404 and
denied callers receive 403.
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

PERMISSION = Permission.ADD_AGENTS.value

ENDPOINTS: list[Endpoint] = [
    ("PATCH", "/persona/999999/public", {"is_public": True}),
    ("PATCH", "/persona/999999/share", {"user_ids": []}),
    ("DELETE", "/persona/999999", None),
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
