"""Tests for the scoped-manager authorization primitives — both gates and the
read-side scope clause, against a real database."""

from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.auth.permissions import SCOPED_MANAGER_PERMISSIONS
from onyx.auth.scoped_permissions import assert_global
from onyx.auth.scoped_permissions import assert_within_scope
from onyx.auth.scoped_permissions import get_scoped_groups
from onyx.db.enums import AccessType
from onyx.db.enums import Permission
from onyx.db.models import ConnectorCredentialPair
from onyx.db.models import DocumentSet
from onyx.db.models import DocumentSet__UserGroup
from onyx.db.models import User
from onyx.db.models import User__UserGroup
from onyx.db.models import UserGroup
from onyx.db.models import UserGroup__ConnectorCredentialPair
from onyx.db.scoped_permissions import scoped_group_ids_subquery
from onyx.db.scoped_permissions import within_managed_scope_clause
from onyx.error_handling.exceptions import OnyxError
from tests.external_dependency_unit.conftest import create_test_user
from tests.external_dependency_unit.indexing_helpers import make_cc_pair


def _make_group(db_session: Session) -> UserGroup:
    group = UserGroup(name=f"scope-test-{uuid4().hex[:12]}")
    db_session.add(group)
    db_session.flush()
    return group


def _manage(db_session: Session, user: User, *groups: UserGroup) -> None:
    for group in groups:
        db_session.add(
            User__UserGroup(user_id=user.id, user_group_id=group.id, is_manager=True)
        )
    user.is_group_manager = True  # recompute sets this cached flag in reality
    db_session.commit()


def _doc_set(db_session: Session, *, is_public: bool, groups: list[UserGroup]) -> int:
    ds = DocumentSet(name=f"ds-{uuid4().hex[:12]}", is_public=is_public)
    db_session.add(ds)
    db_session.flush()
    for group in groups:
        db_session.add(
            DocumentSet__UserGroup(document_set_id=ds.id, user_group_id=group.id)
        )
    db_session.commit()
    return ds.id


def test_bundle_is_the_seven_token_set() -> None:
    assert SCOPED_MANAGER_PERMISSIONS == frozenset(
        {
            Permission.MANAGE_CONNECTORS,
            Permission.MANAGE_DOCUMENT_SETS,
            Permission.MANAGE_AGENTS,
            Permission.ADD_AGENTS,
            Permission.MANAGE_USER_GROUPS,
            Permission.MANAGE_ACTIONS,
            Permission.MANAGE_SKILLS,
        }
    )
    # admin-only tokens must never be scopable
    assert Permission.MANAGE_LLMS not in SCOPED_MANAGER_PERMISSIONS


def test_get_scoped_groups_returns_only_managed_edges(db_session: Session) -> None:
    user = create_test_user(db_session, "scope-mgr")
    managed_a, managed_b, member_only = (
        _make_group(db_session),
        _make_group(db_session),
        _make_group(db_session),
    )
    _manage(db_session, user, managed_a, managed_b)
    db_session.add(
        User__UserGroup(user_id=user.id, user_group_id=member_only.id, is_manager=False)
    )
    db_session.commit()

    assert get_scoped_groups(user, db_session) == {managed_a.id, managed_b.id}
    assert get_scoped_groups(user, db_session, Permission.MANAGE_DOCUMENT_SETS) == {
        managed_a.id,
        managed_b.id,
    }
    # non-bundle token → no scope
    assert get_scoped_groups(user, db_session, Permission.MANAGE_LLMS) == set()


def test_get_scoped_groups_empty_for_non_manager(db_session: Session) -> None:
    user = create_test_user(db_session, "scope-plain")
    group = _make_group(db_session)
    db_session.add(
        User__UserGroup(user_id=user.id, user_group_id=group.id, is_manager=False)
    )
    db_session.commit()
    assert get_scoped_groups(user, db_session) == set()


def test_assert_global_admits_only_global(db_session: Session) -> None:
    """Admin-only gate (rule A): a SCOPED manager is rejected; GLOBAL passes."""
    manager = create_test_user(db_session, "global-gate-mgr")
    _manage(db_session, manager, _make_group(db_session))
    manager.is_group_manager = True
    manager.effective_permissions = []  # SCOPED for a bundle token, no global grant

    # SCOPED → rejected even on a bundle token they "reach" at the route.
    with pytest.raises(OnyxError):
        assert_global(manager, permission=Permission.MANAGE_DOCUMENT_SETS)

    # NONE → rejected.
    plain = create_test_user(db_session, "global-gate-plain")
    plain.effective_permissions = []
    with pytest.raises(OnyxError):
        assert_global(plain, permission=Permission.MANAGE_DOCUMENT_SETS)

    # GLOBAL holder → passes.
    holder = create_test_user(db_session, "global-gate-holder")
    holder.effective_permissions = [Permission.MANAGE_DOCUMENT_SETS.value]
    assert_global(holder, permission=Permission.MANAGE_DOCUMENT_SETS)

    # Admin → passes any token.
    admin = create_test_user(db_session, "global-gate-admin", is_admin=True)
    assert_global(admin, permission=Permission.MANAGE_DOCUMENT_SETS)


