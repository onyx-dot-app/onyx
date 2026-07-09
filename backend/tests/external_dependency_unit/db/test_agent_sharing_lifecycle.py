"""Regression coverage for the persona ownership lifecycle: user deletion
soft-deletes private personas and orphans shared/public ones, deactivation
mutates nothing (vacancy is computed), and self-removal from the share list
works for everyone except the owner."""

import pytest
from sqlalchemy.orm import Session

from onyx.db.enums import PersonaSharePermission
from onyx.db.models import Persona
from onyx.db.persona import remove_user_from_persona_shares
from onyx.db.persona import update_persona_shared
from onyx.db.persona_sharing import persona_ownership_is_vacant
from onyx.db.users import delete_user_from_db
from tests.external_dependency_unit.conftest import create_test_user
from tests.external_dependency_unit.db.agent_sharing_helpers import create_test_persona
from tests.external_dependency_unit.db.agent_sharing_helpers import (
    share_persona_with_user,
)


def test_user_deletion_soft_deletes_private_and_orphans_shared(
    db_session: Session,
) -> None:
    owner = create_test_user(db_session, "owner")
    viewer = create_test_user(db_session, "viewer")
    private_persona = create_test_persona(db_session, owner)
    shared_persona = create_test_persona(db_session, owner)
    public_persona = create_test_persona(db_session, owner, is_public=True)
    share_persona_with_user(
        db_session, shared_persona, viewer, PersonaSharePermission.VIEWER
    )

    delete_user_from_db(owner, db_session)

    private_after = db_session.get(Persona, private_persona.id)
    shared_after = db_session.get(Persona, shared_persona.id)
    public_after = db_session.get(Persona, public_persona.id)
    assert private_after is not None and private_after.deleted
    assert shared_after is not None and not shared_after.deleted
    assert shared_after.user_id is None
    assert public_after is not None and not public_after.deleted
    assert public_after.user_id is None
    # Orphaned personas are admin-manageable
    assert persona_ownership_is_vacant(shared_after)


def test_deactivation_mutates_nothing(db_session: Session) -> None:
    owner = create_test_user(db_session, "owner")
    viewer = create_test_user(db_session, "viewer")
    persona = create_test_persona(db_session, owner)
    share_persona_with_user(db_session, persona, viewer, PersonaSharePermission.VIEWER)

    owner.is_active = False
    db_session.commit()
    db_session.refresh(persona)

    # Owner reference preserved (reversible on reactivation), but the persona
    # now reads as vacant so admins can transfer it away
    assert persona.user_id == owner.id
    assert not persona.deleted
    assert persona_ownership_is_vacant(persona)

    owner.is_active = True
    db_session.commit()
    db_session.refresh(persona)
    assert not persona_ownership_is_vacant(persona)


def test_self_removal_for_shared_user(db_session: Session) -> None:
    owner = create_test_user(db_session, "owner")
    viewer = create_test_user(db_session, "viewer")
    persona = create_test_persona(db_session, owner)
    share_persona_with_user(db_session, persona, viewer, PersonaSharePermission.VIEWER)

    remove_user_from_persona_shares(
        persona_id=persona.id, user=viewer, db_session=db_session
    )
    db_session.refresh(persona)
    assert all(share.user_id != viewer.id for share in persona.user_shares)


def test_owner_cannot_self_remove(db_session: Session) -> None:
    owner = create_test_user(db_session, "owner")
    persona = create_test_persona(db_session, owner)

    with pytest.raises(ValueError):
        remove_user_from_persona_shares(
            persona_id=persona.id, user=owner, db_session=db_session
        )


def test_self_removal_without_share_row_errors(db_session: Session) -> None:
    owner = create_test_user(db_session, "owner")
    stranger = create_test_user(db_session, "stranger")
    persona = create_test_persona(db_session, owner)

    with pytest.raises(ValueError):
        remove_user_from_persona_shares(
            persona_id=persona.id, user=stranger, db_session=db_session
        )


def test_share_update_filters_owner_silently(db_session: Session) -> None:
    """A stale dialog may include the (new) owner in its share list; the save
    must succeed with the owner dropped rather than erroring."""
    owner = create_test_user(db_session, "owner")
    editor = create_test_user(db_session, "editor")
    persona = create_test_persona(db_session, owner)
    share_persona_with_user(db_session, persona, editor, PersonaSharePermission.EDITOR)

    update_persona_shared(
        persona_id=persona.id,
        user=editor,
        db_session=db_session,
        user_ids=None,
        user_shares={
            owner.id: PersonaSharePermission.EDITOR,
            editor.id: PersonaSharePermission.EDITOR,
        },
    )
    db_session.refresh(persona)
    assert all(share.user_id != owner.id for share in persona.user_shares)
    assert any(share.user_id == editor.id for share in persona.user_shares)


def test_share_update_denied_for_viewer(db_session: Session) -> None:
    from fastapi import HTTPException

    owner = create_test_user(db_session, "owner")
    viewer = create_test_user(db_session, "viewer")
    other = create_test_user(db_session, "other")
    persona = create_test_persona(db_session, owner)
    share_persona_with_user(db_session, persona, viewer, PersonaSharePermission.VIEWER)

    with pytest.raises(HTTPException):
        update_persona_shared(
            persona_id=persona.id,
            user=viewer,
            db_session=db_session,
            user_ids=None,
            user_shares={other.id: PersonaSharePermission.VIEWER},
        )


def test_share_update_allowed_for_editor_and_preserves_flags(
    db_session: Session,
) -> None:
    """Editors can manage sharing; doing so must not touch is_featured or
    is_listed (ENG-4179)."""
    owner = create_test_user(db_session, "owner")
    editor = create_test_user(db_session, "editor")
    new_viewer = create_test_user(db_session, "newviewer")
    persona = create_test_persona(db_session, owner, is_listed=False)
    persona.is_featured = True
    db_session.commit()
    share_persona_with_user(db_session, persona, editor, PersonaSharePermission.EDITOR)

    update_persona_shared(
        persona_id=persona.id,
        user=editor,
        db_session=db_session,
        user_ids=None,
        user_shares={
            editor.id: PersonaSharePermission.EDITOR,
            new_viewer.id: PersonaSharePermission.VIEWER,
        },
    )
    db_session.refresh(persona)
    assert persona.is_featured
    assert not persona.is_listed
    assert any(share.user_id == new_viewer.id for share in persona.user_shares)


def test_editor_cannot_flip_public_visibility(db_session: Session) -> None:
    """EDITOR-level sharees may edit shares but not make a private agent
    public; only the owner/admin can flip org-wide visibility."""
    owner = create_test_user(db_session, "owner")
    editor = create_test_user(db_session, "editor")
    persona = create_test_persona(db_session, owner)
    share_persona_with_user(db_session, persona, editor, PersonaSharePermission.EDITOR)
    assert not persona.is_public

    # Editor's attempt to go public is ignored.
    update_persona_shared(
        persona_id=persona.id,
        user=editor,
        db_session=db_session,
        user_ids=None,
        is_public=True,
        public_permission=PersonaSharePermission.EDITOR,
    )
    db_session.refresh(persona)
    assert not persona.is_public

    # Owner can still flip it.
    update_persona_shared(
        persona_id=persona.id,
        user=owner,
        db_session=db_session,
        user_ids=None,
        is_public=True,
    )
    db_session.refresh(persona)
    assert persona.is_public
