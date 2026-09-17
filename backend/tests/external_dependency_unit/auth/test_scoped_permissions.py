"""Tests for the scoped-manager authorization primitives — both gates and the
read-side scope clause, against a real database."""

from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.auth.permissions import (
    SCOPED_MANAGER_PERMISSIONS,
    SCOPED_MANAGER_PERMISSIONS_EXPANDED,
)
from onyx.auth.scoped_permissions import (
    assert_global,
    assert_manages_group,
    assert_within_scope,
    get_scoped_groups,
    manages_group,
    within_scope,
)
from onyx.db.document_set import get_document_set_by_id
from onyx.db.enums import AccessType, Permission
from onyx.db.models import (
    ConnectorCredentialPair,
    DocumentSet,
    DocumentSet__UserGroup,
    User,
    User__UserGroup,
    UserGroup,
    UserGroup__ConnectorCredentialPair,
)
from onyx.db.scoped_permissions import (
    fetch_managed_group_ids,
    scoped_group_ids_subquery,
    within_managed_scope_clause,
)
from onyx.error_handling.exceptions import OnyxError
from onyx.server.manage.models import UserInfo
from tests.external_dependency_unit.conftest import create_test_user
from tests.external_dependency_unit.indexing_helpers import make_cc_pair
from tests.utils.audit import events_for


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


def test_default_group_manager_edge_confers_no_scope(db_session: Session) -> None:
    """A manager edge on a default group (e.g. the GLOBAL_CURATOR backfill on "Basic",
    which holds the whole org) must grant no scope — only custom groups do."""
    user = create_test_user(db_session, "scope-default")
    custom = _make_group(db_session)
    default_group = UserGroup(name=f"default-{uuid4().hex[:12]}", is_default=True)
    db_session.add(default_group)
    db_session.flush()
    _manage(db_session, user, custom, default_group)

    assert fetch_managed_group_ids(user, db_session) == {custom.id}
    assert get_scoped_groups(user, db_session, Permission.MANAGE_USER_GROUPS) == {
        custom.id
    }
    # The per-group write gate is denied for the default group, allowed for the custom one.
    assert not manages_group(user, db_session, group_id=default_group.id)
    assert manages_group(user, db_session, group_id=custom.id)


def test_document_set_locked_fetch_returns_row(db_session: Session) -> None:
    """The patch path locks the row FOR UPDATE before GATE 2; ensure the locked fetch works
    (Postgres forbids FOR UPDATE with DISTINCT, so the query must drop it)."""
    ds_id = _doc_set(db_session, is_public=False, groups=[])
    locked = get_document_set_by_id(db_session, ds_id, for_update=True)
    assert locked is not None
    assert locked.id == ds_id


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


def test_manages_group_global_holder_bypasses_scope(db_session: Session) -> None:
    """The per-group gate, unlike the resource gate, takes no group arguments to
    validate — a global holder administers every group, including ones with no
    manager edge at all."""
    unmanaged = _make_group(db_session)

    holder = create_test_user(db_session, "mg-holder")
    holder.effective_permissions = [Permission.MANAGE_USER_GROUPS.value]
    assert manages_group(holder, db_session, group_id=unmanaged.id)
    assert_manages_group(holder, db_session, group_id=unmanaged.id)

    admin = create_test_user(db_session, "mg-admin", is_admin=True)
    assert manages_group(admin, db_session, group_id=unmanaged.id)


def test_manages_group_scoped_manager_only_managed(db_session: Session) -> None:
    manager = create_test_user(db_session, "mg-mgr")
    manager.effective_permissions = []
    managed = _make_group(db_session)
    unmanaged = _make_group(db_session)
    _manage(db_session, manager, managed)

    assert manages_group(manager, db_session, group_id=managed.id)
    assert_manages_group(manager, db_session, group_id=managed.id)

    assert not manages_group(manager, db_session, group_id=unmanaged.id)
    with pytest.raises(OnyxError):
        assert_manages_group(manager, db_session, group_id=unmanaged.id)


def test_manages_group_rejects_plain_member(db_session: Session) -> None:
    """Membership is not management: the gate keys on the manager edge, so a member
    of the very group being edited is still refused."""
    member = create_test_user(db_session, "mg-member")
    member.effective_permissions = []
    group = _make_group(db_session)
    db_session.add(
        User__UserGroup(user_id=member.id, user_group_id=group.id, is_manager=False)
    )
    db_session.commit()

    assert not manages_group(member, db_session, group_id=group.id)


def test_manages_group_honours_preloaded_scope(db_session: Session) -> None:
    """Row stamping passes a preloaded scope to avoid a query per row, so the gate
    must read that set instead of re-querying — otherwise the two disagree."""
    manager = create_test_user(db_session, "mg-preload")
    manager.effective_permissions = []
    managed = _make_group(db_session)
    _manage(db_session, manager, managed)

    assert not manages_group(
        manager, db_session, group_id=managed.id, managed_group_ids=set()
    )
    assert manages_group(
        manager, db_session, group_id=999_999, managed_group_ids={999_999}
    )