def test_assert_within_scope_admin_and_global_bypass(
    db_session: Session,
) -> None:
    admin = create_test_user(db_session, "gate2-admin", is_admin=True)
    # bypasses every invariant — public + out-of-scope args still pass
    assert_within_scope(
        admin,
        db_session,
        permission=Permission.MANAGE_DOCUMENT_SETS,
        current_group_ids=[999_999],
        requested_group_ids=[],
        is_non_public=False,
    )

    holder = create_test_user(db_session, "gate2-holder")
    holder.effective_permissions = [Permission.MANAGE_DOCUMENT_SETS.value]
    assert_within_scope(
        holder,
        db_session,
        permission=Permission.MANAGE_DOCUMENT_SETS,
        current_group_ids=[999_999],
        requested_group_ids=[],
        is_non_public=False,
    )


def test_assert_within_scope_manager_invariants(
    db_session: Session,
) -> None:
    manager = create_test_user(db_session, "gate2-mgr")
    manager.effective_permissions = []  # scoped only, no global token
    managed = _make_group(db_session)
    unmanaged = _make_group(db_session)
    _manage(db_session, manager, managed)

    perm = Permission.MANAGE_DOCUMENT_SETS

    # happy path: private, all groups managed, ≥1 group
    assert_within_scope(
        manager,
        db_session,
        permission=perm,
        current_group_ids=[managed.id],
        requested_group_ids=[],
        is_non_public=True,
    )

    # out-of-scope group (capture-by-reassign) → reject
    with pytest.raises(OnyxError):
        assert_within_scope(
            manager,
            db_session,
            permission=perm,
            current_group_ids=[managed.id],
            requested_group_ids=[unmanaged.id],
            is_non_public=True,
        )

    # detach to zero groups → reject
    with pytest.raises(OnyxError):
        assert_within_scope(
            manager,
            db_session,
            permission=perm,
            current_group_ids=[],
            requested_group_ids=[],
            is_non_public=True,
        )

    # non-private resource → reject
    with pytest.raises(OnyxError):
        assert_within_scope(
            manager,
            db_session,
            permission=perm,
            current_group_ids=[managed.id],
            requested_group_ids=[],
            is_non_public=False,
        )


def test_assert_within_scope_fails_closed_on_empty_scope(
    db_session: Session,
) -> None:
    # SCOPED but manages nothing → empty scope → reject even a well-formed request
    user = create_test_user(db_session, "gate2-noscope")
    user.effective_permissions = []
    user.is_group_manager = True  # flag set, but no manager edges
    with pytest.raises(OnyxError):
        assert_within_scope(
            user,
            db_session,
            permission=Permission.MANAGE_DOCUMENT_SETS,
            current_group_ids=[1],
            requested_group_ids=[],
            is_non_public=True,
        )


def test_assert_within_scope_classifies_each_permission(
    db_session: Session,
) -> None:
    """A user may hold one bundle token globally and another only via manager
    scope; GATE 2 classifies each permission independently."""
    user = create_test_user(db_session, "gate2-mixed")
    user.effective_permissions = [Permission.MANAGE_AGENTS.value]  # global agents only
    managed = _make_group(db_session)
    unmanaged = _make_group(db_session)
    _manage(db_session, user, managed)

    # manage:agents held globally → scope ignored, even an out-of-scope group passes
    assert_within_scope(
        user,
        db_session,
        permission=Permission.MANAGE_AGENTS,
        current_group_ids=[unmanaged.id],
        requested_group_ids=[],
        is_non_public=True,
    )

    # manage:connectors only via scope → out-of-scope group rejected
    with pytest.raises(OnyxError):
        assert_within_scope(
            user,
            db_session,
            permission=Permission.MANAGE_CONNECTORS,
            current_group_ids=[unmanaged.id],
            requested_group_ids=[],
            is_non_public=True,
        )

    # manage:connectors within managed scope → allowed
    assert_within_scope(
        user,
        db_session,
        permission=Permission.MANAGE_CONNECTORS,
        current_group_ids=[managed.id],
        requested_group_ids=[],
        is_non_public=True,
    )


