"""Escalation suite for two-gate scoping on connectors + document sets.

A scoped group manager may only create/edit non-PUBLIC resources (PRIVATE or SYNC
connectors; PRIVATE document sets) whose every group is one they manage; they can
never widen to PUBLIC, capture another group's resource by reassignment, act
outside their managed scope, or DELETE (admin-only). Global holders (admins)
bypass GATE 2. Managers are seeded by flipping ``User__UserGroup.is_manager``
directly (no manager-creation helper exists yet).

Allowed actions go through the shared Manager classes (which assert real success);
denied actions go through the shared ``_access_matrix`` helpers, which verify the
403 is a genuine permission-gate denial rather than any incidental 403.
"""

import os
from typing import Any
from typing import NamedTuple
from uuid import uuid4

import pytest
from sqlalchemy import update

from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import AccessType
from onyx.db.models import User__UserGroup
from onyx.db.permissions import recompute_user_permissions__no_commit
from tests.integration.common_utils.managers.cc_pair import CCPairManager
from tests.integration.common_utils.managers.connector import ConnectorManager
from tests.integration.common_utils.managers.credential import CredentialManager
from tests.integration.common_utils.managers.document_set import DocumentSetManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.managers.user_group import UserGroupManager
from tests.integration.common_utils.test_models import DATestUser
from tests.integration.common_utils.test_models import DATestUserGroup
from tests.integration.tests.permissions._access_matrix import assert_response
from tests.integration.tests.permissions._access_matrix import call_endpoint

pytestmark = pytest.mark.skipif(
    os.environ.get("ENABLE_PAID_ENTERPRISE_EDITION_FEATURES", "").lower() != "true",
    reason="Group manager scoping is an enterprise-only capability",
)

_DOC_SET_PATH = "/manage/admin/document-set"


class _ScopedEnv(NamedTuple):
    admin: DATestUser
    manager: DATestUser
    managed_group: DATestUserGroup
    other_group: DATestUserGroup


def _promote_to_manager(user_id: str, group_id: int) -> None:
    """Flip is_manager on the (user, group) edge and recompute the cached flag."""
    with get_session_with_current_tenant() as db_session:
        db_session.execute(
            update(User__UserGroup)
            .where(
                User__UserGroup.user_id == user_id,
                User__UserGroup.user_group_id == group_id,
            )
            .values(is_manager=True)
        )
        db_session.flush()
        recompute_user_permissions__no_commit(user_id, db_session)
        db_session.commit()


@pytest.fixture
def env(reset: None, admin_user: DATestUser) -> _ScopedEnv:  # noqa: ARG001
    manager = UserManager.create(name="scoped_manager")
    managed_group = UserGroupManager.create(
        name="managed", user_ids=[manager.id], user_performing_action=admin_user
    )
    other_group = UserGroupManager.create(
        name="unmanaged", user_performing_action=admin_user
    )
    _promote_to_manager(manager.id, managed_group.id)
    return _ScopedEnv(admin_user, manager, managed_group, other_group)


def _build_connector_and_credential(user: DATestUser) -> tuple[int, int]:
    connector = ConnectorManager.create(user_performing_action=user)
    credential = CredentialManager.create(
        user_performing_action=user, curator_public=False
    )
    return connector.id, credential.id


def _associate_body(access_type: AccessType, groups: list[int]) -> dict[str, Any]:
    return {
        "name": f"cc-{uuid4()}",
        "access_type": access_type.value,
        "groups": groups,
    }


def _doc_set_body(
    *,
    is_public: bool,
    groups: list[int],
    cc_pair_ids: list[int],
    doc_set_id: int | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "name": f"ds-{uuid4()}",
        "description": "escalation test",
        "cc_pair_ids": cc_pair_ids,
        "is_public": is_public,
        "users": [],
        "groups": groups,
        "federated_connectors": [],
    }
    if doc_set_id is not None:
        body["id"] = doc_set_id
    return body


# --- cc_pair create (GATE 2) ------------------------------------------------


def test_admin_creates_public_cc_pair_bypasses_gate(env: _ScopedEnv) -> None:
    # Control: a global holder is not scope-restricted (PUBLIC, no groups).
    CCPairManager.create_from_scratch(
        user_performing_action=env.admin, access_type=AccessType.PUBLIC, groups=[]
    )


