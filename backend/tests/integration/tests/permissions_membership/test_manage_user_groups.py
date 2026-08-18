"""Integration tests for MANAGE_USER_GROUPS permission gate (Enterprise).

MANAGE_USER_GROUPS protects the user-group admin endpoints in
``backend/ee/onyx/server/user_group/api.py`` (router prefix ``/manage``).

Note: ``GET /manage/admin/user-group`` is guarded by READ_USER_GROUPS
(implied by MANAGE_USER_GROUPS) so we deliberately exclude it here —
this file only covers endpoints that require the MANAGE token directly.
"""

import os
from typing import Any
from uuid import uuid4

import pytest

from ee.onyx.server.user_group.models import UserGroup as UserGroupSnapshot
from onyx.db.enums import AccessType, Permission
from tests.integration.common_utils.managers.cc_pair import CCPairManager
from tests.integration.common_utils.managers.document_set import DocumentSetManager
from tests.integration.common_utils.managers.persona import PersonaManager
from tests.integration.common_utils.managers.user_group import UserGroupManager
from tests.integration.common_utils.test_models import (
    DATestAPIKey,
    DATestUser,
    DATestUserGroup,
)
from tests.integration.tests.permissions._access_matrix import (
    USER_KINDS,
    Endpoint,
    assert_response,
    call_endpoint,
    resolve_credentials,
)

pytestmark = pytest.mark.skipif(
    os.environ.get("ENABLE_PAID_ENTERPRISE_EDITION_FEATURES", "").lower() != "true",
    reason="User-group permission tests are enterprise only",
)

PERMISSION = Permission.MANAGE_USER_GROUPS.value

_CREATE_GROUP_BODY: dict[str, Any] = {
    "name": "perm-test-user-group",
    "user_ids": [],
    "cc_pair_ids": [],
}

