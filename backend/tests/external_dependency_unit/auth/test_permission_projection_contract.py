"""The read-side permission projection must equal write-side enforcement.

Each test drives the REAL guard and asserts the extracted boolean the projection
stamps matches whether the guard raises, across an actor matrix — so the affordance
the client renders can't silently drift from what the backend enforces.
"""

from collections.abc import Callable
from uuid import uuid4

from sqlalchemy.orm import Session

from onyx.auth.permission_projection import CC_PAIR_ACTIONS
from onyx.auth.permission_projection import cc_pair_permissions
from onyx.auth.permissions import has_global_permission
from onyx.auth.scoped_permissions import assert_manages_group
from onyx.auth.scoped_permissions import assert_within_scope
from onyx.auth.scoped_permissions import manages_group
from onyx.auth.scoped_permissions import within_scope
from onyx.db.enums import Permission
from onyx.db.models import User
from onyx.db.models import User__UserGroup
from onyx.db.models import UserGroup
from onyx.error_handling.exceptions import OnyxError
from tests.external_dependency_unit.conftest import create_test_user


def _guard_raises(guard: Callable[..., None], *args: object, **kwargs: object) -> bool:
    try:
        guard(*args, **kwargs)
        return False
    except OnyxError:
        return True


def _make_group(db_session: Session) -> UserGroup:
    group = UserGroup(name=f"proj-contract-{uuid4().hex[:12]}")
    db_session.add(group)
    db_session.flush()
    return group


def _manage(db_session: Session, user: User, *groups: UserGroup) -> None:
    for group in groups:
        db_session.add(
            User__UserGroup(user_id=user.id, user_group_id=group.id, is_manager=True)
        )
    user.is_group_manager = True
    db_session.commit()


def test_within_scope_matches_assert_within_scope(db_session: Session) -> None:
    managed = _make_group(db_session)
    unmanaged = _make_group(db_session)

    manager = create_test_user(db_session, "proj-within-mgr")
    _manage(db_session, manager, managed)
    manager.effective_permissions = []  # SCOPED for a bundle token, no global grant

    admin = create_test_user(db_session, "proj-within-admin", is_admin=True)

    plain = create_test_user(db_session, "proj-within-plain")
    plain.effective_permissions = []
    db_session.commit()

    perm = Permission.MANAGE_DOCUMENT_SETS
    # (current_group_ids, requested_group_ids, is_non_public)
    configs = [
        ([managed.id], [managed.id], True),  # private, fully in managed scope
        ([managed.id], [managed.id], False),  # public — never in scope
        ([unmanaged.id], [unmanaged.id], True),  # private but out of scope
        ([managed.id], [unmanaged.id], True),  # reassignment escapes scope
        ([], [], True),  # no groups — fails closed (empty final)
    ]

    for actor in (admin, manager, plain):
        for current, requested, non_public in configs:
            decision = within_scope(
                actor,
                db_session,
                permission=perm,
                current_group_ids=current,
                requested_group_ids=requested,
                is_non_public=non_public,
            )
            enforced = not _guard_raises(
                assert_within_scope,
                actor,
                db_session,
                permission=perm,
                current_group_ids=current,
                requested_group_ids=requested,
                is_non_public=non_public,
            )
            assert decision == enforced, (
                f"drift: actor={actor.email} config={(current, requested, non_public)} "
                f"projection={decision} enforced={enforced}"
            )


def test_manages_group_matches_assert_manages_group(db_session: Session) -> None:
    managed = _make_group(db_session)
    other = _make_group(db_session)

    manager = create_test_user(db_session, "proj-mng-mgr")
    _manage(db_session, manager, managed)
    manager.effective_permissions = []

    admin = create_test_user(db_session, "proj-mng-admin", is_admin=True)

    plain = create_test_user(db_session, "proj-mng-plain")
    plain.effective_permissions = []
    db_session.commit()

    for actor in (admin, manager, plain):
        for group in (managed, other):
            decision = manages_group(actor, db_session, group_id=group.id)
            enforced = not _guard_raises(
                assert_manages_group, actor, db_session, group_id=group.id
            )
            assert decision == enforced, (
                f"drift: actor={actor.email} group={group.id} "
                f"projection={decision} enforced={enforced}"
            )


def test_cc_pair_projection_matches_gates(db_session: Session) -> None:
    """edit tracks the managed-scope within_scope decision; delete and publish track
    global MANAGE_CONNECTORS. A scoped manager edits a managed connector but can never
    delete it or make it public — those routes are global-only."""
    managed = _make_group(db_session)

    in_scope = create_test_user(db_session, "proj-cc-inscope")
    _manage(db_session, in_scope, managed)
    in_scope.effective_permissions = []

    out_scope = create_test_user(db_session, "proj-cc-outscope")
    _manage(db_session, out_scope, _make_group(db_session))
    out_scope.effective_permissions = []

    admin = create_test_user(db_session, "proj-cc-admin", is_admin=True)
    db_session.commit()

    for actor in (in_scope, out_scope, admin):
        editable = within_scope(
            actor,
            db_session,
            permission=Permission.MANAGE_CONNECTORS,
            current_group_ids=[managed.id],
            requested_group_ids=[managed.id],
            is_non_public=True,
        )
        admin_authority = has_global_permission(actor, Permission.MANAGE_CONNECTORS)
        tags = cc_pair_permissions(
            is_editable=editable, is_connectors_admin=admin_authority
        )
        assert tags["edit"] == editable  # M — the write-scope decision
        assert tags["delete"] == admin_authority  # A — never a scoped manager
        assert tags["publish"] == admin_authority  # A

    # the whole point of the fix: an in-scope manager can edit but not delete/publish
    manager_editable = within_scope(
        in_scope,
        db_session,
        permission=Permission.MANAGE_CONNECTORS,
        current_group_ids=[managed.id],
        requested_group_ids=[managed.id],
        is_non_public=True,
    )
    assert cc_pair_permissions(
        is_editable=manager_editable,
        is_connectors_admin=has_global_permission(
            in_scope, Permission.MANAGE_CONNECTORS
        ),
    ) == {"edit": True, "delete": False, "publish": False}


def test_cc_pair_projection_key_coverage() -> None:
    stamped = set(cc_pair_permissions(is_editable=True, is_connectors_admin=True))
    assert stamped == set(CC_PAIR_ACTIONS), (
        "cc_pair projection keys drifted from the declared CC_PAIR_ACTIONS vocabulary"
    )
