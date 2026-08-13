"""Escalation suite for two-gate scoping on connectors + document sets.

A scoped group manager may only create/edit non-PUBLIC resources (PRIVATE or SYNC
connectors; PRIVATE document sets) whose every group is one they manage; they can
never widen to PUBLIC, capture another group's resource by reassignment, or act
outside their managed scope. DELETE is admin-only except for a resource in no group
that they created — shared with nobody, so its creator isn't stranded. Global holders
(admins) bypass GATE 2. Managers are seeded by flipping ``User__UserGroup.is_manager``
directly (no manager-creation helper exists yet).

Allowed actions go through the shared Manager classes (which assert real success);
denied actions go through the shared ``_access_matrix`` helpers, which verify the
403 is a genuine permission-gate denial rather than any incidental 403.
"""

import os
from typing import Any, NamedTuple
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
from tests.integration.common_utils.test_models import (
    DATestDocumentSet,
    DATestUser,
    DATestUserGroup,
)
from tests.integration.tests.permissions._access_matrix import (
    assert_response,
    call_endpoint,
)

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
    # a freshly created group is still syncing, and every edit route 404s until it
    # settles — start each test from a settled state rather than racing it
    UserGroupManager.wait_for_sync(
        user_performing_action=admin_user,
        user_groups_to_check=[managed_group, other_group],
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


def _detach_cc_pair_from_group(group: DATestUserGroup, admin: DATestUser) -> None:
    """Drop every cc_pair off a group and wait out the sync.

    The only route to a manager-owned groupless connector: creating one directly is
    refused (no managed scope in zero groups), so it has to start in a group and lose
    it. Attaching the connector already left the group syncing, and an edit is refused
    (404) while is_up_to_date is False — so both waits are load-bearing.
    """
    UserGroupManager.wait_for_sync(
        user_performing_action=admin, user_groups_to_check=[group]
    )
    group.cc_pair_ids = []
    UserGroupManager.edit(group, user_performing_action=admin)
    UserGroupManager.wait_for_sync(
        user_performing_action=admin, user_groups_to_check=[group]
    )


def _create_synced_doc_set(
    env: _ScopedEnv, *, groups: list[int], cc_pair_ids: list[int]
) -> DATestDocumentSet:
    """Create a document set and wait until it is done syncing.

    update_document_set refuses to touch a set whose is_up_to_date is False, and the
    create response reports True before the sync has run.
    """
    doc_set = DocumentSetManager.create(
        user_performing_action=env.manager,
        is_public=False,
        groups=groups,
        cc_pair_ids=cc_pair_ids,
    )
    DocumentSetManager.wait_for_sync(
        user_performing_action=env.manager, document_sets_to_check=[doc_set]
    )
    return doc_set


def _patch_doc_set_ok(
    env: _ScopedEnv, body: dict[str, Any], doc_set: DATestDocumentSet
) -> None:
    """PATCH expecting success, then wait out the sync it starts — see above."""
    resp = call_endpoint(
        "PATCH", _DOC_SET_PATH, body, env.manager.headers, env.manager.cookies
    )
    assert resp.status_code == 200, resp.text
    DocumentSetManager.wait_for_sync(
        user_performing_action=env.manager, document_sets_to_check=[doc_set]
    )


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
    doc_set = _create_synced_doc_set(
        env, groups=[env.managed_group.id], cc_pair_ids=[cc_pair.id]
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
    doc_set = _create_synced_doc_set(
        env, groups=[env.managed_group.id], cc_pair_ids=[cc_pair.id]
    )
    DocumentSetManager.edit(doc_set, user_performing_action=env.manager)


def test_manager_edits_own_groupless_doc_set(env: _ScopedEnv) -> None:
    """Detaching the last group must leave it editable in place — delete is admin-only,
    so otherwise the creator can see it and do nothing with it."""
    cc_pair = CCPairManager.create_from_scratch(
        user_performing_action=env.manager,
        access_type=AccessType.PRIVATE,
        groups=[env.managed_group.id],
    )
    doc_set = _create_synced_doc_set(
        env, groups=[env.managed_group.id], cc_pair_ids=[cc_pair.id]
    )
    body = _doc_set_body(
        is_public=False, groups=[], cc_pair_ids=[cc_pair.id], doc_set_id=doc_set.id
    )
    # first call detaches (scope gate, current groups still managed); second edits it
    # in place with no groups left, which only the creator path admits
    _patch_doc_set_ok(env, body, doc_set)

    body["name"] = f"ds-renamed-{uuid4()}"
    in_place = call_endpoint(
        "PATCH", _DOC_SET_PATH, body, env.manager.headers, env.manager.cookies
    )
    assert in_place.status_code == 200, in_place.text


def test_manager_cannot_publish_own_groupless_doc_set(env: _ScopedEnv) -> None:
    """In-place editing is not a route to publishing."""
    cc_pair = CCPairManager.create_from_scratch(
        user_performing_action=env.manager,
        access_type=AccessType.PRIVATE,
        groups=[env.managed_group.id],
    )
    doc_set = _create_synced_doc_set(
        env, groups=[env.managed_group.id], cc_pair_ids=[cc_pair.id]
    )
    detach = _doc_set_body(
        is_public=False, groups=[], cc_pair_ids=[cc_pair.id], doc_set_id=doc_set.id
    )
    _patch_doc_set_ok(env, detach, doc_set)

    publish = _doc_set_body(
        is_public=True, groups=[], cc_pair_ids=[cc_pair.id], doc_set_id=doc_set.id
    )
    resp = call_endpoint(
        "PATCH", _DOC_SET_PATH, publish, env.manager.headers, env.manager.cookies
    )
    assert_response(resp, "PATCH", _DOC_SET_PATH, "manager", "denied")


def test_manager_cannot_attach_unmanaged_group_to_groupless_doc_set(
    env: _ScopedEnv,
) -> None:
    """Nor to capture: any group added still goes through the gate."""
    cc_pair = CCPairManager.create_from_scratch(
        user_performing_action=env.manager,
        access_type=AccessType.PRIVATE,
        groups=[env.managed_group.id],
    )
    doc_set = _create_synced_doc_set(
        env, groups=[env.managed_group.id], cc_pair_ids=[cc_pair.id]
    )
    detach = _doc_set_body(
        is_public=False, groups=[], cc_pair_ids=[cc_pair.id], doc_set_id=doc_set.id
    )
    _patch_doc_set_ok(env, detach, doc_set)

    capture = _doc_set_body(
        is_public=False,
        groups=[env.other_group.id],
        cc_pair_ids=[cc_pair.id],
        doc_set_id=doc_set.id,
    )
    resp = call_endpoint(
        "PATCH", _DOC_SET_PATH, capture, env.manager.headers, env.manager.cookies
    )
    assert_response(resp, "PATCH", _DOC_SET_PATH, "manager", "denied")


def test_manager_deletes_own_groupless_doc_set(env: _ScopedEnv) -> None:
    """Groupless and creator-owned is shared with nobody, so delete is allowed."""
    cc_pair = CCPairManager.create_from_scratch(
        user_performing_action=env.manager,
        access_type=AccessType.PRIVATE,
        groups=[env.managed_group.id],
    )
    doc_set = _create_synced_doc_set(
        env, groups=[env.managed_group.id], cc_pair_ids=[cc_pair.id]
    )
    detach = _doc_set_body(
        is_public=False, groups=[], cc_pair_ids=[cc_pair.id], doc_set_id=doc_set.id
    )
    _patch_doc_set_ok(env, detach, doc_set)

    resp = call_endpoint(
        "DELETE",
        f"{_DOC_SET_PATH}/{doc_set.id}",
        None,
        env.manager.headers,
        env.manager.cookies,
    )
    assert resp.status_code == 200, resp.text


def test_manager_cannot_delete_doc_set(env: _ScopedEnv) -> None:
    cc_pair = CCPairManager.create_from_scratch(
        user_performing_action=env.manager,
        access_type=AccessType.PRIVATE,
        groups=[env.managed_group.id],
    )
    doc_set = _create_synced_doc_set(
        env, groups=[env.managed_group.id], cc_pair_ids=[cc_pair.id]
    )
    # Owns it, but it is still shared into a group — delete stays admin-only.
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


def test_manager_reads_detail_of_managed_cc_pair(env: _ScopedEnv) -> None:
    """Write routes admitted scope but these reads did not, so a manager could create
    a connector then 403 opening it. Each read row-filters by caller."""
    cc_pair = CCPairManager.create_from_scratch(
        user_performing_action=env.manager,
        access_type=AccessType.PRIVATE,
        groups=[env.managed_group.id],
    )
    for path in [
        f"/manage/admin/cc-pair/{cc_pair.id}",
        f"/manage/admin/cc-pair/{cc_pair.id}/index-attempts?page=0&page_size=10",
        f"/manage/admin/cc-pair/{cc_pair.id}/last_pruned",
    ]:
        resp = call_endpoint(
            "GET", path, None, env.manager.headers, env.manager.cookies
        )
        assert_response(resp, "GET", path, "manager", "allowed")


def test_manager_cannot_read_detail_of_unmanaged_cc_pair(env: _ScopedEnv) -> None:
    """allow_scope must not widen the row filter."""
    admin_cc_pair = CCPairManager.create_from_scratch(
        user_performing_action=env.admin,
        access_type=AccessType.PRIVATE,
        groups=[env.other_group.id],
    )
    path = f"/manage/admin/cc-pair/{admin_cc_pair.id}"
    resp = call_endpoint("GET", path, None, env.manager.headers, env.manager.cookies)
    assert resp.status_code in (403, 404), resp.text


def test_manager_reads_credentials_for_connector_form(env: _ScopedEnv) -> None:
    """The setup page renders an empty fragment when either fetch fails — a blank
    page with a sidebar, not an error."""
    for path in [
        "/manage/admin/credential",
        "/manage/admin/similar-credentials/file",
    ]:
        resp = call_endpoint(
            "GET", path, None, env.manager.headers, env.manager.cookies
        )
        assert_response(resp, "GET", path, "manager", "allowed")


def test_plain_member_cannot_read_credentials(env: _ScopedEnv) -> None:
    """allow_scope admits managers, not everyone in the group."""
    member = UserManager.create(name="cred_plain_member")
    UserGroupManager.add_users(
        env.managed_group, [member.id], user_performing_action=env.admin
    )
    path = "/manage/admin/credential"
    resp = call_endpoint("GET", path, None, member.headers, member.cookies)
    assert_response(resp, "GET", path, "member", "denied")


def test_manager_pauses_own_managed_cc_pair(env: _ScopedEnv) -> None:
    # Pause/status (mutate routes) authorize via the re-keyed read/editable filter,
    # not a separate scope check — so managed-scope access gates mutation too.
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


def test_admin_cc_pair_detail_carries_permissions_map(env: _ScopedEnv) -> None:
    cc_pair = CCPairManager.create_from_scratch(
        user_performing_action=env.admin,
        access_type=AccessType.PRIVATE,
        groups=[env.managed_group.id],
    )
    path = f"/manage/admin/cc-pair/{cc_pair.id}"
    resp = call_endpoint("GET", path, None, env.admin.headers, env.admin.cookies)
    assert resp.status_code == 200

    body = resp.json()
    # admin holds global MANAGE_CONNECTORS, so every action is allowed
    assert body["permissions"] == {"edit": True, "delete": True, "publish": True}
    # edit is stamped from is_editable_for_current_user, so the two must agree
    assert body["permissions"]["edit"] == body["is_editable_for_current_user"]


def test_manager_reads_detail_of_own_groupless_cc_pair(env: _ScopedEnv) -> None:
    """Every fetch the detail page makes, on a connector that lost its last group.

    The page gates its whole render on the cc-pair AND the index-attempts fetch, and
    usePaginatedFetch never clears isLoading on error — so a single 404 here is an
    infinite spinner, not a visible failure.
    """
    cc_pair = CCPairManager.create_from_scratch(
        user_performing_action=env.manager,
        access_type=AccessType.PRIVATE,
        groups=[env.managed_group.id],
    )
    _detach_cc_pair_from_group(env.managed_group, env.admin)

    for path in [
        f"/manage/admin/cc-pair/{cc_pair.id}",
        f"/manage/admin/cc-pair/{cc_pair.id}/index-attempts?page_num=0&page_size=10",
        f"/manage/admin/cc-pair/{cc_pair.id}/last_pruned",
        f"/manage/admin/cc-pair/{cc_pair.id}/permission-sync-attempts",
    ]:
        resp = call_endpoint(
            "GET", path, None, env.manager.headers, env.manager.cookies
        )
        assert_response(resp, "GET", path, "manager", "allowed")


def test_manager_cannot_read_groupless_cc_pair_of_another_creator(
    env: _ScopedEnv,
) -> None:
    """The fallback is creator-only — otherwise detaching a group would expose a
    connector to every manager instead of hiding it from all but one."""
    admin_cc_pair = CCPairManager.create_from_scratch(
        user_performing_action=env.admin,
        access_type=AccessType.PRIVATE,
        groups=[env.other_group.id],
    )
    _detach_cc_pair_from_group(env.other_group, env.admin)

    path = f"/manage/admin/cc-pair/{admin_cc_pair.id}"
    resp = call_endpoint("GET", path, None, env.manager.headers, env.manager.cookies)
    assert resp.status_code in (403, 404), resp.text


def test_manager_cc_pair_detail_stamps_delete_once_groupless(
    env: _ScopedEnv,
) -> None:
    """The Delete control renders off permissions.delete, so the map must track the
    same carve-out the deletion route enforces — not stay admin-only behind it."""
    cc_pair = CCPairManager.create_from_scratch(
        user_performing_action=env.manager,
        access_type=AccessType.PRIVATE,
        groups=[env.managed_group.id],
    )
    path = f"/manage/admin/cc-pair/{cc_pair.id}"

    shared = call_endpoint(
        "GET", path, None, env.manager.headers, env.manager.cookies
    ).json()
    assert shared["permissions"]["edit"] is True
    assert shared["permissions"]["delete"] is False, "shared connector is admin-only"

    _detach_cc_pair_from_group(env.managed_group, env.admin)

    groupless = call_endpoint(
        "GET", path, None, env.manager.headers, env.manager.cookies
    ).json()
    assert groupless["permissions"]["delete"] is True
    assert groupless["permissions"]["publish"] is False, "publish stays global-only"


def test_manager_deletes_own_groupless_cc_pair(env: _ScopedEnv) -> None:
    """Mirrors the document-set carve-out: shared with nobody, so its creator may
    delete it rather than needing an admin to unstrand it."""
    cc_pair = CCPairManager.create_from_scratch(
        user_performing_action=env.manager,
        access_type=AccessType.PRIVATE,
        groups=[env.managed_group.id],
    )
    _detach_cc_pair_from_group(env.managed_group, env.admin)

    resp = call_endpoint(
        "POST",
        "/manage/admin/deletion-attempt",
        {"connector_id": cc_pair.connector_id, "credential_id": cc_pair.credential_id},
        env.manager.headers,
        env.manager.cookies,
    )
    assert resp.status_code == 200, resp.text


def test_manager_doc_set_listing_stamps_groupless_as_editable(
    env: _ScopedEnv,
) -> None:
    """The Edit button reads permissions.edit off this listing, not the write gate.
    Recomputing editability here instead of taking it from the editable query is what
    previously left a creator able to PATCH a set the list showed as read-only."""
    cc_pair = CCPairManager.create_from_scratch(
        user_performing_action=env.manager,
        access_type=AccessType.PRIVATE,
        groups=[env.managed_group.id],
    )
    doc_set = _create_synced_doc_set(
        env, groups=[env.managed_group.id], cc_pair_ids=[cc_pair.id]
    )
    detach = _doc_set_body(
        is_public=False, groups=[], cc_pair_ids=[cc_pair.id], doc_set_id=doc_set.id
    )
    _patch_doc_set_ok(env, detach, doc_set)

    listing = call_endpoint(
        "GET", "/manage/document-set", None, env.manager.headers, env.manager.cookies
    )
    assert listing.status_code == 200, listing.text
    listed = {entry["id"]: entry for entry in listing.json()}
    assert doc_set.id in listed, "creator lost their groupless set from the listing"
    assert listed[doc_set.id]["permissions"]["edit"] is True
    assert listed[doc_set.id]["permissions"]["delete"] is True
    assert listed[doc_set.id]["permissions"]["publish"] is False
