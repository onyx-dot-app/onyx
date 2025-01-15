import uuid
from uuid import UUID

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Query
from fastapi import UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from onyx.auth.users import current_admin_user
from onyx.auth.users import current_chat_accesssible_user
from onyx.auth.users import current_curator_or_admin_user
from onyx.auth.users import current_limited_user
from onyx.auth.users import current_user
from onyx.chat.prompt_builder.utils import build_dummy_prompt
from onyx.configs.constants import FileOrigin
from onyx.configs.constants import MilestoneRecordType
from onyx.configs.constants import NotificationType
from onyx.db.engine import get_current_tenant_id
from onyx.db.engine import get_session
from onyx.db.models import StarterMessageModel as StarterMessage
from onyx.db.models import User
from onyx.db.notification import create_notification
from onyx.db.persona import create_assistant_category
from onyx.db.persona import create_update_persona
from onyx.db.persona import delete_persona_category
from onyx.db.persona import get_assistant_categories
from onyx.db.persona import get_persona_by_id
from onyx.db.persona import get_personas_for_user
from onyx.db.persona import mark_persona_as_deleted
from onyx.db.persona import mark_persona_as_not_deleted
from onyx.db.persona import update_all_personas_display_priority
from onyx.db.persona import update_persona_category
from onyx.db.persona import update_persona_public_status
from onyx.db.persona import update_persona_shared_users
from onyx.db.persona import update_persona_visibility
from onyx.file_store.file_store import get_default_file_store
from onyx.file_store.models import ChatFileType
from onyx.secondary_llm_flows.starter_message_creation import (
    generate_starter_messages,
)
from onyx.server.features.persona.models import CreatePersonaRequest
from onyx.server.features.persona.models import GenerateStarterMessageRequest
from onyx.server.features.persona.models import ImageGenerationToolStatus
from onyx.server.features.persona.models import PersonaCategoryCreate
from onyx.server.features.persona.models import PersonaCategoryResponse
from onyx.server.features.persona.models import PersonaSharedNotificationData
from onyx.server.features.persona.models import PersonaSnapshot
from onyx.server.features.persona.models import PromptTemplateResponse
from onyx.server.models import DisplayPriorityRequest
from onyx.tools.utils import is_image_generation_available
from onyx.utils.logger import setup_logger
from onyx.utils.telemetry import create_milestone_and_report


logger = setup_logger()


admin_router = APIRouter(prefix="/admin/persona")
basic_router = APIRouter(prefix="/persona")


class IsVisibleRequest(BaseModel):
    is_visible: bool


class IsPublicRequest(BaseModel):
    is_public: bool


@admin_router.patch("/{persona_id}/visible")
def patch_persona_visibility(
    persona_id: int,
    is_visible_request: IsVisibleRequest,
    user: User | None = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
) -> None:
    update_persona_visibility(
        persona_id=persona_id,
        is_visible=is_visible_request.is_visible,
        db_session=db_session,
        user=user,
    )


