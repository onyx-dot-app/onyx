import uuid
from uuid import UUID

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Query
from fastapi import UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from danswer.auth.users import current_admin_user
from danswer.auth.users import current_curator_or_admin_user
from danswer.auth.users import current_user
from danswer.configs.constants import FileOrigin
from danswer.configs.constants import NotificationType
from danswer.db.engine import get_session
from danswer.db.models import User
from danswer.db.notification import create_notification
from danswer.db.persona import create_update_persona
from danswer.db.persona import get_persona_by_id
from danswer.db.persona import get_personas
from danswer.db.persona import mark_persona_as_deleted
from danswer.db.persona import mark_persona_as_not_deleted
from danswer.db.persona import update_all_personas_display_priority
from danswer.db.persona import update_persona_public_status
from danswer.db.persona import update_persona_shared_users
from danswer.db.persona import update_persona_visibility
from danswer.file_store.file_store import get_default_file_store
from danswer.file_store.models import ChatFileType
from danswer.llm.answering.prompts.utils import build_dummy_prompt
from danswer.server.features.persona.models import CreatePersonaRequest
from danswer.server.features.persona.models import ImageGenerationToolStatus
from danswer.server.features.persona.models import PersonaSharedNotificationData
from danswer.server.features.persona.models import PersonaSnapshot
from danswer.server.features.persona.models import PromptTemplateResponse
from danswer.server.models import DisplayPriorityRequest
from danswer.tools.utils import is_image_generation_available
from danswer.utils.logger import setup_logger

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
        for persona in get_personas(
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
) -> PersonaSnapshot:
    return create_update_persona(
        persona_id=None,
        create_persona_request=create_persona_request,
        user=user,
        db_session=db_session,
    )


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
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
    include_deleted: bool = False,
    persona_ids: list[int] = Query(None),
) -> list[PersonaSnapshot]:
    personas = get_personas(
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
    user: User | None = Depends(current_user),
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