ENDPOINTS: list[Endpoint] = [
    ("GET", "/manage/admin/user-group/999999/permissions", None),
    ("POST", "/manage/admin/user-group", _CREATE_GROUP_BODY),
    ("DELETE", "/manage/admin/user-group/999999", None),
    (
        "PATCH",
        "/manage/admin/user-group/999999/agents",
        {"added_agent_ids": [], "removed_agent_ids": []},
    ),
    (
        "PATCH",
        "/manage/admin/user-group/999999/document-sets",
        {"added_document_set_ids": [], "removed_document_set_ids": []},
    ),
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


# PUT /manage/admin/user-group/{id}/permissions is admin-only (not
# MANAGE_USER_GROUPS) to prevent privilege escalation: a group manager
# could otherwise grant their own group any toggleable permission. Gated
# on FULL_ADMIN_PANEL_ACCESS, so MANAGE_USER_GROUPS holders are denied here.
_SET_PERMISSIONS_USER_KINDS: list[tuple[str, str]] = [
    ("admin", "allowed"),
    ("holder", "denied"),
    ("service_account_holder", "denied"),
    ("basic", "denied"),
    ("service_account", "denied"),
    ("bot", "denied"),
    ("ext_perm", "denied"),
    ("anonymous", "anon_denied"),
]


@pytest.mark.parametrize("user_kind,expected", _SET_PERMISSIONS_USER_KINDS)
def test_set_permissions_requires_full_admin(
    user_kind: str,
    expected: str,
    request: pytest.FixtureRequest,
    permission_admin_user: DATestUser,  # noqa: ARG001 -- ensures module_reset ran
) -> None:
    method = "PUT"
    path = "/manage/admin/user-group/999999/permissions"
    body: dict[str, Any] = {"permissions": []}
    headers, cookies = resolve_credentials(user_kind, request)
    resp = call_endpoint(method, path, body, headers, cookies)
    assert_response(resp, method, path, user_kind, expected)


# ---------------------------------------------------------------------------
# Sharing resources into a group. MANAGE_USER_GROUPS implies only the reads, while the
# resource-side gates ask for MANAGE_AGENTS / MANAGE_DOCUMENT_SETS / MANAGE_CONNECTORS.
# ---------------------------------------------------------------------------


@pytest.fixture
def target_group(permission_admin_user: DATestUser) -> DATestUserGroup:
    """A group ``holder_user`` administers but does not belong to — global authority,
    never membership. Uniquely named because each test mutates it."""
    group = UserGroupManager.create(
        name=f"share-target-{uuid4()}",
        user_performing_action=permission_admin_user,
    )
    # create returns mid-sync, and the membership endpoints refuse a syncing group
    UserGroupManager.wait_for_sync(
        user_performing_action=permission_admin_user,
        user_groups_to_check=[group],
    )
    return group


def _group_snapshot(
    group_id: int, permission_admin_user: DATestUser
) -> UserGroupSnapshot:
    groups = UserGroupManager.get_all(user_performing_action=permission_admin_user)
    return next(group for group in groups if group.id == group_id)


def test_global_holder_shares_agent_it_does_not_own(
    permission_admin_user: DATestUser,
    holder_user: DATestUser,
    target_group: DATestUserGroup,
) -> None:
    # Was refused as if scoped: editable-only lookup plus a MANAGE_AGENTS share gate.
    agent = PersonaManager.create(
        user_performing_action=permission_admin_user, is_public=False
    )
    resp = call_endpoint(
        "PATCH",
        f"/manage/admin/user-group/{target_group.id}/agents",
        {"added_agent_ids": [agent.id], "removed_agent_ids": []},
        holder_user.headers,
        holder_user.cookies,
    )
    assert resp.status_code == 200, resp.text
    snapshot = _group_snapshot(target_group.id, permission_admin_user)
    assert agent.id in {persona.id for persona in snapshot.personas}


def test_global_holder_removes_agent_it_does_not_own(
    permission_admin_user: DATestUser,
    holder_user: DATestUser,
    target_group: DATestUserGroup,
) -> None:
    agent = PersonaManager.create(
        user_performing_action=permission_admin_user,
        is_public=False,
        groups=[target_group.id],
    )
    resp = call_endpoint(
        "PATCH",
        f"/manage/admin/user-group/{target_group.id}/agents",
        {"added_agent_ids": [], "removed_agent_ids": [agent.id]},
        holder_user.headers,
        holder_user.cookies,
    )
    assert resp.status_code == 200, resp.text
    snapshot = _group_snapshot(target_group.id, permission_admin_user)
    assert agent.id not in {persona.id for persona in snapshot.personas}


def test_global_holder_sees_private_connector_in_picker(
    permission_admin_user: DATestUser,
    holder_user: DATestUser,
    target_group: DATestUserGroup,
) -> None:
    # The cc_pair filter bypassed only for MANAGE_CONNECTORS, so private pairs the
    # holder isn't a member of vanished from the picker.
    cc_pair = CCPairManager.create_from_scratch(
        user_performing_action=permission_admin_user,
        access_type=AccessType.PRIVATE,
        groups=[target_group.id],
    )
    resp = call_endpoint(
        "GET",
        "/manage/admin/connector/status",
        None,
        holder_user.headers,
        holder_user.cookies,
    )
    assert resp.status_code == 200, resp.text
    assert cc_pair.id in {row["cc_pair_id"] for row in resp.json()}


def test_global_holder_shares_document_set(
    permission_admin_user: DATestUser,
    holder_user: DATestUser,
    target_group: DATestUserGroup,
) -> None:
    # PUBLIC so check_if_cc_pairs_are_owned_by_groups passes without first attaching
    # the connector to the group.
    cc_pair = CCPairManager.create_from_scratch(
        user_performing_action=permission_admin_user,
        access_type=AccessType.PUBLIC,
        groups=[],
    )
    doc_set = DocumentSetManager.create(
        user_performing_action=permission_admin_user,
        cc_pair_ids=[cc_pair.id],
        is_public=False,
    )
    DocumentSetManager.wait_for_sync(
        document_sets_to_check=[doc_set], user_performing_action=permission_admin_user
    )
    resp = call_endpoint(
        "PATCH",
        f"/manage/admin/user-group/{target_group.id}/document-sets",
        {"added_document_set_ids": [doc_set.id], "removed_document_set_ids": []},
        holder_user.headers,
        holder_user.cookies,
    )
    assert resp.status_code == 200, resp.text
    snapshot = _group_snapshot(target_group.id, permission_admin_user)
    assert doc_set.id in {document_set.id for document_set in snapshot.document_sets}


# ---------------------------------------------------------------------------
# Privilege amplification. The seeded "Admin" group grants FULL_ADMIN_PANEL_ACCESS.
# ---------------------------------------------------------------------------


def _effective_permissions(user: DATestUser) -> list[str]:
    """Indexed, not ``.get`` — a renamed field must fail here, not silently
    hand back an empty list that passes every ``not in`` assertion."""
    resp = call_endpoint("GET", "/me", None, user.headers, user.cookies)
    assert resp.status_code == 200, resp.text
    return resp.json()["effective_permissions"]


def test_holder_cannot_add_self_to_admin_group(
    permission_admin_user: DATestUser,
    holder_user: DATestUser,
) -> None:
    admin_group = UserGroupManager.get_default(
        user_performing_action=permission_admin_user, name="Admin"
    )
    resp = call_endpoint(
        "POST",
        f"/manage/admin/user-group/{admin_group.id}/add-users",
        {"user_ids": [holder_user.id]},
        holder_user.headers,
        holder_user.cookies,
    )
    assert resp.status_code == 403, resp.text

    # 403 alone isn't enough — prove the grant never landed
    assert Permission.FULL_ADMIN_PANEL_ACCESS.value not in _effective_permissions(
        holder_user
    )
    # ...and that this probe can see the grant when it really is there
    assert Permission.FULL_ADMIN_PANEL_ACCESS.value in _effective_permissions(
        permission_admin_user
    )


def test_holder_cannot_add_self_to_admin_group_via_patch(
    permission_admin_user: DATestUser,
    holder_user: DATestUser,
) -> None:
    """add-users delegates to update_user_group, so PATCH is the same door."""
    admin_group = UserGroupManager.get_default(
        user_performing_action=permission_admin_user, name="Admin"
    )
    resp = call_endpoint(
        "PATCH",
        f"/manage/admin/user-group/{admin_group.id}",
        {
            "user_ids": [user.id for user in admin_group.users] + [holder_user.id],
            "cc_pair_ids": [cc_pair.id for cc_pair in admin_group.cc_pairs],
        },
        holder_user.headers,
        holder_user.cookies,
    )
    assert resp.status_code == 403, resp.text


def test_holder_can_still_add_users_to_an_ordinary_group(
    holder_user: DATestUser,
    target_group: DATestUserGroup,
) -> None:
    resp = call_endpoint(
        "POST",
        f"/manage/admin/user-group/{target_group.id}/add-users",
        {"user_ids": [holder_user.id]},
        holder_user.headers,
        holder_user.cookies,
    )
    assert resp.status_code == 200, resp.text
    assert holder_user.id in {user["id"] for user in resp.json()["users"]}
