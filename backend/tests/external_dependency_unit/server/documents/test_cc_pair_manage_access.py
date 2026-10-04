"""The manage-access routes, called directly: pair side, group side and prefill.

The integration suite covers the same rules over HTTP; this runs them against a real
Postgres without a deployment."""

from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from ee.onyx.server.documents.cc_pair import (
    get_cc_pair_manage_access,
    get_manage_access_prefill,
    set_cc_pair_manage_access,
)
from ee.onyx.server.documents.manage_access import CCPairManageAccessUpdateRequest
from ee.onyx.server.user_group.api import set_group_managed_cc_pairs
from ee.onyx.server.user_group.models import (
    GroupManagedCCPairsUpdateRequest,
    ManagedCCPairEntry,
)
from onyx.db.enums import AccessType, ConnectorManageRole, GrantSource, Permission
from onyx.db.models import (
    ConnectorCredentialPair,
    PermissionGrant,
    User,
    User__UserGroup,
    UserGroup,
    UserGroup__ConnectorCredentialPair,
)
from onyx.error_handling.exceptions import OnyxError
from onyx.server.documents.models import CCPairManageAccessEntry
from tests.external_dependency_unit.conftest import create_test_user
from tests.external_dependency_unit.indexing_helpers import make_cc_pair

pytestmark = pytest.mark.usefixtures("tenant_context")

EDITOR = ConnectorManageRole.EDITOR
OPERATOR = ConnectorManageRole.OPERATOR


def _group(db_session: Session) -> UserGroup:
    group = UserGroup(name=f"ma-{uuid4().hex[:12]}")
    db_session.add(group)
    db_session.flush()
    return group


def _manager_of(db_session: Session, group: UserGroup) -> User:
    user = create_test_user(db_session, "ma-mgr")
    user.effective_permissions = []
    user.is_group_manager = True
    db_session.add(
        User__UserGroup(user_id=user.id, user_group_id=group.id, is_manager=True)
    )
    db_session.commit()
    return user


def _pair(
    db_session: Session, rows: dict[UserGroup, ConnectorManageRole]
) -> ConnectorCredentialPair:
    cc_pair = make_cc_pair(db_session)
    cc_pair.access_type = AccessType.PRIVATE
    for group, role in rows.items():
        db_session.add(
            UserGroup__ConnectorCredentialPair(
                user_group_id=group.id, cc_pair_id=cc_pair.id, role=role
            )
        )
    db_session.commit()
    return cc_pair


def _stored(db_session: Session, cc_pair_id: int, user: User) -> dict[int, str]:
    return {
        row.group_id: row.role.value
        for row in get_cc_pair_manage_access(cc_pair_id, user, db_session)
        if not row.is_fixed
    }


def _put(
    db_session: Session,
    cc_pair_id: int,
    user: User,
    rows: dict[UserGroup, ConnectorManageRole],
) -> None:
    set_cc_pair_manage_access(
        cc_pair_id,
        CCPairManageAccessUpdateRequest(
            manage_access=[
                CCPairManageAccessEntry(group_id=group.id, role=role)
                for group, role in rows.items()
            ]
        ),
        user,
        db_session,
    )


def test_get_lists_fixed_admin_rows_then_stored_rows(db_session: Session) -> None:
    group = _group(db_session)
    admin = create_test_user(db_session, "ma-admin", is_admin=True)
    cc_pair = _pair(db_session, {group: OPERATOR})

    rows = get_cc_pair_manage_access(cc_pair.id, admin, db_session)

    fixed = [row for row in rows if row.is_fixed]
    assert "Admin" in {row.group_name for row in fixed}
    assert {row.role for row in fixed} == {EDITOR}
    assert [(row.group_id, row.role) for row in rows if not row.is_fixed] == [
        (group.id, OPERATOR)
    ]


def test_put_edits_rows_in_place_and_keeps_fixed_rows(db_session: Session) -> None:
    kept = _group(db_session)
    dropped = _group(db_session)
    added = _group(db_session)
    admin = create_test_user(db_session, "ma-admin-put", is_admin=True)
    cc_pair = _pair(db_session, {kept: EDITOR, dropped: EDITOR})

    _put(db_session, cc_pair.id, admin, {kept: OPERATOR, added: EDITOR})

    assert _stored(db_session, cc_pair.id, admin) == {
        kept.id: "operator",
        added.id: "editor",
    }
    live_rows = db_session.query(UserGroup__ConnectorCredentialPair).filter_by(
        cc_pair_id=cc_pair.id
    )
    assert all(row.is_current for row in live_rows), "a write left history rows"

    _put(db_session, cc_pair.id, admin, {})
    rows = get_cc_pair_manage_access(cc_pair.id, admin, db_session)
    assert rows and all(row.is_fixed for row in rows)


def test_put_keeps_the_hidden_row_of_a_group_with_a_global_grant(
    db_session: Session,
) -> None:
    granted = _group(db_session)
    admin = create_test_user(db_session, "ma-admin-grant", is_admin=True)
    cc_pair = _pair(db_session, {granted: OPERATOR})
    db_session.add(
        PermissionGrant(
            group_id=granted.id,
            permission=Permission.MANAGE_CONNECTORS,
            grant_source=GrantSource.USER,
        )
    )
    db_session.commit()
    assert granted.id not in _stored(db_session, cc_pair.id, admin)

    _put(db_session, cc_pair.id, admin, {})

    rows = db_session.query(UserGroup__ConnectorCredentialPair).filter_by(
        cc_pair_id=cc_pair.id, user_group_id=granted.id
    )
    assert [row.role for row in rows] == [OPERATOR]


