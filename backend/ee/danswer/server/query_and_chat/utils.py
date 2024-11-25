from typing import cast

from fastapi import HTTPException
from sqlalchemy.orm import Session

from danswer.auth.users import is_user_admin
from danswer.db.llm import fetch_existing_doc_sets
from danswer.db.llm import fetch_existing_tools
from danswer.db.models import Persona
from danswer.db.models import Prompt
from danswer.db.models import Tool
from danswer.db.models import User
from danswer.db.persona import get_prompts_by_ids
from danswer.one_shot_answer.models import PersonaConfig
from danswer.tools.tool_implementations.custom.custom_tool import (
    build_custom_tools_from_openapi_schema_and_headers,
)


def create_temporary_persona(
    persona_config: PersonaConfig, db_session: Session, user: User | None = None
) -> Persona:
    if not is_user_admin(user):
        raise HTTPException(
            status_code=403,
            detail="User is not authorized to create a persona in one shot queries",
        )

    """Create a temporary Persona object from the provided configuration."""
    persona = Persona(
        name=persona_config.name,
        description=persona_config.description,
        num_chunks=persona_config.num_chunks,
        llm_relevance_filter=persona_config.llm_relevance_filter,
        llm_filter_extraction=persona_config.llm_filter_extraction,
        recency_bias=persona_config.recency_bias,
        llm_model_provider_override=persona_config.llm_model_provider_override,
        llm_model_version_override=persona_config.llm_model_version_override,
    )

    if persona_config.prompts:
        persona.prompts = [
            Prompt(
                name=p.name,
                description=p.description,
                system_prompt=p.system_prompt,
                task_prompt=p.task_prompt,
                include_citations=p.include_citations,
                datetime_aware=p.datetime_aware,
            )
            for p in persona_config.prompts
        ]
    elif persona_config.prompt_ids:
        persona.prompts = get_prompts_by_ids(
            db_session=db_session, prompt_ids=persona_config.prompt_ids
        )

    persona.tools = []
    if persona_config.custom_tools_openapi:
        for schema in persona_config.custom_tools_openapi:
            tools = cast(
                list[Tool],
                build_custom_tools_from_openapi_schema_and_headers(schema),
            )
            persona.tools.extend(tools)

    if persona_config.tools:
        tool_ids = [tool.id for tool in persona_config.tools]
        persona.tools.extend(
            fetch_existing_tools(db_session=db_session, tool_ids=tool_ids)
        )

    if persona_config.tool_ids:
        persona.tools.extend(
            fetch_existing_tools(
                db_session=db_session, tool_ids=persona_config.tool_ids
            )
        )

    fetched_docs = fetch_existing_doc_sets(
        db_session=db_session, doc_ids=persona_config.document_set_ids
    )
    persona.document_sets = fetched_docs

    return persona
