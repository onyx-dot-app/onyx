"""The read-side permission projection must equal write-side enforcement.

Each test drives the REAL guard and asserts the extracted boolean the projection
stamps matches whether the guard raises, across an actor matrix — so the affordance
the client renders can't silently drift from what the backend enforces.
"""

from collections.abc import Callable
from uuid import uuid4

from sqlalchemy.orm import Session

from ee.onyx.db.analytics import user_can_view_assistant_stats
from onyx.auth.permission_projection import CC_PAIR_ACTIONS
from onyx.auth.permission_projection import cc_pair_permissions
from onyx.auth.permission_projection import DOCUMENT_SET_ACTIONS
from onyx.auth.permission_projection import document_set_permissions
from onyx.auth.permission_projection import PERSONA_ACTIONS
from onyx.auth.permission_projection import persona_permissions
from onyx.auth.permissions import has_global_permission
from onyx.auth.scoped_permissions import assert_manages_group
from onyx.auth.scoped_permissions import assert_within_scope
from onyx.auth.scoped_permissions import manages_group
from onyx.auth.scoped_permissions import within_scope
from onyx.db.document_set import fetch_all_document_sets_for_user
from onyx.db.enums import Permission
from onyx.db.enums import PersonaSharePermission
from onyx.db.models import DocumentSet
from onyx.db.models import DocumentSet__UserGroup
from onyx.db.models import Persona
from onyx.db.models import Persona__UserGroup
from onyx.db.models import User
from onyx.db.models import User__UserGroup
from onyx.db.models import UserGroup
from onyx.db.persona import _assert_persona_update_within_managed_scope
from onyx.db.persona import can_delete_persona
from onyx.db.persona import can_edit_persona
from onyx.db.persona import can_view_persona_stats
from onyx.db.persona import get_persona_by_id
from onyx.db.persona import is_persona_editable_by_user
from onyx.db.persona import persona_edit_within_scope
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.persona.models import PersonaUpsertRequest
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


def _make_persona(
    db_session: Session, *, owner: User, is_public: bool, groups: list[UserGroup]
) -> Persona:
    persona = Persona(
        name=f"proj-persona-{uuid4().hex[:12]}",
        description="contract",
        public_permission=PersonaSharePermission.EDITOR,
        user_id=owner.id,
        is_public=is_public,
    )
    db_session.add(persona)
    db_session.flush()
    for group in groups:
        db_session.add(
            Persona__UserGroup(persona_id=persona.id, user_group_id=group.id)
        )
    db_session.commit()
    return persona


def _make_doc_set(
    db_session: Session, *, is_public: bool, groups: list[UserGroup]
) -> DocumentSet:
    doc_set = DocumentSet(name=f"proj-ds-{uuid4().hex[:12]}", is_public=is_public)
    db_session.add(doc_set)
    db_session.flush()
    for group in groups:
        db_session.add(
            DocumentSet__UserGroup(document_set_id=doc_set.id, user_group_id=group.id)
        )
    db_session.commit()
    return doc_set


