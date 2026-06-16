"""Regression coverage for the persona share-permission predicate: EDITOR
shares grant edit access, VIEWER shares grant use only, public_permission can
extend edit org-wide, and the computed access level / sharing status helpers
agree with the SQL filter."""

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from onyx.auth.schemas import UserRole
from onyx.db.enums import PersonaAccessLevel
from onyx.db.enums import PersonaSharePermission
from onyx.db.enums import PersonaSharingStatus
from onyx.db.models import Persona__User
from onyx.db.models import User
from onyx.db.persona import fetch_persona_by_id_for_user
from onyx.db.persona import update_persona_access
from onyx.db.persona_sharing import derive_persona_sharing_status
from onyx.db.persona_sharing import get_persona_access_level
from tests.external_dependency_unit.conftest import create_test_user
from tests.external_dependency_unit.db.agent_sharing_helpers import create_test_persona
from tests.external_dependency_unit.db.agent_sharing_helpers import (
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
    admin = create_test_user(db_session, "admin", role=UserRole.ADMIN)
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
    admin = create_test_user(db_session, "admin", role=UserRole.ADMIN)
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
