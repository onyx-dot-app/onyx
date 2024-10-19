from typing import Any
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from danswer.db.engine import get_session
from danswer.db.models import Persona
from danswer.db.models import User
from danswer.db.persona import get_persona_by_id
from danswer.db.persona import get_personas
from danswer.db.persona import mark_persona_as_deleted
from danswer.db.persona import upsert_persona
from danswer.db.persona import upsert_prompt
from danswer.server.danswer_api.ingestion import api_key_dep

router = APIRouter(prefix="/assistants")


# Base models
class AssistantObject(BaseModel):
    id: str
    object: str = "assistant"
    created_at: int
    name: Optional[str] = None
    description: Optional[str] = None
    model: str
    instructions: Optional[str] = None
    tools: list[dict[str, Any]]
    file_ids: list[str]
    metadata: Optional[dict[str, Any]] = None


class CreateAssistantRequest(BaseModel):
    model: str
    name: Optional[str] = None
    description: Optional[str] = None
    instructions: Optional[str] = None
    tools: Optional[list[dict[str, Any]]] = None
    file_ids: Optional[list[str]] = None
    metadata: Optional[dict[str, Any]] = None


class ModifyAssistantRequest(BaseModel):
    model: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    instructions: Optional[str] = None
    tools: Optional[list[dict[str, Any]]] = None
    file_ids: Optional[list[str]] = None
    metadata: Optional[dict[str, Any]] = None


class DeleteAssistantResponse(BaseModel):
    id: str
    object: str = "assistant.deleted"
    deleted: bool


class ListAssistantsResponse(BaseModel):
    object: str = "list"
    data: list[AssistantObject]
    first_id: Optional[str] = None
    last_id: Optional[str] = None
    has_more: bool


def persona_to_assistant(persona: Persona) -> AssistantObject:
    return AssistantObject(
        id=str(persona.id),
        created_at=0,
        name=persona.name,
        description=persona.description,
        model=persona.llm_model_version_override or "gpt-3.5-turbo",
        instructions=persona.prompts[0].system_prompt if persona.prompts else None,
        tools=[
            {
                "type": tool.display_name,
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "schema": tool.openapi_schema,
                },
            }
            for tool in persona.tools
        ],
        file_ids=[],  # Assuming no file support for now
        metadata={},  # Assuming no metadata for now
    )


# API endpoints
@router.post("")
def create_assistant(
    request: CreateAssistantRequest,
    user: User | None = Depends(api_key_dep),
    db_session: Session = Depends(get_session),
) -> AssistantObject:
    prompt = None
    if request.instructions:
        prompt = upsert_prompt(
            user=user,
            name=f"Prompt for {request.name or 'New Assistant'}",
            description="Auto-generated prompt",
            system_prompt=request.instructions,
            task_prompt="",
            include_citations=True,
            datetime_aware=True,
            personas=[],
            db_session=db_session,
        )

    persona = upsert_persona(
        user=user,
        name=request.name or f"Assistant-{uuid4()}",
        description=request.description or "",
        num_chunks=10,  # Default value
        llm_relevance_filter=True,
        llm_filter_extraction=True,
        recency_bias="auto",
        llm_model_provider_override=None,
        llm_model_version_override=request.model,
        starter_messages=None,
        is_public=False,
        db_session=db_session,
        prompt_ids=[prompt.id] if prompt else [0],
        document_set_ids=[],
        tool_ids=[],  # TODO: Convert OpenAI tools to Danswer tools
        icon_color=None,
        icon_shape=None,
        is_visible=True,
    )

    if prompt:
        prompt.personas = [persona]
        db_session.commit()

    return persona_to_assistant(persona)


@router.get("/{assistant_id}")
def retrieve_assistant(
    assistant_id: int,
    user: User | None = Depends(api_key_dep),
    db_session: Session = Depends(get_session),
) -> AssistantObject:
    try:
        persona = get_persona_by_id(
            persona_id=assistant_id,
            user=user,
            db_session=db_session,
            is_for_edit=False,
        )
    except ValueError:
        persona = None

    if not persona:
        raise HTTPException(status_code=404, detail="Assistant not found")
    return persona_to_assistant(persona)


@router.post("/{assistant_id}")
def modify_assistant(
    assistant_id: int,
    request: ModifyAssistantRequest,
    user: User | None = Depends(api_key_dep),
    db_session: Session = Depends(get_session),
) -> AssistantObject:
    persona = get_persona_by_id(
        persona_id=assistant_id,
        user=user,
        db_session=db_session,
        is_for_edit=True,
    )
    if not persona:
        raise HTTPException(status_code=404, detail="Assistant not found")

    update_data = request.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(persona, key, value)

    if "instructions" in update_data and persona.prompts:
        persona.prompts[0].system_prompt = update_data["instructions"]

    db_session.commit()
    return persona_to_assistant(persona)


@router.delete("/{assistant_id}")
def delete_assistant(
    assistant_id: str,
    user: User | None = Depends(api_key_dep),
    db_session: Session = Depends(get_session),
) -> DeleteAssistantResponse:
    try:
        mark_persona_as_deleted(
            persona_id=int(assistant_id),
            user=user,
            db_session=db_session,
        )
        return DeleteAssistantResponse(id=assistant_id, deleted=True)
    except ValueError:
        raise HTTPException(status_code=404, detail="Assistant not found")


@router.get("")
def list_assistants(
    limit: int = Query(20, le=100),
    order: str = Query("desc", regex="^(asc|desc)$"),
    after: Optional[int] = None,
    before: Optional[int] = None,
    user: User | None = Depends(api_key_dep),
    db_session: Session = Depends(get_session),
) -> ListAssistantsResponse:
    personas = get_personas(
        user=user,
        db_session=db_session,
        get_editable=False,
        joinedload_all=True,
    )

    # Apply filtering based on after and before
    if after:
        personas = [p for p in personas if p.id > int(after)]
    if before:
        personas = [p for p in personas if p.id < int(before)]

    # Apply ordering
    personas.sort(key=lambda p: p.id, reverse=(order == "desc"))

    # Apply limit
    personas = personas[:limit]

    assistants = [persona_to_assistant(p) for p in personas]

    return ListAssistantsResponse(
        data=assistants,
        first_id=str(assistants[0].id) if assistants else None,
        last_id=str(assistants[-1].id) if assistants else None,
        has_more=len(personas) == limit,
    )