def test_persona_projection_matches_gates(db_session: Session) -> None:
    """edit tracks the read-editable AND managed-scope decision the write guard enforces;
    view_stats tracks the real owner-or-admin stats gate; the rest are global-only."""
    managed = _make_group(db_session)
    unmanaged = _make_group(db_session)

    in_scope = create_test_user(db_session, "b-persona-in")
    _manage(db_session, in_scope, managed)
    in_scope.effective_permissions = []

    out_scope = create_test_user(db_session, "b-persona-out")
    _manage(db_session, out_scope, unmanaged)
    out_scope.effective_permissions = []

    owner = create_test_user(db_session, "b-persona-owner")
    owner.effective_permissions = []

    admin = create_test_user(db_session, "b-persona-admin", is_admin=True)
    db_session.commit()

    persona = _make_persona(db_session, owner=owner, is_public=False, groups=[managed])
    group_ids = [group.id for group in persona.groups]

    def edit_guard_raises(actor: User) -> bool:
        request = PersonaUpsertRequest(
            name=persona.name,
            description=persona.description or "",
            system_prompt="",
            task_prompt="",
            datetime_aware=False,
            document_set_ids=[],
            tool_ids=[],
            groups=group_ids,
            is_public=persona.is_public,
        )
        return _guard_raises(
            _assert_persona_update_within_managed_scope,
            persona.id,
            request,
            actor,
            db_session,
        )

    for actor in (in_scope, out_scope, owner, admin):
        # read bool == the real write guard's managed-scope decision
        assert persona_edit_within_scope(
            actor, db_session, group_ids=group_ids, is_public=persona.is_public
        ) == (not edit_guard_raises(actor)), actor.email
        # view_stats == the real owner-or-admin stats gate
        assert can_view_persona_stats(actor, persona) == user_can_view_assistant_stats(
            db_session, actor, persona.id
        ), actor.email
        # delete == the real delete handler's ownership gate (get_persona_by_id is_for_edit)
        try:
            get_persona_by_id(persona_id=persona.id, user=actor, db_session=db_session)
            delete_allowed = True
        except ValueError:
            delete_allowed = False
        assert can_delete_persona(actor, persona, db_session) == delete_allowed, (
            actor.email
        )

    # concrete: an in-scope manager can edit/share but not view_stats/delete/feature/reorder
    mgr_map = persona_permissions(
        can_edit=can_edit_persona(
            in_scope,
            persona,
            db_session,
            is_editable=is_persona_editable_by_user(db_session, persona.id, in_scope),
        ),
        can_view_stats=can_view_persona_stats(in_scope, persona),
        can_delete=can_delete_persona(in_scope, persona, db_session),
        is_manage_agents_admin=has_global_permission(
            in_scope, Permission.MANAGE_AGENTS
        ),
        is_full_admin=has_global_permission(
            in_scope, Permission.FULL_ADMIN_PANEL_ACCESS
        ),
    )
    assert mgr_map["edit"] is True and mgr_map["share"] is True
    assert mgr_map["view_stats"] is False
    assert not any(mgr_map[a] for a in ("delete", "publish", "feature", "reorder"))


def test_document_set_projection_matches_gates(db_session: Session) -> None:
    """edit tracks the editable filter, which equals the within_scope decision the write
    guard enforces; delete/publish track global MANAGE_DOCUMENT_SETS."""
    managed = _make_group(db_session)

    in_scope = create_test_user(db_session, "b-ds-in")
    _manage(db_session, in_scope, managed)
    in_scope.effective_permissions = []

    out_scope = create_test_user(db_session, "b-ds-out")
    _manage(db_session, out_scope, _make_group(db_session))
    out_scope.effective_permissions = []

    admin = create_test_user(db_session, "b-ds-admin", is_admin=True)
    db_session.commit()

    doc_set = _make_doc_set(db_session, is_public=False, groups=[managed])

    for actor in (in_scope, out_scope, admin):
        editable_ids = {
            ds.id
            for ds in fetch_all_document_sets_for_user(
                db_session=db_session, user=actor, get_editable=True
            )
        }
        is_editable = doc_set.id in editable_ids
        # the editable filter equals the write guard's scope decision
        scope_decision = within_scope(
            actor,
            db_session,
            permission=Permission.MANAGE_DOCUMENT_SETS,
            current_group_ids=[managed.id],
            requested_group_ids=[managed.id],
            is_non_public=True,
        )
        assert is_editable == scope_decision, actor.email

        is_ds_admin = has_global_permission(actor, Permission.MANAGE_DOCUMENT_SETS)
        tags = document_set_permissions(
            is_editable=is_editable, is_document_sets_admin=is_ds_admin
        )
        assert tags["edit"] == scope_decision
        assert tags["manage_access"] == scope_decision
        assert tags["delete"] == is_ds_admin


def test_persona_and_doc_set_key_coverage() -> None:
    persona_keys = set(
        persona_permissions(
            can_edit=True,
            can_view_stats=True,
            can_delete=True,
            is_manage_agents_admin=True,
            is_full_admin=True,
        )
    )
    assert persona_keys == set(PERSONA_ACTIONS)
    ds_keys = set(
        document_set_permissions(is_editable=True, is_document_sets_admin=True)
    )
    assert ds_keys == set(DOCUMENT_SET_ACTIONS)
