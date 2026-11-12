"""Regression coverage for the persona share-permission predicate: EDITOR
shares grant edit access, VIEWER shares grant use only, public_permission can
extend edit org-wide, and the computed access level / sharing status helpers
agree with the SQL filter."""

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from onyx.auth.permissions import has_global_permission
from onyx.db.enums import (
    Permission,
    PersonaAccessLevel,
    PersonaSharePermission,
    PersonaSharingStatus,
)
from onyx.db.models import Persona__User, User
from onyx.db.persona import (
    fetch_persona_by_id_for_user,
    get_minimal_persona_snapshots_for_user,
    update_persona_access,
    upsert_persona,
)
from onyx.db.persona_sharing import (
    derive_persona_sharing_status,
    get_persona_access_level,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.persona.api import delete_persona
from onyx.utils.variable_functionality import global_version
from tests.external_dependency_unit.conftest import create_test_user
from tests.external_dependency_unit.db.agent_sharing_helpers import (
    create_test_persona,
    share_persona_with_user,
)


def _can_fetch(
    db_session: Session, persona_id: int, user: User, editable: bool
) -> bool:
    try:
        fetch_persona_by_id_for_user(
            db_session=db_session,
            persona_id=persona_id,
            user=user,
            get_editable=editable,
        )
        return True
    except HTTPException:
        return False


def test_deleted_persona_is_not_fetchable_by_its_owner(db_session: Session) -> None:
    # Every caller mutates the agent, so a soft-deleted one must not come back — otherwise
    # it can still be rostered into a group or re-shared while invisible everywhere else.
    owner = create_test_user(db_session, "deleted-owner")
    persona = create_test_persona(db_session, owner)
    persona.deleted = True
    db_session.commit()

    assert not _can_fetch(db_session, persona.id, owner, editable=True)
    # upsert_persona's name-reuse path still needs it.
    assert fetch_persona_by_id_for_user(
        db_session=db_session,
        persona_id=persona.id,
        user=owner,
        include_deleted=True,
    )


def test_owner_has_edit_access(db_session: Session) -> None:
    owner = create_test_user(db_session, "owner")
    persona = create_test_persona(db_session, owner)
    assert _can_fetch(db_session, persona.id, owner, editable=True)
    assert _can_fetch(db_session, persona.id, owner, editable=False)


def test_viewer_share_grants_use_not_edit(db_session: Session) -> None:
    owner = create_test_user(db_session, "owner")
    viewer = create_test_user(db_session, "viewer")
    persona = create_test_persona(db_session, owner)
    share_persona_with_user(db_session, persona, viewer, PersonaSharePermission.VIEWER)

    assert _can_fetch(db_session, persona.id, viewer, editable=False)
    assert not _can_fetch(db_session, persona.id, viewer, editable=True)


def test_editor_share_grants_edit(db_session: Session) -> None:
    owner = create_test_user(db_session, "owner")
    editor = create_test_user(db_session, "editor")
    persona = create_test_persona(db_session, owner)
    share_persona_with_user(db_session, persona, editor, PersonaSharePermission.EDITOR)

    assert _can_fetch(db_session, persona.id, editor, editable=True)
    assert _can_fetch(db_session, persona.id, editor, editable=False)


def test_unrelated_user_has_no_access_to_private_persona(db_session: Session) -> None:
    owner = create_test_user(db_session, "owner")
    stranger = create_test_user(db_session, "stranger")
    persona = create_test_persona(db_session, owner)

    assert not _can_fetch(db_session, persona.id, stranger, editable=False)
    assert not _can_fetch(db_session, persona.id, stranger, editable=True)


def test_admin_always_has_edit_access(db_session: Session) -> None:
    owner = create_test_user(db_session, "owner")
    admin = create_test_user(db_session, "admin", is_admin=True)
    persona = create_test_persona(db_session, owner)
    assert _can_fetch(db_session, persona.id, admin, editable=True)


def test_public_persona_use_only_by_default(db_session: Session) -> None:
    owner = create_test_user(db_session, "owner")
    other = create_test_user(db_session, "other")
    persona = create_test_persona(db_session, owner, is_public=True)

    assert _can_fetch(db_session, persona.id, other, editable=False)
    assert not _can_fetch(db_session, persona.id, other, editable=True)


def test_public_editor_permission_grants_org_wide_edit(db_session: Session) -> None:
    owner = create_test_user(db_session, "owner")
    other = create_test_user(db_session, "other")
    persona = create_test_persona(
        db_session,
        owner,
        is_public=True,
        public_permission=PersonaSharePermission.EDITOR,
    )
    assert _can_fetch(db_session, persona.id, other, editable=True)


def test_unlisted_shared_persona_hidden_from_use_but_owner_sees(
    db_session: Session,
) -> None:
    owner = create_test_user(db_session, "owner")
    viewer = create_test_user(db_session, "viewer")
    persona = create_test_persona(db_session, owner, is_listed=False)
    share_persona_with_user(db_session, persona, viewer, PersonaSharePermission.VIEWER)

    assert not _can_fetch(db_session, persona.id, viewer, editable=False)
    assert _can_fetch(db_session, persona.id, owner, editable=False)


def test_legacy_user_ids_path_defaults_to_viewer(db_session: Session) -> None:
    """Pre-permission callers (plain user_ids) must keep today's use-only
    semantics: new rows land as VIEWER and grant no edit access."""
    owner = create_test_user(db_session, "owner")
    shared = create_test_user(db_session, "shared")
    persona = create_test_persona(db_session, owner)

    update_persona_access(
        persona_id=persona.id,
        creator_user_id=owner.id,
        db_session=db_session,
        acting_user=owner,
        user_ids=[shared.id],
    )
    db_session.commit()

    row = (
        db_session.query(Persona__User)
        .filter(
            Persona__User.persona_id == persona.id,
            Persona__User.user_id == shared.id,
        )
        .one()
    )
    assert row.permission == PersonaSharePermission.VIEWER
    assert not _can_fetch(db_session, persona.id, shared, editable=True)


def test_legacy_user_ids_path_preserves_existing_editor_level(
    db_session: Session,
) -> None:
    owner = create_test_user(db_session, "owner")
    editor = create_test_user(db_session, "editor")
    persona = create_test_persona(db_session, owner)
    share_persona_with_user(db_session, persona, editor, PersonaSharePermission.EDITOR)

    update_persona_access(
        persona_id=persona.id,
        creator_user_id=owner.id,
        db_session=db_session,
        acting_user=owner,
        user_ids=[editor.id],
    )
    db_session.commit()

    row = (
        db_session.query(Persona__User)
        .filter(
            Persona__User.persona_id == persona.id,
            Persona__User.user_id == editor.id,
        )
        .one()
    )
    assert row.permission == PersonaSharePermission.EDITOR


@pytest.mark.parametrize(
    "permission,expected_level",
    [
        (PersonaSharePermission.EDITOR, PersonaAccessLevel.EDITOR),
        (PersonaSharePermission.VIEWER, PersonaAccessLevel.VIEWER),
    ],
)
def test_access_level_for_user_shares(
    db_session: Session,
    permission: PersonaSharePermission,
    expected_level: PersonaAccessLevel,
) -> None:
    owner = create_test_user(db_session, "owner")
    shared = create_test_user(db_session, "shared")
    persona = create_test_persona(db_session, owner)
    share_persona_with_user(db_session, persona, shared, permission)
    db_session.refresh(persona)

    assert get_persona_access_level(persona, shared, set()) == expected_level
    assert get_persona_access_level(persona, owner, set()) == PersonaAccessLevel.OWNER


def test_access_level_admin_and_stranger(db_session: Session) -> None:
    owner = create_test_user(db_session, "owner")
    admin = create_test_user(db_session, "admin", is_admin=True)
    stranger = create_test_user(db_session, "stranger")
    persona = create_test_persona(db_session, owner)
    db_session.refresh(persona)

    assert get_persona_access_level(persona, admin, set()) == PersonaAccessLevel.EDITOR
    assert get_persona_access_level(persona, stranger, set()) is None


def test_sharing_status_derivation(db_session: Session) -> None:
    owner = create_test_user(db_session, "owner")
    viewer = create_test_user(db_session, "viewer")

    private_persona = create_test_persona(db_session, owner)
    assert (
        derive_persona_sharing_status(private_persona) == PersonaSharingStatus.PRIVATE
    )

    shared_persona = create_test_persona(db_session, owner)
    share_persona_with_user(
        db_session, shared_persona, viewer, PersonaSharePermission.VIEWER
    )
    db_session.refresh(shared_persona)
    assert derive_persona_sharing_status(shared_persona) == PersonaSharingStatus.SHARED

    public_persona = create_test_persona(db_session, owner, is_public=True)
    assert derive_persona_sharing_status(public_persona) == PersonaSharingStatus.PUBLIC


def _list_snapshot(db_session: Session, user: User, persona_id: int):
    snapshots = get_minimal_persona_snapshots_for_user(
        user=user, db_session=db_session, get_editable=False
    )
    return next(s for s in snapshots if s.id == persona_id)


def test_list_stamps_affordance_map_for_owner(db_session: Session) -> None:
    """The list endpoint stamps the per-agent permissions map, so a card gates its icons
    from list data instead of a per-card full-agent refetch (the flicker Nik flagged)."""
    owner = create_test_user(db_session, "list-owner")
    # delete gates on ADD_AGENTS, which EE does not grant by default.
    owner.effective_permissions = [Permission.ADD_AGENTS.value]
    db_session.commit()
    persona = create_test_persona(db_session, owner)

    snap = _list_snapshot(db_session, owner, persona.id)
    assert snap.permissions.get("edit") is True
    assert snap.permissions.get("delete") is True


def test_list_affordance_map_fail_closed_for_viewer(db_session: Session) -> None:
    """A viewer-shared user gets the map stamped but every mutating affordance false —
    the client can't render an edit/delete control the write guard would 403."""
    owner = create_test_user(db_session, "list-owner2")
    viewer = create_test_user(db_session, "list-viewer")
    persona = create_test_persona(db_session, owner)
    share_persona_with_user(db_session, persona, viewer, PersonaSharePermission.VIEWER)

    snap = _list_snapshot(db_session, viewer, persona.id)
    assert snap.permissions.get("edit") is False
    assert snap.permissions.get("delete") is False


def test_delete_persona_unowned_raises_403_not_400(db_session: Session) -> None:
    """A non-owner admitted past GATE 1 (allow_scope) must get a 403 authorization denial, not
    the generic 400 the global ValueError handler produces for get_persona_by_id's raise."""
    owner = create_test_user(db_session, "del-owner")
    stranger = create_test_user(db_session, "del-stranger")
    persona = create_test_persona(db_session, owner)

    with pytest.raises(OnyxError) as exc_info:
        delete_persona(persona_id=persona.id, user=stranger, db_session=db_session)
    assert exc_info.value.error_code == OnyxErrorCode.INSUFFICIENT_PERMISSIONS
    assert exc_info.value.status_code == 403


def test_builtin_persona_cannot_be_deleted(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Built-in agents are ownerless, so get_persona_by_id's ownership check admits
    every caller — any user who passes the delete route's ADD_AGENTS gate (auto-granted
    to all in CE, the "Create Agents" grant in EE) could tombstone the default
    assistant workspace-wide. mark_persona_as_deleted refuses built-ins for every
    caller, admins included."""
    ce_user = create_test_user(db_session, "builtin-del-ce")
    ee_user = create_test_user(db_session, "builtin-del-ee")
    # In EE "Create Agents" is a grant, not an auto-grant — model the EE caller by
    # holding only that permission.
    ee_user.effective_permissions = [Permission.ADD_AGENTS.value]
    db_session.commit()

    admin = create_test_user(db_session, "builtin-del-admin", is_admin=True)

    builtin = create_test_persona(db_session, owner=None, builtin_persona=True)
    try:
        # Pin each edition — CI runs EE-loaded, so neither auto-grant nor grant
        # applies on its own. In CE every non-anonymous user holds ADD_AGENTS via
        # CE_UNGATED_PERMISSIONS — the reported repro's caller.
        with monkeypatch.context() as m:
            m.setattr(global_version, "is_ee_version", lambda: False)
            assert has_global_permission(ce_user, Permission.ADD_AGENTS)
            assert not has_global_permission(ce_user, Permission.MANAGE_AGENTS)
            with pytest.raises(OnyxError) as exc_info:
                delete_persona(
                    persona_id=builtin.id, user=ce_user, db_session=db_session
                )
            assert exc_info.value.error_code == OnyxErrorCode.BAD_REQUEST

        with monkeypatch.context() as m:
            m.setattr(global_version, "is_ee_version", lambda: True)
            assert has_global_permission(ee_user, Permission.ADD_AGENTS)
            assert not has_global_permission(ee_user, Permission.MANAGE_AGENTS)
            with pytest.raises(OnyxError) as exc_info:
                delete_persona(
                    persona_id=builtin.id, user=ee_user, db_session=db_session
                )
            assert exc_info.value.error_code == OnyxErrorCode.BAD_REQUEST

        with pytest.raises(OnyxError) as exc_info:
            delete_persona(persona_id=builtin.id, user=admin, db_session=db_session)
        assert exc_info.value.error_code == OnyxErrorCode.BAD_REQUEST

        db_session.refresh(builtin)
        assert not builtin.deleted
    finally:
        # get_default_assistant() reads the builtin persona with one_or_none(), so a
        # stray one breaks every later test in this directory that touches it.
        db_session.delete(builtin)
        db_session.commit()


def test_add_agents_user_does_not_see_others_private_agents(
    db_session: Session,
) -> None:
    """ADD_AGENTS must not imply READ_AGENTS (see-all): the browse list shows own / shared /
    public, never another user's private agent."""
    creator = create_test_user(db_session, "add-agents-creator")
    creator.effective_permissions = [Permission.ADD_AGENTS.value]
    stranger = create_test_user(db_session, "agent-stranger")
    db_session.commit()

    own = create_test_persona(db_session, creator)
    public = create_test_persona(db_session, stranger, is_public=True)
    shared = create_test_persona(db_session, stranger)
    share_persona_with_user(db_session, shared, creator, PersonaSharePermission.VIEWER)
    others_private = create_test_persona(db_session, stranger)

    visible = {
        snap.id
        for snap in get_minimal_persona_snapshots_for_user(
            user=creator, db_session=db_session, get_editable=False
        )
    }
    assert own.id in visible
    assert public.id in visible
    assert shared.id in visible
    assert others_private.id not in visible  # ADD_AGENTS no longer grants see-all


def _edit_persona(
    db_session: Session, persona_id: int, user: User, is_public: bool
) -> None:
    """Run the update-path setter as ``user`` requesting ``is_public``."""
    upsert_persona(
        user=user,
        name=f"edit-{is_public}",
        description="",
        starter_messages=None,
        system_prompt="",
        task_prompt="",
        datetime_aware=False,
        is_public=is_public,
        db_session=db_session,
        persona_id=persona_id,
    )


def test_editor_cannot_publish_via_update(db_session: Session) -> None:
    """An EDITOR-shared user may edit the agent but not flip it public via the update path —
    is_public from a non-owner is dropped (owner-or-admin only, matching the share route)."""
    owner = create_test_user(db_session, "pub-owner")
    editor = create_test_user(db_session, "pub-editor")
    persona = create_test_persona(db_session, owner, is_public=False)
    share_persona_with_user(db_session, persona, editor, PersonaSharePermission.EDITOR)

    _edit_persona(db_session, persona.id, editor, is_public=True)
    db_session.refresh(persona)
    assert persona.is_public is False  # editor's publish attempt is dropped

    _edit_persona(db_session, persona.id, owner, is_public=True)
    db_session.refresh(persona)
    assert persona.is_public is True  # owner can publish
