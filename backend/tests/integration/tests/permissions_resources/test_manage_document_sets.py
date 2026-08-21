"""Integration tests for MANAGE_DOCUMENT_SETS permission gate.

Document-set admin endpoints live in
``backend/onyx/server/features/document_set/api.py`` (router prefix
``/manage``). Only mutating endpoints exist; the access matrix therefore
sends valid-shape bodies and tolerates 404 on a bogus DELETE path.
"""

import os
from typing import Any, NamedTuple
from uuid import uuid4

import pytest

from onyx.db.enums import AccessType, Permission
from tests.integration.common_utils.managers.cc_pair import CCPairManager
from tests.integration.common_utils.managers.document_set import DocumentSetManager
from tests.integration.common_utils.test_models import (
    DATestAPIKey,
    DATestUser,
    DATestUserGroup,
)
from tests.integration.tests.permissions._access_matrix import (
    SCOPE_USER_KINDS,
    USER_KINDS,
    Endpoint,
    ScopeEndpoint,
    assert_response,
    assert_scope_case,
    call_endpoint,
    resolve_credentials,
)

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


# Scope matrix — MANAGE_DOCUMENT_SETS is in SCOPED_MANAGER_PERMISSIONS.


class _ScopedDocSet(NamedTuple):
    """Update re-sends groups and cc_pairs, so the id alone isn't enough."""

    id: int
    group_id: int
    cc_pair_id: int


def _update_body(doc_set: _ScopedDocSet) -> dict[str, Any]:
    """No-op update: re-sends current state, so only the gate verdict can fail it
    and repeated runs stay order-independent."""
    return {
        "id": doc_set.id,
        "name": f"scope-doc-set-{doc_set.id}",
        "description": "scope matrix",
        "cc_pair_ids": [doc_set.cc_pair_id],
        "is_public": False,
        "users": [],
        "groups": [doc_set.group_id],
        "federated_connectors": [],
    }


@pytest.fixture(scope="module")
def scoped_document_sets(
    permission_admin_user: DATestUser,
    scoped_managed_group: DATestUserGroup,
    scoped_other_group: DATestUserGroup,
) -> tuple[_ScopedDocSet, _ScopedDocSet]:
    """Created by the admin so the manager's create path isn't a precondition for
    testing their edit path. A private set is rejected without a connector owned by
    its own groups."""

    def _pair_for(group: DATestUserGroup) -> int:
        return CCPairManager.create_from_scratch(
            user_performing_action=permission_admin_user,
            access_type=AccessType.PRIVATE,
            groups=[group.id],
        ).id

    managed_pair = _pair_for(scoped_managed_group)
    other_pair = _pair_for(scoped_other_group)
    in_scope = DocumentSetManager.create(
        user_performing_action=permission_admin_user,
        is_public=False,
        cc_pair_ids=[managed_pair],
        groups=[scoped_managed_group.id],
    )
    out_of_scope = DocumentSetManager.create(
        user_performing_action=permission_admin_user,
        is_public=False,
        cc_pair_ids=[other_pair],
        groups=[scoped_other_group.id],
    )
    return (
        _ScopedDocSet(in_scope.id, scoped_managed_group.id, managed_pair),
        _ScopedDocSet(out_of_scope.id, scoped_other_group.id, other_pair),
    )


def _create_body(doc_set: _ScopedDocSet) -> dict[str, Any]:
    """Create is scoped by the groups the request asks for; the resource only
    supplies the target group."""
    return {
        "name": f"scope-create-{uuid4()}",
        "description": "scope matrix",
        "cc_pair_ids": [doc_set.cc_pair_id],
        "is_public": False,
        "users": [],
        "groups": [doc_set.group_id],
        "federated_connectors": [],
    }


_CREATE_ENDPOINT = ScopeEndpoint(
    method="POST",
    path=lambda _doc_set: "/manage/admin/document-set",
    body=_create_body,
    label="create-document-set",
)

_PATCH_ENDPOINT = ScopeEndpoint(
    method="PATCH",
    path=lambda _doc_set: "/manage/admin/document-set",
    body=_update_body,
    label="patch-document-set",
)

_DELETE_ENDPOINT = ScopeEndpoint(
    method="DELETE",
    path=lambda doc_set: f"/manage/admin/document-set/{doc_set.id}",
    label="delete-document-set",
)


@pytest.mark.parametrize(
    "endpoint", [_CREATE_ENDPOINT, _PATCH_ENDPOINT], ids=lambda e: e.label
)
@pytest.mark.parametrize("user_kind,in_scope,out_of_scope", SCOPE_USER_KINDS)
def test_scope_matrix(
    endpoint: ScopeEndpoint,
    user_kind: str,
    in_scope: str,
    out_of_scope: str,
    scoped_document_sets: tuple[_ScopedDocSet, _ScopedDocSet],
    request: pytest.FixtureRequest,
) -> None:
    in_scope_set, out_of_scope_set = scoped_document_sets
    assert_scope_case(endpoint, in_scope_set, user_kind, in_scope, request)
    assert_scope_case(endpoint, out_of_scope_set, user_kind, out_of_scope, request)


@pytest.mark.parametrize(
    "user_kind,expected",
    [("manager", "denied_admin_only"), ("plain_member", "denied_gate1")],
)
def test_delete_is_out_of_manager_scope(
    user_kind: str,
    expected: str,
    scoped_document_sets: tuple[_ScopedDocSet, _ScopedDocSet],
    request: pytest.FixtureRequest,
) -> None:
    """DELETE does allow scope, so a manager clears GATE 1 and is stopped by the
    handler's admin-only check either way — that is what keeps delete admin-only for
    a set they can otherwise edit. Pinning the layer catches a lost allow_scope, which
    would deny them at GATE 1 instead. The admin side is covered above; repeating it
    here would delete the fixture."""
    for doc_set in scoped_document_sets:
        assert_scope_case(_DELETE_ENDPOINT, doc_set, user_kind, expected, request)
