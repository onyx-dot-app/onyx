from uuid import UUID
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from onyx.db.input_prompt import fetch_input_prompts_by_user
from onyx.db.input_prompt import insert_input_prompt
from onyx.db.input_prompt import insert_input_prompt_for_persona
from onyx.db.input_prompt import sync_input_prompts_for_persona
from onyx.db.input_prompt import update_input_prompt_for_persona
from onyx.db.models import Persona
from onyx.server.features.input_prompt.models import SyncPersonaInputPromptItem
from tests.external_dependency_unit.conftest import create_test_user


def _create_persona(db_session: Session, owner_id: UUID, name: str) -> Persona:
    persona = Persona(
        id=int(uuid4().int % 1000000),
        user_id=owner_id,
        name=name,
        description=f"{name} description",
        system_prompt="",
        task_prompt="",
        datetime_aware=True,
        is_public=True,
        is_visible=True,
        featured=False,
        builtin_persona=False,
        deleted=False,
    )
    db_session.add(persona)
    db_session.commit()
    db_session.refresh(persona)
    return persona


def test_fetch_input_prompts_by_user_includes_persona_shortcuts(
    tenant_context: None,  # noqa: ARG001
    db_session: Session,
) -> None:
    user = create_test_user(db_session, "prompt_scope_user")
    persona = _create_persona(db_session, user.id, "prompt_scope_persona")

    user_prompt = insert_input_prompt(
        prompt="user_cmd",
        content="user content",
        is_public=False,
        user=user,
        persona_id=None,
        db_session=db_session,
    )
    public_prompt = insert_input_prompt(
        prompt="public_cmd",
        content="public content",
        is_public=True,
        user=None,
        persona_id=None,
        db_session=db_session,
    )
    persona_prompt = insert_input_prompt_for_persona(
        prompt="persona_cmd",
        content="persona content",
        active=True,
        persona_id=persona.id,
        user=user,
        db_session=db_session,
    )

    prompts = fetch_input_prompts_by_user(
        db_session=db_session,
        user_id=user.id,
        include_public=True,
        persona_id=persona.id,
    )
    prompt_ids = {prompt.id for prompt in prompts}

    assert user_prompt.id in prompt_ids
    assert public_prompt.id in prompt_ids
    assert persona_prompt.id in prompt_ids


def test_persona_prompt_and_public_prompt_can_share_name(
    tenant_context: None,  # noqa: ARG001
    db_session: Session,
) -> None:
    user = create_test_user(db_session, "prompt_scope_user2")
    persona = _create_persona(db_session, user.id, "prompt_scope_persona2")

    public_prompt = insert_input_prompt(
        prompt="shared_name",
        content="public content",
        is_public=True,
        user=None,
        persona_id=None,
        db_session=db_session,
    )
    persona_prompt = insert_input_prompt_for_persona(
        prompt="shared_name",
        content="persona content",
        active=True,
        persona_id=persona.id,
        user=user,
        db_session=db_session,
    )

    assert public_prompt.id is not None
    assert persona_prompt.id is not None
    assert public_prompt.id != persona_prompt.id


def test_insert_input_prompt_for_persona_enforces_unique_name_per_persona(
    tenant_context: None,  # noqa: ARG001
    db_session: Session,
) -> None:
    user = create_test_user(db_session, "prompt_scope_user3")
    persona = _create_persona(db_session, user.id, "prompt_scope_persona3")

    insert_input_prompt_for_persona(
        prompt="dupe_name",
        content="first",
        active=True,
        persona_id=persona.id,
        user=user,
        db_session=db_session,
    )

    with pytest.raises(HTTPException) as exc_info:
        insert_input_prompt_for_persona(
            prompt="dupe_name",
            content="second",
            active=True,
            persona_id=persona.id,
            user=user,
            db_session=db_session,
        )

    assert exc_info.value.status_code == 409


def test_update_input_prompt_for_persona_requires_editor_access(
    tenant_context: None,  # noqa: ARG001
    db_session: Session,
) -> None:
    owner = create_test_user(db_session, "prompt_scope_owner")
    other_user = create_test_user(db_session, "prompt_scope_other")
    persona = _create_persona(db_session, owner.id, "prompt_scope_persona4")

    prompt = insert_input_prompt_for_persona(
        prompt="editable_name",
        content="editable content",
        active=True,
        persona_id=persona.id,
        user=owner,
        db_session=db_session,
    )

    with pytest.raises(HTTPException) as exc_info:
        update_input_prompt_for_persona(
            user=other_user,
            persona_id=persona.id,
            input_prompt_id=prompt.id,
            prompt="updated_name",
            content="updated_content",
            active=True,
            db_session=db_session,
        )

    assert exc_info.value.status_code == 403


def test_sync_input_prompts_for_persona_updates_creates_and_deletes(
    tenant_context: None,  # noqa: ARG001
    db_session: Session,
) -> None:
    user = create_test_user(db_session, "prompt_scope_user4")
    persona = _create_persona(db_session, user.id, "prompt_scope_persona5")

    keep_prompt = insert_input_prompt_for_persona(
        prompt="keep_name",
        content="keep_content",
        active=True,
        persona_id=persona.id,
        user=user,
        db_session=db_session,
    )
    remove_prompt = insert_input_prompt_for_persona(
        prompt="remove_name",
        content="remove_content",
        active=True,
        persona_id=persona.id,
        user=user,
        db_session=db_session,
    )

    synced = sync_input_prompts_for_persona(
        user=user,
        persona_id=persona.id,
        prompts=[
            SyncPersonaInputPromptItem(
                id=keep_prompt.id,
                prompt="keep_name_updated",
                content="keep_content_updated",
                active=False,
            ),
            SyncPersonaInputPromptItem(
                prompt="new_name",
                content="new_content",
                active=True,
            ),
        ],
        db_session=db_session,
    )

    prompt_names = [prompt.prompt for prompt in synced]
    assert prompt_names == ["keep_name_updated", "new_name"]
    assert all(prompt.id != remove_prompt.id for prompt in synced)
    updated = next(prompt for prompt in synced if prompt.id == keep_prompt.id)
    assert updated.content == "keep_content_updated"
    assert updated.active is False


def test_sync_input_prompts_for_persona_rejects_foreign_prompt_id(
    tenant_context: None,  # noqa: ARG001
    db_session: Session,
) -> None:
    user = create_test_user(db_session, "prompt_scope_user5")
    other = create_test_user(db_session, "prompt_scope_user6")
    persona = _create_persona(db_session, user.id, "prompt_scope_persona6")
    other_persona = _create_persona(db_session, other.id, "prompt_scope_persona7")

    other_persona_prompt = insert_input_prompt_for_persona(
        prompt="foreign_name",
        content="foreign_content",
        active=True,
        persona_id=other_persona.id,
        user=other,
        db_session=db_session,
    )

    with pytest.raises(HTTPException) as exc_info:
        sync_input_prompts_for_persona(
            user=user,
            persona_id=persona.id,
            prompts=[
                SyncPersonaInputPromptItem(
                    id=other_persona_prompt.id,
                    prompt="invalid",
                    content="invalid",
                    active=True,
                )
            ],
            db_session=db_session,
        )

    assert exc_info.value.status_code == 400