@basic_router.patch("/{persona_id}/public")
def patch_user_presona_public_status(
    persona_id: int,
    is_public_request: IsPublicRequest,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> None:
    try:
        update_persona_public_status(
            persona_id=persona_id,
            is_public=is_public_request.is_public,
            db_session=db_session,
            user=user,
        )
    except ValueError as e:
        logger.exception("Failed to update persona public status")
        raise HTTPException(status_code=403, detail=str(e))


@admin_router.put("/display-priority")
def patch_persona_display_priority(
    display_priority_request: DisplayPriorityRequest,
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> None:
    update_all_personas_display_priority(
        display_priority_map=display_priority_request.display_priority_map,
        db_session=db_session,
    )


@admin_router.get("")
def list_personas_admin(
    user: User | None = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
    include_deleted: bool = False,
    get_editable: bool = Query(False, description="If true, return editable personas"),
) -> list[PersonaSnapshot]:
    return [
        PersonaSnapshot.from_model(persona)
        for persona in get_personas_for_user(
            db_session=db_session,
            user=user,
            get_editable=get_editable,
            include_deleted=include_deleted,
            joinedload_all=True,
        )
    ]


@admin_router.patch("/{persona_id}/undelete")
def undelete_persona(
    persona_id: int,
    user: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> None:
    mark_persona_as_not_deleted(
        persona_id=persona_id,
        user=user,
        db_session=db_session,
    )


# used for assistat profile pictures
@admin_router.post("/upload-image")
def upload_file(
    file: UploadFile,
    db_session: Session = Depends(get_session),
    _: User | None = Depends(current_user),
) -> dict[str, str]:
    file_store = get_default_file_store(db_session)
    file_type = ChatFileType.IMAGE
    file_id = str(uuid.uuid4())
    file_store.save_file(
        file_name=file_id,
        content=file.file,
        display_name=file.filename,
        file_origin=FileOrigin.CHAT_UPLOAD,
        file_type=file.content_type or file_type.value,
    )
    return {"file_id": file_id}


"""Endpoints for all"""


@basic_router.post("")
def create_persona(
    create_persona_request: CreatePersonaRequest,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
    tenant_id: str | None = Depends(get_current_tenant_id),
) -> PersonaSnapshot:
    persona_snapshot = create_update_persona(
        persona_id=None,
        create_persona_request=create_persona_request,
        user=user,
        db_session=db_session,
    )

    create_milestone_and_report(
        user=user,
        distinct_id=tenant_id or "N/A",
        event_type=MilestoneRecordType.CREATED_ASSISTANT,
        properties=None,
        db_session=db_session,
    )

    return persona_snapshot


# NOTE: This endpoint cannot update persona configuration options that
# are core to the persona, such as its display priority and
# whether or not the assistant is a built-in / default assistant
@basic_router.patch("/{persona_id}")
def update_persona(
    persona_id: int,
    update_persona_request: CreatePersonaRequest,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> PersonaSnapshot:
    return create_update_persona(
        persona_id=persona_id,
        create_persona_request=update_persona_request,
        user=user,
        db_session=db_session,
    )


class PersonaCategoryPatchRequest(BaseModel):
    category_description: str
    category_name: str


@basic_router.get("/categories")
def get_categories(
    db: Session = Depends(get_session),
    _: User | None = Depends(current_user),
) -> list[PersonaCategoryResponse]:
    return [
        PersonaCategoryResponse.from_model(category)
        for category in get_assistant_categories(db_session=db)
    ]


@admin_router.post("/categories")
def create_category(
    category: PersonaCategoryCreate,
    db: Session = Depends(get_session),
    _: User | None = Depends(current_admin_user),
) -> PersonaCategoryResponse:
    """Create a new assistant category"""
    category_model = create_assistant_category(
        name=category.name, description=category.description, db_session=db
    )
    return PersonaCategoryResponse.from_model(category_model)


@admin_router.patch("/category/{category_id}")
def patch_persona_category(
    category_id: int,
    persona_category_patch_request: PersonaCategoryPatchRequest,
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> None:
    update_persona_category(
        category_id=category_id,
        category_description=persona_category_patch_request.category_description,
        category_name=persona_category_patch_request.category_name,
        db_session=db_session,
    )


@admin_router.delete("/category/{category_id}")
def delete_category(
    category_id: int,
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> None:
    delete_persona_category(category_id=category_id, db_session=db_session)


class PersonaShareRequest(BaseModel):
    user_ids: list[UUID]


# We notify each user when a user is shared with them
@basic_router.patch("/{persona_id}/share")
def share_persona(
    persona_id: int,
    persona_share_request: PersonaShareRequest,
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> None:
    update_persona_shared_users(
        persona_id=persona_id,
        user_ids=persona_share_request.user_ids,
        user=user,
        db_session=db_session,
    )

    for user_id in persona_share_request.user_ids:
        # Don't notify the user that they have access to their own persona
        if user_id != user.id:
            create_notification(
                user_id=user_id,
                notif_type=NotificationType.PERSONA_SHARED,
                db_session=db_session,
                additional_data=PersonaSharedNotificationData(
                    persona_id=persona_id,
                ).model_dump(),
            )


@basic_router.delete("/{persona_id}")
def delete_persona(
    persona_id: int,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> None:
    mark_persona_as_deleted(
        persona_id=persona_id,
        user=user,
        db_session=db_session,
    )


@basic_router.get("/image-generation-tool")
def get_image_generation_tool(
    _: User
    | None = Depends(current_user),  # User param not used but kept for consistency
    db_session: Session = Depends(get_session),
) -> ImageGenerationToolStatus:  # Use bool instead of str for boolean values
    is_available = is_image_generation_available(db_session=db_session)
    return ImageGenerationToolStatus(is_available=is_available)


@basic_router.get("")
def list_personas(
    user: User | None = Depends(current_chat_accesssible_user),
    db_session: Session = Depends(get_session),
    include_deleted: bool = False,
    persona_ids: list[int] = Query(None),
) -> list[PersonaSnapshot]:
    personas = get_personas_for_user(
        user=user,
        include_deleted=include_deleted,
        db_session=db_session,
        get_editable=False,
        joinedload_all=True,
    )

    if persona_ids:
        personas = [p for p in personas if p.id in persona_ids]

    # Filter out personas with unavailable tools
    personas = [
        p
        for p in personas
        if not (
            any(tool.in_code_tool_id == "ImageGenerationTool" for tool in p.tools)
            and not is_image_generation_available(db_session=db_session)
        )
    ]

    return [PersonaSnapshot.from_model(p) for p in personas]


@basic_router.get("/{persona_id}")
def get_persona(
    persona_id: int,
    user: User | None = Depends(current_limited_user),
    db_session: Session = Depends(get_session),
) -> PersonaSnapshot:
    return PersonaSnapshot.from_model(
        get_persona_by_id(
            persona_id=persona_id,
            user=user,
            db_session=db_session,
            is_for_edit=False,
        )
    )


@basic_router.get("/utils/prompt-explorer")
def build_final_template_prompt(
    system_prompt: str,
    task_prompt: str,
    retrieval_disabled: bool = False,
    _: User | None = Depends(current_user),
) -> PromptTemplateResponse:
    return PromptTemplateResponse(
        final_prompt_template=build_dummy_prompt(
            system_prompt=system_prompt,
            task_prompt=task_prompt,
            retrieval_disabled=retrieval_disabled,
        )
    )


@basic_router.post("/assistant-prompt-refresh")
def build_assistant_prompts(
    generate_persona_prompt_request: GenerateStarterMessageRequest,
    db_session: Session = Depends(get_session),
    user: User | None = Depends(current_user),
) -> list[StarterMessage]:
    try:
        logger.info(
            "Generating starter messages for user: %s", user.id if user else "Anonymous"
        )
        return generate_starter_messages(
            name=generate_persona_prompt_request.name,
            description=generate_persona_prompt_request.description,
            instructions=generate_persona_prompt_request.instructions,
            document_set_ids=generate_persona_prompt_request.document_set_ids,
            db_session=db_session,
            user=user,
        )
    except Exception as e:
        logger.exception("Failed to generate starter messages")
        raise HTTPException(status_code=500, detail=str(e))
