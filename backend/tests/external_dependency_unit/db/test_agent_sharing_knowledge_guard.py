"""Regression coverage for the editor knowledge-attach guard (ENG-4180): a
non-owner editor may only ATTACH document sets they can access; pre-existing
attachments survive updates, and a removed inaccessible set cannot be re-added
by that editor."""

from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.auth.schemas import UserRole
from onyx.db.enums import PersonaSharePermission
from onyx.db.models import DocumentSet
from onyx.db.models import Persona
from onyx.db.models import User
from onyx.db.persona import upsert_persona
from tests.external_dependency_unit.conftest import create_test_user
from tests.external_dependency_unit.db.agent_sharing_helpers import create_test_persona
from tests.external_dependency_unit.db.agent_sharing_helpers import (
    share_persona_with_user,
)


def _create_persona_with_editor(
    db_session: Session, owner: User, editor: User
) -> Persona:
    persona = create_test_persona(db_session, owner)
    share_persona_with_user(db_session, persona, editor, PersonaSharePermission.EDITOR)
    return persona


def _create_document_set(
    db_session: Session, owner: User, is_public: bool
) -> DocumentSet:
    document_set = DocumentSet(
        name=f"agent-sharing-ds-{uuid4().hex[:8]}",
        description="knowledge guard test set",
        user_id=owner.id,
        is_public=is_public,
        is_up_to_date=True,
    )
    db_session.add(document_set)
    db_session.commit()
    db_session.refresh(document_set)
    return document_set


def _update_persona_document_sets(
    db_session: Session, persona: Persona, user: User, document_set_ids: list[int]
) -> Persona:
    return upsert_persona(
        persona_id=persona.id,
        user=user,
        name=persona.name,
        description=persona.description,
        starter_messages=None,
        system_prompt=None,
        task_prompt=None,
        datetime_aware=None,
        is_public=persona.is_public,
        db_session=db_session,
        document_set_ids=document_set_ids,
    )


def test_editor_cannot_attach_inaccessible_document_set(db_session: Session) -> None:
    owner = create_test_user(db_session, "owner")
    editor = create_test_user(db_session, "editor")
    private_set = _create_document_set(db_session, owner, is_public=False)
    persona = _create_persona_with_editor(db_session, owner, editor)

    with pytest.raises(ValueError, match="document sets"):
        _update_persona_document_sets(db_session, persona, editor, [private_set.id])


def test_editor_can_attach_accessible_document_set(db_session: Session) -> None:
    owner = create_test_user(db_session, "owner")
    editor = create_test_user(db_session, "editor")
    public_set = _create_document_set(db_session, owner, is_public=True)
    persona = _create_persona_with_editor(db_session, owner, editor)

    updated = _update_persona_document_sets(
        db_session, persona, editor, [public_set.id]
    )
    db_session.commit()
    assert {ds.id for ds in updated.document_sets} == {public_set.id}


def test_editor_keeps_existing_inaccessible_set(db_session: Session) -> None:
    owner = create_test_user(db_session, "owner")
    editor = create_test_user(db_session, "editor")
    private_set = _create_document_set(db_session, owner, is_public=False)
    public_set = _create_document_set(db_session, owner, is_public=True)
    persona = _create_persona_with_editor(db_session, owner, editor)
    persona.document_sets = [private_set]
    db_session.commit()

    updated = _update_persona_document_sets(
        db_session, persona, editor, [private_set.id, public_set.id]
    )
    db_session.commit()
    assert {ds.id for ds in updated.document_sets} == {private_set.id, public_set.id}


def test_editor_cannot_readd_removed_inaccessible_set(db_session: Session) -> None:
    owner = create_test_user(db_session, "owner")
    editor = create_test_user(db_session, "editor")
    private_set = _create_document_set(db_session, owner, is_public=False)
    persona = _create_persona_with_editor(db_session, owner, editor)
    persona.document_sets = [private_set]
    db_session.commit()

    _update_persona_document_sets(db_session, persona, editor, [])
    db_session.commit()

    with pytest.raises(ValueError, match="document sets"):
        _update_persona_document_sets(db_session, persona, editor, [private_set.id])


def test_admin_bypasses_knowledge_guard(db_session: Session) -> None:
    owner = create_test_user(db_session, "owner")
    admin = create_test_user(db_session, "admin", role=UserRole.ADMIN)
    private_set = _create_document_set(db_session, owner, is_public=False)
    persona = create_test_persona(db_session, owner)

    updated = _update_persona_document_sets(
        db_session, persona, admin, [private_set.id]
    )
    db_session.commit()
    assert {ds.id for ds in updated.document_sets} == {private_set.id}