def test_within_scope_honours_preloaded_scope(db_session: Session) -> None:
    """Same preloaded-set contract on the resource gate."""
    manager = create_test_user(db_session, "ws-preload")
    manager.effective_permissions = []
    managed = _make_group(db_session)
    _manage(db_session, manager, managed)

    assert within_scope(
        manager,
        db_session,
        permission=Permission.MANAGE_DOCUMENT_SETS,
        current_group_ids=[managed.id],
        requested_group_ids=[],
        is_non_public=True,
    )
    assert not within_scope(
        manager,
        db_session,
        permission=Permission.MANAGE_DOCUMENT_SETS,
        current_group_ids=[managed.id],
        requested_group_ids=[],
        is_non_public=True,
        managed_group_ids=set(),
    )


def test_fetch_managed_group_ids_ignores_the_bundle(db_session: Session) -> None:
    """Bundle gating lives in get_scoped_groups, not the DB helper — a non-scopable
    token resolves no scope there while the raw manager edges are unchanged."""
    manager = create_test_user(db_session, "fetch-mgr")
    managed = _make_group(db_session)
    _manage(db_session, manager, managed)

    assert fetch_managed_group_ids(manager, db_session) == {managed.id}
    assert get_scoped_groups(manager, db_session, Permission.MANAGE_LLMS) == set()


def test_admin_capabilities_reveal_the_bundle_for_a_manager(
    db_session: Session,
) -> None:
    """``admin_capabilities`` is what reveals admin nav to a manager who holds no
    admin token; ``effective_permissions`` must stay global-only beside it, since
    org-wide gates read that field and would otherwise admit them."""
    manager = create_test_user(db_session, "caps-mgr")
    granted = [Permission.BASIC_ACCESS.value]
    manager.effective_permissions = granted
    _manage(db_session, manager, _make_group(db_session))

    info = UserInfo.from_model(manager, effective_permissions=granted)

    assert info.is_group_manager
    assert SCOPED_MANAGER_PERMISSIONS_EXPANDED <= set(info.admin_capabilities)
    assert info.effective_permissions == granted


def test_admin_capabilities_stay_global_only_without_a_manager_edge(
    db_session: Session,
) -> None:
    user = create_test_user(db_session, "caps-plain")
    granted = [Permission.BASIC_ACCESS.value]
    user.effective_permissions = granted

    info = UserInfo.from_model(user, effective_permissions=granted)

    assert not info.is_group_manager
    assert info.admin_capabilities == granted


@pytest.mark.usefixtures("audit_stream")
def test_each_gate_records_its_refusal(
    db_session: Session, caplog: pytest.LogCaptureFixture
) -> None:
    """A refused write is the escalation signal — the actor holds some authority
    and reached the handler. ``extra.gate`` says which gate refused, so an alert
    can tell an out-of-scope write from an admin-only one."""
    manager = create_test_user(db_session, "denial-mgr")
    manager.effective_permissions = []
    managed = _make_group(db_session)
    unmanaged = _make_group(db_session)
    _manage(db_session, manager, managed)

    with pytest.raises(OnyxError):
        assert_manages_group(manager, db_session, group_id=unmanaged.id)
    with pytest.raises(OnyxError):
        assert_global(manager, permission=Permission.MANAGE_DOCUMENT_SETS)
    with pytest.raises(OnyxError):
        assert_within_scope(
            manager,
            db_session,
            permission=Permission.MANAGE_DOCUMENT_SETS,
            current_group_ids=[managed.id],
            requested_group_ids=[unmanaged.id],
            is_non_public=True,
        )

    events = events_for(caplog, "permission.denied")
    assert [e["extra"]["gate"] for e in events] == [
        "manages_group",
        "global_only",
        "within_scope",
    ]
    assert all(e["outcome"] == "denied" for e in events)
    assert all(e["actor"]["email"] == manager.email for e in events)
    # Only the per-group gate has a single resource to name.
    assert events[0]["resource_id"] == str(unmanaged.id)
    assert events[1]["resource_id"] is None

    caplog.clear()
    admin = create_test_user(db_session, "denial-admin", is_admin=True)
    assert_manages_group(admin, db_session, group_id=unmanaged.id)
    assert_global(admin, permission=Permission.MANAGE_DOCUMENT_SETS)
    assert events_for(caplog, "permission.denied") == []


@pytest.mark.usefixtures("audit_stream")
def test_every_refusal_is_recorded(
    db_session: Session, caplog: pytest.LogCaptureFixture
) -> None:
    """A manager walking several resources produces one event each. These gates see
    no resource identity, so nothing here may be suppressed as a duplicate — a bulk
    update refusing two look-alike document sets is two separate attempts."""
    manager = create_test_user(db_session, "denial-walk")
    manager.effective_permissions = []
    managed = _make_group(db_session)
    first = _make_group(db_session)
    second = _make_group(db_session)
    _manage(db_session, manager, managed)

    def refuse(target_group_id: int) -> None:
        with pytest.raises(OnyxError):
            assert_within_scope(
                manager,
                db_session,
                permission=Permission.MANAGE_DOCUMENT_SETS,
                current_group_ids=[managed.id],
                requested_group_ids=[target_group_id],
                is_non_public=True,
            )

    refuse(first.id)
    refuse(second.id)
    # Indistinguishable from the first at this gate, but a distinct attempt.
    refuse(first.id)

    events = events_for(caplog, "permission.denied")
    assert [e["extra"]["requested_group_ids"] for e in events] == [
        [first.id],
        [second.id],
        [first.id],
    ]