def test_within_managed_scope_clause_selects_right_rows(db_session: Session) -> None:
    manager = create_test_user(db_session, "clause-mgr")
    managed_a = _make_group(db_session)
    managed_b = _make_group(db_session)
    unmanaged = _make_group(db_session)
    _manage(db_session, manager, managed_a, managed_b)

    private_one = _doc_set(db_session, is_public=False, groups=[managed_a])
    private_two = _doc_set(db_session, is_public=False, groups=[managed_a, managed_b])
    public_in_scope = _doc_set(db_session, is_public=True, groups=[managed_a])
    private_mixed = _doc_set(db_session, is_public=False, groups=[managed_a, unmanaged])
    private_no_group = _doc_set(db_session, is_public=False, groups=[])

    clause = within_managed_scope_clause(
        resource_id_col=DocumentSet.id,
        junction_resource_col=DocumentSet__UserGroup.document_set_id,
        junction_group_col=DocumentSet__UserGroup.user_group_id,
        non_public_clause=DocumentSet.is_public.is_(False),
        managed_subq=scoped_group_ids_subquery(manager),
    )
    editable = set(db_session.scalars(select(DocumentSet.id).where(clause)).all())

    assert private_one in editable
    assert private_two in editable
    assert public_in_scope not in editable
    assert private_mixed not in editable
    assert private_no_group not in editable

    # non-manager → empty scope → nothing editable
    plain = create_test_user(db_session, "clause-plain")
    plain_clause = within_managed_scope_clause(
        resource_id_col=DocumentSet.id,
        junction_resource_col=DocumentSet__UserGroup.document_set_id,
        junction_group_col=DocumentSet__UserGroup.user_group_id,
        non_public_clause=DocumentSet.is_public.is_(False),
        managed_subq=scoped_group_ids_subquery(plain),
    )
    plain_editable = set(
        db_session.scalars(select(DocumentSet.id).where(plain_clause)).all()
    )
    assert private_one not in plain_editable


def test_within_managed_scope_clause_handles_enum_privateness(
    db_session: Session,
) -> None:
    # cc_pair encodes privateness as access_type (enum), not a bool column — the
    # clause must accept any predicate, which a PR3 caller relies on.
    manager = create_test_user(db_session, "clause-ccpair-mgr")
    managed = _make_group(db_session)
    _manage(db_session, manager, managed)

    private_pair = make_cc_pair(db_session)
    private_pair.access_type = AccessType.PRIVATE
    public_pair = make_cc_pair(db_session)
    public_pair.access_type = AccessType.PUBLIC
    for pair in (private_pair, public_pair):
        db_session.add(
            UserGroup__ConnectorCredentialPair(
                user_group_id=managed.id, cc_pair_id=pair.id
            )
        )
    db_session.commit()

    clause = within_managed_scope_clause(
        resource_id_col=ConnectorCredentialPair.id,
        junction_resource_col=UserGroup__ConnectorCredentialPair.cc_pair_id,
        junction_group_col=UserGroup__ConnectorCredentialPair.user_group_id,
        non_public_clause=ConnectorCredentialPair.access_type == AccessType.PRIVATE,
        managed_subq=scoped_group_ids_subquery(manager),
    )
    editable = set(
        db_session.scalars(select(ConnectorCredentialPair.id).where(clause)).all()
    )

    assert private_pair.id in editable
    assert public_pair.id not in editable


def test_within_managed_scope_clause_includes_sync_cc_pairs(
    db_session: Session,
) -> None:
    # A manager manages the PRIVATE *and* SYNC cc_pairs in their groups, never
    # PUBLIC — so the cc_pair caller passes access_type != PUBLIC (not == PRIVATE).
    manager = create_test_user(db_session, "clause-sync-mgr")
    managed = _make_group(db_session)
    _manage(db_session, manager, managed)

    private_pair = make_cc_pair(db_session)
    private_pair.access_type = AccessType.PRIVATE
    sync_pair = make_cc_pair(db_session)
    sync_pair.access_type = AccessType.SYNC
    public_pair = make_cc_pair(db_session)
    public_pair.access_type = AccessType.PUBLIC
    for pair in (private_pair, sync_pair, public_pair):
        db_session.add(
            UserGroup__ConnectorCredentialPair(
                user_group_id=managed.id, cc_pair_id=pair.id
            )
        )
    db_session.commit()

    clause = within_managed_scope_clause(
        resource_id_col=ConnectorCredentialPair.id,
        junction_resource_col=UserGroup__ConnectorCredentialPair.cc_pair_id,
        junction_group_col=UserGroup__ConnectorCredentialPair.user_group_id,
        non_public_clause=ConnectorCredentialPair.access_type != AccessType.PUBLIC,
        managed_subq=scoped_group_ids_subquery(manager),
    )
    editable = set(
        db_session.scalars(select(ConnectorCredentialPair.id).where(clause)).all()
    )

    assert private_pair.id in editable
    assert sync_pair.id in editable
    assert public_pair.id not in editable