def test_put_limits_a_scoped_editor_to_visible_groups(db_session: Session) -> None:
    mine = _group(db_session)
    other = _group(db_session)
    editor = _manager_of(db_session, mine)
    admin = create_test_user(db_session, "ma-admin-vis", is_admin=True)
    cc_pair = _pair(db_session, {mine: EDITOR, other: OPERATOR})

    for rows in (
        {mine: EDITOR, other: EDITOR},  # re-roles other
        {mine: EDITOR, other: OPERATOR, _group(db_session): OPERATOR},  # adds one
    ):
        with pytest.raises(OnyxError):
            _put(db_session, cc_pair.id, editor, rows)
        db_session.rollback()

    # leaving out a group the editor cannot see keeps its row
    _put(db_session, cc_pair.id, editor, {mine: EDITOR})
    assert _stored(db_session, cc_pair.id, admin) == {
        mine.id: "editor",
        other.id: "operator",
    }

    _put(db_session, cc_pair.id, editor, {mine: OPERATOR, other: OPERATOR})
    assert _stored(db_session, cc_pair.id, admin) == {
        mine.id: "operator",
        other.id: "operator",
    }

    # now an Operator: they may read the rows but no longer change them
    assert _stored(db_session, cc_pair.id, editor)
    with pytest.raises(OnyxError):
        _put(db_session, cc_pair.id, editor, {mine: OPERATOR, other: OPERATOR})


def test_put_refuses_default_and_unknown_groups(db_session: Session) -> None:
    admin = create_test_user(db_session, "ma-admin-def", is_admin=True)
    cc_pair = _pair(db_session, {})
    basic = db_session.query(UserGroup).filter_by(name="Basic", is_default=True).one()

    with pytest.raises(OnyxError):
        _put(db_session, cc_pair.id, admin, {basic: EDITOR})
    db_session.rollback()

    ghost = UserGroup(id=2_000_000_000, name="ghost")
    with pytest.raises(OnyxError):
        _put(db_session, cc_pair.id, admin, {ghost: EDITOR})


def test_group_side_keeps_the_group_edit_authorization(db_session: Session) -> None:
    """A scoped groups manager may attach or re-role only private pairs whose every
    group they manage, or groupless pairs they created, and may give only a role
    they hold. Removal is not restricted."""
    mine = _group(db_session)
    other = _group(db_session)
    manager = _manager_of(db_session, mine)
    operated = _pair(db_session, {mine: OPERATOR})
    shared = _pair(db_session, {mine: OPERATOR, other: EDITOR})
    public = _pair(db_session, {})
    public.access_type = AccessType.PUBLIC
    others_groupless = _pair(db_session, {})
    own_groupless = _pair(db_session, {})
    own_groupless.creator_id = manager.id
    db_session.commit()

    def put(entries: list[ManagedCCPairEntry]) -> dict[int, ConnectorManageRole]:
        result = set_group_managed_cc_pairs(
            mine.id,
            GroupManagedCCPairsUpdateRequest(cc_pairs=entries),
            manager,
            db_session,
        )
        return {entry.cc_pair_id: entry.role for entry in result}

    keep = [
        ManagedCCPairEntry(cc_pair_id=operated.id, role=OPERATOR),
        ManagedCCPairEntry(cc_pair_id=shared.id, role=OPERATOR),
    ]
    for refused in (public, others_groupless):
        with pytest.raises(OnyxError):
            put(keep + [ManagedCCPairEntry(cc_pair_id=refused.id)])
        db_session.rollback()
    # re-roling a pair that also sits in a group they don't manage
    with pytest.raises(OnyxError):
        put([keep[0], ManagedCCPairEntry(cc_pair_id=shared.id, role=EDITOR)])
    db_session.rollback()

    # an Operator can't make their group an Editor
    with pytest.raises(OnyxError):
        put([ManagedCCPairEntry(cc_pair_id=operated.id, role=EDITOR), keep[1]])
    db_session.rollback()

    # attach their own groupless pair (EDITOR by default), re-role it, and drop
    # the shared one
    assert put([keep[0], ManagedCCPairEntry(cc_pair_id=own_groupless.id)]) == {
        operated.id: OPERATOR,
        own_groupless.id: EDITOR,
    }
    assert put(
        [keep[0], ManagedCCPairEntry(cc_pair_id=own_groupless.id, role=OPERATOR)]
    ) == {operated.id: OPERATOR, own_groupless.id: OPERATOR}


def test_group_side_refuses_a_group_the_caller_does_not_manage(
    db_session: Session,
) -> None:
    manager = _manager_of(db_session, _group(db_session))
    other = _group(db_session)
    with pytest.raises(OnyxError):
        set_group_managed_cc_pairs(
            other.id, GroupManagedCCPairsUpdateRequest(cc_pairs=[]), manager, db_session
        )


def test_prefill_marks_data_access_groups_as_operators(db_session: Session) -> None:
    admin = create_test_user(db_session, "ma-admin-pre", is_admin=True)
    data_group = _group(db_session)
    admin_group = db_session.query(UserGroup).filter_by(name="Admin").one()

    rows = get_manage_access_prefill([data_group.id, admin_group.id], admin, db_session)

    assert (data_group.id, OPERATOR, False) in {
        (row.group_id, row.role, row.is_fixed) for row in rows
    }
    admin_rows = [row for row in rows if row.group_id == admin_group.id]
    assert [(row.role, row.is_fixed) for row in admin_rows] == [(EDITOR, True)]


def test_prefill_drops_groups_the_caller_cannot_see(db_session: Session) -> None:
    mine = _group(db_session)
    other = _group(db_session)
    manager = _manager_of(db_session, mine)

    rows = get_manage_access_prefill([mine.id, other.id], manager, db_session)

    operator_ids = {row.group_id for row in rows if not row.is_fixed}
    assert operator_ids == {mine.id}