def test_manager_creates_private_cc_pair_in_managed_group(env: _ScopedEnv) -> None:
    CCPairManager.create_from_scratch(
        user_performing_action=env.manager,
        access_type=AccessType.PRIVATE,
        groups=[env.managed_group.id],
    )


def test_manager_cannot_create_cc_pair_in_unmanaged_group(env: _ScopedEnv) -> None:
    connector_id, credential_id = _build_connector_and_credential(env.manager)
    path = f"/manage/connector/{connector_id}/credential/{credential_id}"
    resp = call_endpoint(
        "PUT",
        path,
        _associate_body(AccessType.PRIVATE, [env.other_group.id]),
        env.manager.headers,
        env.manager.cookies,
    )
    assert_response(resp, "PUT", path, "manager", "denied")


def test_manager_cannot_create_public_cc_pair(env: _ScopedEnv) -> None:
    connector_id, credential_id = _build_connector_and_credential(env.manager)
    path = f"/manage/connector/{connector_id}/credential/{credential_id}"
    resp = call_endpoint(
        "PUT",
        path,
        _associate_body(AccessType.PUBLIC, [env.managed_group.id]),
        env.manager.headers,
        env.manager.cookies,
    )
    assert_response(resp, "PUT", path, "manager", "denied")


def test_manager_cannot_create_cc_pair_without_groups(env: _ScopedEnv) -> None:
    # Fail-closed: a PRIVATE cc_pair in zero groups has no managed scope.
    connector_id, credential_id = _build_connector_and_credential(env.manager)
    path = f"/manage/connector/{connector_id}/credential/{credential_id}"
    resp = call_endpoint(
        "PUT",
        path,
        _associate_body(AccessType.PRIVATE, []),
        env.manager.headers,
        env.manager.cookies,
    )
    assert_response(resp, "PUT", path, "manager", "denied")


# --- document set create / edit (GATE 2) ------------------------------------


def test_manager_creates_private_doc_set_in_managed_group(env: _ScopedEnv) -> None:
    cc_pair = CCPairManager.create_from_scratch(
        user_performing_action=env.manager,
        access_type=AccessType.PRIVATE,
        groups=[env.managed_group.id],
    )
    DocumentSetManager.create(
        user_performing_action=env.manager,
        is_public=False,
        groups=[env.managed_group.id],
        cc_pair_ids=[cc_pair.id],
    )


def test_manager_cannot_create_public_doc_set(env: _ScopedEnv) -> None:
    cc_pair = CCPairManager.create_from_scratch(
        user_performing_action=env.manager,
        access_type=AccessType.PRIVATE,
        groups=[env.managed_group.id],
    )
    resp = call_endpoint(
        "POST",
        _DOC_SET_PATH,
        _doc_set_body(
            is_public=True, groups=[env.managed_group.id], cc_pair_ids=[cc_pair.id]
        ),
        env.manager.headers,
        env.manager.cookies,
    )
    assert_response(resp, "POST", _DOC_SET_PATH, "manager", "denied")


def test_manager_cannot_create_doc_set_in_unmanaged_group(env: _ScopedEnv) -> None:
    cc_pair = CCPairManager.create_from_scratch(
        user_performing_action=env.manager,
        access_type=AccessType.PRIVATE,
        groups=[env.managed_group.id],
    )
    resp = call_endpoint(
        "POST",
        _DOC_SET_PATH,
        _doc_set_body(
            is_public=False, groups=[env.other_group.id], cc_pair_ids=[cc_pair.id]
        ),
        env.manager.headers,
        env.manager.cookies,
    )
    assert_response(resp, "POST", _DOC_SET_PATH, "manager", "denied")


def test_manager_cannot_capture_doc_set_by_reassign(env: _ScopedEnv) -> None:
    cc_pair = CCPairManager.create_from_scratch(
        user_performing_action=env.manager,
        access_type=AccessType.PRIVATE,
        groups=[env.managed_group.id],
    )
    doc_set = DocumentSetManager.create(
        user_performing_action=env.manager,
        is_public=False,
        groups=[env.managed_group.id],
        cc_pair_ids=[cc_pair.id],
    )
    # current ∪ requested must be ⊆ managed — adding an unmanaged group is rejected.
    resp = call_endpoint(
        "PATCH",
        _DOC_SET_PATH,
        _doc_set_body(
            is_public=False,
            groups=[env.managed_group.id, env.other_group.id],
            cc_pair_ids=[cc_pair.id],
            doc_set_id=doc_set.id,
        ),
        env.manager.headers,
        env.manager.cookies,
    )
    assert_response(resp, "PATCH", _DOC_SET_PATH, "manager", "denied")


