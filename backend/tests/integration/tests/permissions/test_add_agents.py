"""Integration tests for the ADD_AGENTS permission gate.

ADD_AGENTS gates creating and deleting your own agent (``/persona``). Bogus ids
are fine: the gate runs before the DB lookup.

``PATCH /persona/{id}/public`` and ``/share`` are deliberately absent — both are
BASIC_ACCESS + GATE 2, so they live in test_basic_access.py.
"""

import os
from typing import Any

import pytest

from onyx.db.enums import Permission
from tests.integration.common_utils.test_models import DATestAPIKey, DATestUser
from tests.integration.tests.permissions._access_matrix import (
    USER_KINDS,
    Endpoint,
    assert_response,
    call_endpoint,
    resolve_credentials,
)

pytestmark = pytest.mark.skipif(
    os.environ.get("ENABLE_PAID_ENTERPRISE_EDITION_FEATURES", "").lower() != "true",
    reason="Custom group permission assignment is enterprise only",
)

PERMISSION = Permission.ADD_AGENTS.value

# Private with no groups — the personal-agent shape an ADD_AGENTS-only holder may
# create. Public or grouped would drag in publish / scope gates.
_CREATE_AGENT_BODY: dict[str, Any] = {
    "name": "perm-test-agent",
    "description": "perm-test agent",
    "system_prompt": "",
    "task_prompt": "",
    "datetime_aware": False,
    "is_public": False,
    "document_set_ids": [],
    "tool_ids": [],
    "users": [],
    "groups": [],
    "label_ids": [],
    "user_file_ids": [],
}

ENDPOINTS: list[Endpoint] = [
    ("POST", "/persona", _CREATE_AGENT_BODY),
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
