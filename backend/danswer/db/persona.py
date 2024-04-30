from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from danswer.db.chat import get_prompts_by_ids
from danswer.db.chat import upsert_persona
from danswer.db.document_set import get_document_sets_by_ids
from danswer.db.models import Persona
from danswer.db.models import Persona__User
from danswer.db.models import User
from danswer.server.features.persona.models import CreatePersonaRequest
from danswer.server.features.persona.models import PersonaSnapshot
from danswer.utils.logger import setup_logger
from danswer.utils.variable_functionality import fetch_versioned_implementation

logger = setup_logger()


def make_persona_private(
    persona_id: int,
    user_ids: list[UUID] | None,
    group_ids: list[int] | None,
    db_session: Session,
) -> None:
    if user_ids is not None:
        db_session.query(Persona__User).filter(
            Persona__User.persona_id == persona_id
        ).delete(synchronize_session="fetch")

        for user_uuid in user_ids:
            db_session.add(Persona__User(persona_id=persona_id, user_id=user_uuid))

        db_session.commit()

    # May cause error if someone switches down to MIT from EE
    if group_ids:
        raise NotImplementedError("Danswer MIT does not support private Personas")


def create_update_persona(
    persona_id: int | None,
    create_persona_request: CreatePersonaRequest,
    user: User | None,
    db_session: Session,
) -> PersonaSnapshot:
    # Permission to actually use these is checked later
    document_sets = list(
        get_document_sets_by_ids(
            document_set_ids=create_persona_request.document_set_ids,
            db_session=db_session,
        )
    )
    prompts = list(
        get_prompts_by_ids(
            prompt_ids=create_persona_request.prompt_ids,
            db_session=db_session,
        )
    )

    try:
        persona = upsert_persona(
            persona_id=persona_id,
            user=user,
            name=create_persona_request.name,
            description=create_persona_request.description,
            num_chunks=create_persona_request.num_chunks,
            llm_relevance_filter=create_persona_request.llm_relevance_filter,
            llm_filter_extraction=create_persona_request.llm_filter_extraction,
            recency_bias=create_persona_request.recency_bias,
            prompts=prompts,
            document_sets=document_sets,
            llm_model_provider_override=create_persona_request.llm_model_provider_override,
            llm_model_version_override=create_persona_request.llm_model_version_override,
            starter_messages=create_persona_request.starter_messages,
            is_public=create_persona_request.is_public,
            db_session=db_session,
        )

        versioned_make_persona_private = fetch_versioned_implementation(
            "danswer.db.persona", "make_persona_private"
        )

        # Privatize Persona
        versioned_make_persona_private(
            persona_id=persona.id,
            user_ids=create_persona_request.users,
            group_ids=create_persona_request.groups,
            db_session=db_session,
        )

    except ValueError as e:
        logger.exception("Failed to create persona")
        raise HTTPException(status_code=400, detail=str(e))
    return PersonaSnapshot.from_model(persona)


def fetch_persona_by_id(db_session: Session, persona_id: int) -> Persona | None:
    return db_session.scalar(select(Persona).where(Persona.id == persona_id))