def test_manager_edits_doc_set_within_managed_group(env: _ScopedEnv) -> None:
    cc_pair = CCPairManager.create_from_scratch(
        user_performing_action=env.manager,
        access_type=AccessType.PRIVATE,
        groups=[env.managed_group.id],
    )
    doc_set = DocumentSetManager.create(
        user_performing_action=env.manager,
        is_public=False,
        groups=[env.managed_group.id],
        cc_pair_ids=[cc_pair.id],
    )
    DocumentSetManager.edit(doc_set, user_performing_action=env.manager)


# --- DELETE stays admin-only ------------------------------------------------


def test_manager_cannot_delete_doc_set(env: _ScopedEnv) -> None:
    cc_pair = CCPairManager.create_from_scratch(
        user_performing_action=env.manager,
        access_type=AccessType.PRIVATE,
        groups=[env.managed_group.id],
    )
    doc_set = DocumentSetManager.create(
        user_performing_action=env.manager,
        is_public=False,
        groups=[env.managed_group.id],
        cc_pair_ids=[cc_pair.id],
    )
    # Owns it, in a managed group — still denied: delete is admin-only.
    path = f"{_DOC_SET_PATH}/{doc_set.id}"
    resp = call_endpoint("DELETE", path, None, env.manager.headers, env.manager.cookies)
    assert_response(resp, "DELETE", path, "manager", "denied")


def test_manager_cannot_delete_cc_pair(env: _ScopedEnv) -> None:
    cc_pair = CCPairManager.create_from_scratch(
        user_performing_action=env.manager,
        access_type=AccessType.PRIVATE,
        groups=[env.managed_group.id],
    )
    path = "/manage/admin/deletion-attempt"
    resp = call_endpoint(
        "POST",
        path,
        {"connector_id": cc_pair.connector_id, "credential_id": cc_pair.credential_id},
        env.manager.headers,
        env.manager.cookies,
    )
    assert_response(resp, "POST", path, "manager", "denied")


# --- re-keyed read filter authorizes the mutate routes ----------------------


def test_manager_pauses_own_managed_cc_pair(env: _ScopedEnv) -> None:
    cc_pair = CCPairManager.create_from_scratch(
        user_performing_action=env.manager,
        access_type=AccessType.PRIVATE,
        groups=[env.managed_group.id],
    )
    CCPairManager.pause_cc_pair(cc_pair, user_performing_action=env.manager)


def test_manager_cannot_pause_unmanaged_cc_pair(env: _ScopedEnv) -> None:
    # Admin owns a PRIVATE cc_pair in a group the manager does not manage.
    admin_cc_pair = CCPairManager.create_from_scratch(
        user_performing_action=env.admin,
        access_type=AccessType.PRIVATE,
        groups=[env.other_group.id],
    )
    path = f"/manage/admin/cc-pair/{admin_cc_pair.id}/status"
    resp = call_endpoint(
        "PUT",
        path,
        {"status": "PAUSED"},
        env.manager.headers,
        env.manager.cookies,
    )
    assert_response(resp, "PUT", path, "manager", "denied")


# --- membership is not managership ------------------------------------------


def test_plain_member_cannot_create_doc_set(env: _ScopedEnv) -> None:
    # A group member without is_manager has NONE authority — rejected at GATE 1.
    member = UserManager.create(name="plain_member")
    UserGroupManager.add_users(
        env.managed_group, [member.id], user_performing_action=env.admin
    )
    resp = call_endpoint(
        "POST",
        _DOC_SET_PATH,
        _doc_set_body(is_public=False, groups=[env.managed_group.id], cc_pair_ids=[]),
        member.headers,
        member.cookies,
    )
    assert_response(resp, "POST", _DOC_SET_PATH, "member", "denied")
