from typing import Any
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from onyx.auth.users import current_user
from onyx.context.search.enums import RecencyBiasSetting
from onyx.db.engine.sql_engine import get_session
from onyx.db.models import Persona
from onyx.db.models import User
from onyx.db.persona import get_persona_by_id
from onyx.db.persona import get_raw_personas_for_user
from onyx.db.persona import mark_persona_as_deleted
from onyx.db.persona import upsert_persona
from onyx.db.tools import get_tool_by_name
from onyx.utils.logger import setup_logger

logger = setup_logger()


router = APIRouter(prefix="/assistants")


# Base models
class AssistantObject(BaseModel):
    id: int
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
    id: int
    object: str = "assistant.deleted"
    deleted: bool


class ListAssistantsResponse(BaseModel):
    object: str = "list"
    data: list[AssistantObject]
    first_id: Optional[int] = None
    last_id: Optional[int] = None
    has_more: bool


def persona_to_assistant(persona: Persona) -> AssistantObject:
    return AssistantObject(
        id=persona.id,
        created_at=0,
        name=persona.name,
        description=persona.description,
        model=persona.llm_model_version_override or "gpt-3.5-turbo",
        instructions=persona.system_prompt,
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
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> AssistantObject:
    # No separate Prompt entity; instructions map to persona.system_prompt

    tool_ids = []
    for tool in request.tools or []:
        tool_type = tool.get("type")
        if not tool_type:
            continue

        try:
            tool_db = get_tool_by_name(tool_type, db_session)
            tool_ids.append(tool_db.id)
        except ValueError:
            # Skip tools that don't exist in the database
            logger.error(f"Tool {tool_type} not found in database")
            raise HTTPException(
                status_code=404, detail=f"Tool {tool_type} not found in database"
            )

    persona = upsert_persona(
        user=user,
        name=request.name or f"Assistant-{uuid4()}",
        description=request.description or "",
        num_chunks=25,
        llm_relevance_filter=True,
        llm_filter_extraction=True,
        recency_bias=RecencyBiasSetting.AUTO,
        llm_model_provider_override=None,
        llm_model_version_override=request.model,
        starter_messages=None,
        is_public=False,
        db_session=db_session,
        document_set_ids=[],
        tool_ids=tool_ids,
        icon_color=None,
        icon_shape=None,
        is_visible=True,
        system_prompt=request.instructions or "",
        task_prompt="",
        datetime_aware=True,
    )
    return persona_to_assistant(persona)


@router.get("/{assistant_id}")
def retrieve_assistant(
    assistant_id: int,
    user: User | None = Depends(current_user),
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
    user: User | None = Depends(current_user),
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

    if "instructions" in update_data:
        persona.system_prompt = update_data["instructions"]

    db_session.commit()
    return persona_to_assistant(persona)


@router.delete("/{assistant_id}")
def delete_assistant(
    assistant_id: int,
    user: User | None = Depends(current_user),
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
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> ListAssistantsResponse:
    persona_snapshots = list(
        get_raw_personas_for_user(
            user=user,
            db_session=db_session,
            get_editable=False,
        )
    )

    # Apply filtering based on after and before
    if after:
        persona_snapshots = [p for p in persona_snapshots if p.id > int(after)]
    if before:
        persona_snapshots = [p for p in persona_snapshots if p.id < int(before)]

    # Apply ordering
    persona_snapshots.sort(key=lambda p: p.id, reverse=(order == "desc"))

    # Apply limit
    persona_snapshots = persona_snapshots[:limit]

    assistants = [persona_to_assistant(p) for p in persona_snapshots]

    return ListAssistantsResponse(
        data=assistants,
        first_id=assistants[0].id if assistants else None,
        last_id=assistants[-1].id if assistants else None,
        has_more=len(persona_snapshots) == limit,
    )
