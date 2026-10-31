"""Audit coverage for the group write paths that are more than call-a-function-
then-emit.

Plain emit-on-success wiring is covered once by the API-key representatives in
tests/unit/onyx/server/test_admin_audit_events.py, so only the paths with real
logic live here: the permission diff, the two reads that must happen before the
value they capture is destroyed, and the two places a second event could sneak in.
"""

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from ee.onyx.db.user_group import prepare_user_group_for_deletion
from ee.onyx.server.user_group.api import (
    add_users,
    delete_user_group,
    rename_user_group_endpoint,
    set_user_group_permissions,
)
from ee.onyx.server.user_group.models import (
    AddUsersToUserGroupRequest,
    BulkSetPermissionsRequest,
    UserGroupRename,
)
from onyx.db.enums import Permission
from onyx.db.models import User, User__UserGroup, UserGroup
from onyx.utils.audit import AuditAction, AuditOutcome
from tests.external_dependency_unit.conftest import create_test_user, delete_test_user
from tests.utils.audit import audit_actions, events_for

_EMIT = "ee.onyx.server.user_group.api.emit_audit_event"

pytestmark = pytest.mark.usefixtures("tenant_context")


@pytest.fixture
def admin(db_session: Session) -> User:
    return create_test_user(db_session, "group_audit_admin", is_admin=True)


def _make_group(db_session: Session, *members: User) -> UserGroup:
    # is_up_to_date=True: the rename/delete guards refuse a group mid-sync.
    group = UserGroup(name=f"audit-test-{uuid4().hex[:12]}", is_up_to_date=True)
    db_session.add(group)
    db_session.flush()
    for member in members:
        db_session.add(User__UserGroup(user_id=member.id, user_group_id=group.id))
    db_session.commit()
    return group


def _one_call(emit: MagicMock, action: AuditAction) -> dict:
    calls = [call for call in emit.call_args_list if call.args[0] is action]
    assert len(calls) == 1, f"expected one {action.value}, got {len(calls)}"
    assert calls[0].args[1] is AuditOutcome.SUCCESS
    return {
        "resource_id": calls[0].kwargs["resource_id"],
        "resource_type": calls[0].kwargs["resource_type"],
        "extra": calls[0].kwargs["extra"],
    }


def test_permission_change_reports_the_diff(db_session: Session, admin: User) -> None:
    group = _make_group(db_session)

    # Start from a known state so the second save is a genuine add-and-remove.
    set_user_group_permissions(
        group.id,
        BulkSetPermissionsRequest(
            permissions=[Permission.MANAGE_CONNECTORS, Permission.READ_QUERY_HISTORY]
        ),
        admin,
        db_session,
    )

    with patch(_EMIT) as emit:
        set_user_group_permissions(
            group.id,
            BulkSetPermissionsRequest(
                permissions=[Permission.MANAGE_CONNECTORS, Permission.MANAGE_LLMS]
            ),
            admin,
            db_session,
        )

    event = _one_call(emit, AuditAction.USER_GROUP_PERMISSION_CHANGE)
    assert event["resource_id"] == group.id
    assert event["resource_type"] == "user_group"
    assert event["extra"]["group_name"] == group.name
    assert event["extra"]["added"] == ["manage:llms"]
    assert event["extra"]["removed"] == ["read:query_history"]
    # Unchanged and non-toggleable grants sit on both sides and cancel.
    assert "manage:connectors" not in event["extra"]["added"]
    assert "basic" not in event["extra"]["added"] + event["extra"]["removed"]

    # Re-saving the same state still emits (it is a deliberate admin action) but
    # reports no delta, so an alert keyed on `added` stays quiet.
    with patch(_EMIT) as emit:
        set_user_group_permissions(
            group.id,
            BulkSetPermissionsRequest(
                permissions=[Permission.MANAGE_CONNECTORS, Permission.MANAGE_LLMS]
            ),
            admin,
            db_session,
        )
    resave = _one_call(emit, AuditAction.USER_GROUP_PERMISSION_CHANGE)
    assert resave["extra"]["added"] == []
    assert resave["extra"]["removed"] == []


def test_rename_records_the_previous_name(db_session: Session, admin: User) -> None:
    """The DB fn renames in place, so a naive read would report the new name twice."""
    group = _make_group(db_session)
    original = group.name
    new_name = f"audit-renamed-{uuid4().hex[:12]}"

    with patch(_EMIT) as emit:
        rename_user_group_endpoint(
            UserGroupRename(id=group.id, name=new_name), admin, db_session
        )

    event = _one_call(emit, AuditAction.USER_GROUP_RENAME)
    assert event["extra"]["previous_name"] == original
    assert event["extra"]["new_name"] == new_name


@pytest.mark.usefixtures("audit_stream")
def test_delete_records_who_lost_access_exactly_once(
    db_session: Session, admin: User, caplog: pytest.LogCaptureFixture
) -> None:
    """monitor_usergroup_taskset deliberately re-runs prepare_user_group_for_deletion
    after marking the group synced. The emit lives on the route so that second pass
    stays silent — inside the DB function it would fire again with no actor.
    """
    member = create_test_user(db_session, "group_audit_deleted")
    group = _make_group(db_session, member)
    name = group.name

    delete_user_group(group.id, admin, db_session)

    assert audit_actions(caplog) == ["user_group.delete"]
    event = events_for(caplog, "user_group.delete")[0]
    assert event["extra"]["name"] == name
    assert event["extra"]["member_ids"] == [str(member.id)]

    group.is_up_to_date = True
    db_session.commit()
    prepare_user_group_for_deletion(db_session, group.id)

    assert audit_actions(caplog) == ["user_group.delete"]
    delete_test_user(db_session, member)


@pytest.mark.usefixtures("audit_stream")
def test_add_users_emits_exactly_one_membership_event(
    db_session: Session, admin: User, caplog: pytest.LogCaptureFixture
) -> None:
    """add-users delegates to update_user_group, which already emits. A second
    emit on the route would double-count one membership change."""
    member = create_test_user(db_session, "group_audit_added")
    group = _make_group(db_session)

    add_users(
        group.id,
        AddUsersToUserGroupRequest(user_ids=[member.id]),
        admin,
        db_session,
    )

    assert audit_actions(caplog) == ["user.group_change"]
    delete_test_user(db_session, member)
