from uuid import UUID
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from onyx.db.input_prompt import insert_input_prompt
from onyx.db.input_prompt import insert_input_prompt_for_persona
from onyx.db.models import Persona
from onyx.server.features.input_prompt.api import list_input_prompts
from onyx.server.features.input_prompt.models import SyncPersonaInputPromptItem
from onyx.server.features.input_prompt.models import SyncPersonaInputPromptsRequest
from onyx.server.features.persona.api import sync_persona_input_prompts
from tests.external_dependency_unit.conftest import create_test_user


def _create_persona(
    db_session: Session, owner_id: UUID, name: str, is_public: bool
) -> Persona:
    persona = Persona(
        id=int(uuid4().int % 1000000),
        user_id=owner_id,
        name=name,
        description=f"{name} description",
        system_prompt="",
        task_prompt="",
        datetime_aware=True,
        is_public=is_public,
        is_visible=True,
        featured=False,
        builtin_persona=False,
        deleted=False,
    )
    db_session.add(persona)
    db_session.commit()
    db_session.refresh(persona)
    return persona


def test_list_input_prompts_with_persona_id_returns_composed_results(
    tenant_context: None,  # noqa: ARG001
    db_session: Session,
) -> None:
    user = create_test_user(db_session, "persona_prompt_api_user")
    persona = _create_persona(
        db_session=db_session,
        owner_id=user.id,
        name="persona_prompt_api_assistant",
        is_public=True,
    )

    user_prompt = insert_input_prompt(
        prompt="api_user",
        content="api user content",
        is_public=False,
        user=user,
        persona_id=None,
        db_session=db_session,
    )
    public_prompt = insert_input_prompt(
        prompt="api_public",
        content="api public content",
        is_public=True,
        user=None,
        persona_id=None,
        db_session=db_session,
    )
    persona_prompt = insert_input_prompt_for_persona(
        prompt="api_persona",
        content="api persona content",
        active=True,
        persona_id=persona.id,
        user=user,
        db_session=db_session,
    )

    prompts = list_input_prompts(
        user=user,
        include_public=True,
        persona_id=persona.id,
        db_session=db_session,
    )
    prompt_ids = {prompt.id for prompt in prompts}

    assert user_prompt.id in prompt_ids
    assert public_prompt.id in prompt_ids
    assert persona_prompt.id in prompt_ids


def test_list_input_prompts_with_inaccessible_persona_raises_403(
    tenant_context: None,  # noqa: ARG001
    db_session: Session,
) -> None:
    owner = create_test_user(db_session, "persona_prompt_api_owner")
    other = create_test_user(db_session, "persona_prompt_api_other")
    private_persona = _create_persona(
        db_session=db_session,
        owner_id=owner.id,
        name="persona_prompt_private_assistant",
        is_public=False,
    )

    with pytest.raises(HTTPException) as exc_info:
        list_input_prompts(
            user=other,
            include_public=True,
            persona_id=private_persona.id,
            db_session=db_session,
        )

    assert exc_info.value.status_code == 403


def test_sync_persona_input_prompts_requires_editor_access(
    tenant_context: None,  # noqa: ARG001
    db_session: Session,
) -> None:
    owner = create_test_user(db_session, "persona_prompt_sync_owner")
    other = create_test_user(db_session, "persona_prompt_sync_other")
    persona = _create_persona(
        db_session=db_session,
        owner_id=owner.id,
        name="persona_prompt_sync_assistant",
        is_public=True,
    )

    with pytest.raises(HTTPException) as exc_info:
        sync_persona_input_prompts(
            persona_id=persona.id,
            request=SyncPersonaInputPromptsRequest(
                prompts=[
                    SyncPersonaInputPromptItem(
                        prompt="new_sync_prompt",
                        content="new_sync_content",
                        active=True,
                    )
                ]
            ),
            user=other,
            db_session=db_session,
        )

    assert exc_info.value.status_code == 403
