"""Integration tests for MANAGE_DOCUMENT_SETS permission gate.

Document-set admin endpoints live in
``backend/onyx/server/features/document_set/api.py`` (router prefix
``/manage``). Only mutating endpoints exist; the access matrix therefore
sends valid-shape bodies and tolerates 404 on a bogus DELETE path.
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

PERMISSION = Permission.MANAGE_DOCUMENT_SETS.value

_VALID_CREATE_BODY: dict[str, Any] = {
    "name": "perm-test-doc-set",
    "description": "created by test_manage_document_sets",
    "cc_pair_ids": [],
    "is_public": True,
    "users": [],
    "groups": [],
    "federated_connectors": [],
}

_VALID_UPDATE_BODY: dict[str, Any] = {
    "id": 999999,
    "description": "irrelevant",
    "cc_pair_ids": [],
    "is_public": True,
    "users": [],
    "groups": [],
    "federated_connectors": [],
}

ENDPOINTS: list[Endpoint] = [
    ("POST", "/manage/admin/document-set", _VALID_CREATE_BODY),
    ("PATCH", "/manage/admin/document-set", _VALID_UPDATE_BODY),
    ("DELETE", "/manage/admin/document-set/999999", None),
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
