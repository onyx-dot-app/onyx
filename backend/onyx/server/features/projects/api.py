import json
from uuid import UUID

from fastapi import APIRouter
from fastapi import Depends
from fastapi import File
from fastapi import Form
from fastapi import HTTPException
from fastapi import Response
from fastapi import UploadFile
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from onyx.auth.users import current_user
from onyx.background.celery.versioned_apps.client import app as client_app
from onyx.configs.constants import OnyxCeleryPriority
from onyx.configs.constants import OnyxCeleryQueues
from onyx.configs.constants import OnyxCeleryTask
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import UserFileStatus
from onyx.db.models import ChatSession
from onyx.db.models import User
from onyx.db.models import UserFile
from onyx.db.models import UserProject
from onyx.db.persona import get_personas_by_ids
from onyx.db.projects import upload_files_to_user_files_with_indexing
from onyx.server.features.projects.models import CategorizedFilesSnapshot
from onyx.server.features.projects.models import ChatSessionRequest
from onyx.server.features.projects.models import TokenCountResponse
from onyx.server.features.projects.models import UserFileSnapshot
from onyx.server.features.projects.models import UserProjectSnapshot
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()


router = APIRouter(prefix="/user/projects")


class UserFileDeleteResult(BaseModel):
    has_associations: bool
    project_names: list[str] = []
    assistant_names: list[str] = []


@router.get("/")
def get_projects(
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> list[UserProjectSnapshot]:
    user_id = user.id if user is not None else None
    projects = (
        db_session.query(UserProject).filter(UserProject.user_id == user_id).all()
    )
    return [UserProjectSnapshot.from_model(project) for project in projects]


@router.post("/create")
def create_project(
    name: str,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> UserProjectSnapshot:
    if name == "":
        raise HTTPException(status_code=400, detail="Project name cannot be empty")
    user_id = user.id if user is not None else None
    project = UserProject(name=name, user_id=user_id)
    db_session.add(project)
    db_session.commit()
    return UserProjectSnapshot.from_model(project)


@router.post("/file/upload")
def upload_user_files(
    files: list[UploadFile] = File(...),
    project_id: int | None = Form(None),
    temp_id_map: str | None = Form(None),  # JSON string mapping hashed key -> temp_id
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> CategorizedFilesSnapshot:
    try:
        parsed_temp_id_map: dict[str, str] | None = None
        if temp_id_map:
            try:
                parsed = json.loads(temp_id_map)
                if isinstance(parsed, dict):
                    # Ensure all keys/values are strings
                    parsed_temp_id_map = {str(k): str(v) for k, v in parsed.items()}
                else:
                    parsed_temp_id_map = None
            except json.JSONDecodeError:
                parsed_temp_id_map = None

        # Use our consolidated function that handles indexing properly
        categorized_files_result = upload_files_to_user_files_with_indexing(
            files=files,
            project_id=project_id,
            user=user,
            temp_id_map=parsed_temp_id_map,
            db_session=db_session,
        )

        return CategorizedFilesSnapshot.from_result(categorized_files_result)

    except Exception as e:
        # Log error with type, message, and stack for easier debugging
        logger.exception(f"Error uploading files - {type(e).__name__}: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="Failed to upload files. Please try again or contact support if the issue persists.",
        )


@router.get("/{project_id}")
def get_project(
    project_id: int,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> UserProjectSnapshot:
    user_id = user.id if user is not None else None
    project = (
        db_session.query(UserProject)
        .filter(UserProject.id == project_id, UserProject.user_id == user_id)
        .one_or_none()
    )
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return UserProjectSnapshot.from_model(project)


@router.get("/files/{project_id}")
def get_files_in_project(
    project_id: int,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> list[UserFileSnapshot]:
    user_id = user.id if user is not None else None
    user_files = (
        db_session.query(UserFile)
        .filter(UserFile.projects.any(id=project_id), UserFile.user_id == user_id)
        .filter(UserFile.status != UserFileStatus.FAILED)
        .order_by(UserFile.created_at.desc())
        .all()
    )
    return [UserFileSnapshot.from_model(user_file) for user_file in user_files]


@router.delete("/{project_id}/files/{file_id}")
def unlink_user_file_from_project(
    project_id: int,
    file_id: UUID,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> Response:
    """Unlink an existing user file from a specific project for the current user.

    Does not delete the underlying file; only removes the association.
    """
    user_id = user.id if user is not None else None
    project = (
        db_session.query(UserProject)
        .filter(UserProject.id == project_id, UserProject.user_id == user_id)
        .one_or_none()
    )
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    user_id = user.id if user is not None else None
    user_file = (
        db_session.query(UserFile)
        .filter(UserFile.id == file_id, UserFile.user_id == user_id)
        .one_or_none()
    )
    if user_file is None:
        raise HTTPException(status_code=404, detail="File not found")

    # Remove the association if it exists
    if user_file in project.user_files:
        project.user_files.remove(user_file)
        user_file.needs_project_sync = True
        db_session.commit()

    tenant_id = get_current_tenant_id()
    task = client_app.send_task(
        OnyxCeleryTask.PROCESS_SINGLE_USER_FILE_PROJECT_SYNC,
        kwargs={"user_file_id": user_file.id, "tenant_id": tenant_id},
        queue=OnyxCeleryQueues.USER_FILE_PROJECT_SYNC,
        priority=OnyxCeleryPriority.HIGHEST,
    )
    logger.info(
        f"Triggered project sync for user_file_id={user_file.id} with task_id={task.id}"
    )

    return Response(status_code=204)


@router.post("/{project_id}/files/{file_id}", response_model=UserFileSnapshot)
def link_user_file_to_project(
    project_id: int,
    file_id: UUID,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> UserFileSnapshot:
    """Link an existing user file to a specific project for the current user.

    Creates the association in the Project__UserFile join table if it does not exist.
    Returns the linked user file snapshot.
    """
    user_id = user.id if user is not None else None
    project = (
        db_session.query(UserProject)
        .filter(UserProject.id == project_id, UserProject.user_id == user_id)
        .one_or_none()
    )
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    user_file = (
        db_session.query(UserFile)
        .filter(UserFile.id == file_id, UserFile.user_id == user_id)
        .one_or_none()
    )
    if user_file is None:
        raise HTTPException(status_code=404, detail="File not found")

    if user_file not in project.user_files:
        user_file.needs_project_sync = True
        project.user_files.append(user_file)
        db_session.commit()

    tenant_id = get_current_tenant_id()
    task = client_app.send_task(
        OnyxCeleryTask.PROCESS_SINGLE_USER_FILE_PROJECT_SYNC,
        kwargs={"user_file_id": user_file.id, "tenant_id": tenant_id},
        queue=OnyxCeleryQueues.USER_FILE_PROJECT_SYNC,
        priority=OnyxCeleryPriority.HIGHEST,
    )
    logger.info(
        f"Triggered project sync for user_file_id={user_file.id} with task_id={task.id}"
    )

    return UserFileSnapshot.from_model(user_file)


class ProjectInstructionsResponse(BaseModel):
    instructions: str | None


@router.get("/{project_id}/instructions", response_model=ProjectInstructionsResponse)
def get_project_instructions(
    project_id: int,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> ProjectInstructionsResponse:
    user_id = user.id if user is not None else None
    project = (
        db_session.query(UserProject)
        .filter(UserProject.id == project_id, UserProject.user_id == user_id)
        .one_or_none()
    )

    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    return ProjectInstructionsResponse(instructions=project.instructions)


class UpsertProjectInstructionsRequest(BaseModel):
    instructions: str


@router.post("/{project_id}/instructions", response_model=ProjectInstructionsResponse)
def upsert_project_instructions(
    project_id: int,
    body: UpsertProjectInstructionsRequest,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> ProjectInstructionsResponse:
    """Create or update this project's instructions stored on the project itself."""
    # Ensure the project exists and belongs to the user
    user_id = user.id if user is not None else None
    project = (
        db_session.query(UserProject)
        .filter(UserProject.id == project_id, UserProject.user_id == user_id)
        .one_or_none()
    )
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    project.instructions = body.instructions

    db_session.commit()
    db_session.refresh(project)
    return ProjectInstructionsResponse(instructions=project.instructions)


class ProjectPayload(BaseModel):
    project: UserProjectSnapshot
    files: list[UserFileSnapshot] | None = None
    persona_id_to_is_default: dict[int, bool] | None = None


@router.get("/{project_id}/details", response_model=ProjectPayload)
def get_project_details(
    project_id: int,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> ProjectPayload:
    project = get_project(project_id, user, db_session)
    files = get_files_in_project(project_id, user, db_session)
    persona_ids = [
        session.persona_id
        for session in project.chat_sessions
        if session.persona_id is not None
    ]
    personas = get_personas_by_ids(persona_ids, db_session)
    persona_id_to_is_default = {
        persona.id: persona.is_default_persona for persona in personas
    }
    return ProjectPayload(
        project=project,
        files=files,
        persona_id_to_is_default=persona_id_to_is_default,
    )


class UpdateProjectRequest(BaseModel):
    name: str | None = None
    description: str | None = None


@router.patch("/{project_id}", response_model=UserProjectSnapshot)
def update_project(
    project_id: int,
    body: UpdateProjectRequest,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> UserProjectSnapshot:
    user_id = user.id if user is not None else None
    project = (
        db_session.query(UserProject)
        .filter(UserProject.id == project_id, UserProject.user_id == user_id)
        .one_or_none()
    )
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    if body.name is not None:
        project.name = body.name
    if body.description is not None:
        project.description = body.description

    db_session.commit()
    db_session.refresh(project)
    return UserProjectSnapshot.from_model(project)


@router.delete("/{project_id}")
def delete_project(
    project_id: int,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> Response:
    user_id = user.id if user is not None else None
    project = (
        db_session.query(UserProject)
        .filter(UserProject.id == project_id, UserProject.user_id == user_id)
        .one_or_none()
    )
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    # Unlink chat sessions from this project
    for chat in project.chat_sessions:
        chat.project_id = None

    # Unlink many-to-many user files association (Project__UserFile)
    for uf in list(project.user_files):
        project.user_files.remove(uf)

    db_session.delete(project)
    db_session.commit()
    return Response(status_code=204)


@router.delete("/file/{file_id}")
def delete_user_file(
    file_id: UUID,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> UserFileDeleteResult:
    """Delete a user file belonging to the current user.

    This will also remove any project associations for the file.
    """
    user_id = user.id if user is not None else None
    user_file = (
        db_session.query(UserFile)
        .filter(UserFile.id == file_id, UserFile.user_id == user_id)
        .one_or_none()
    )
    if user_file is None:
        raise HTTPException(status_code=404, detail="File not found")

    # Check associations with projects and assistants (personas)
    project_names = [project.name for project in user_file.projects]
    assistant_names = [assistant.name for assistant in user_file.assistants]

    if len(project_names) > 0 or len(assistant_names) > 0:
        return UserFileDeleteResult(
            has_associations=True,
            project_names=project_names,
            assistant_names=assistant_names,
        )

    # No associations found; mark as DELETING and enqueue delete task
    user_file.status = UserFileStatus.DELETING
    db_session.commit()

    tenant_id = get_current_tenant_id()
    task = client_app.send_task(
        OnyxCeleryTask.DELETE_SINGLE_USER_FILE,
        kwargs={"user_file_id": str(user_file.id), "tenant_id": tenant_id},
        queue=OnyxCeleryQueues.USER_FILE_DELETE,
        priority=OnyxCeleryPriority.HIGH,
    )
    logger.info(
        f"Triggered delete for user_file_id={user_file.id} with task_id={task.id}"
    )
    return UserFileDeleteResult(
        has_associations=False, project_names=[], assistant_names=[]
    )


@router.get("/file/{file_id}", response_model=UserFileSnapshot)
def get_user_file(
    file_id: UUID,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> UserFileSnapshot:
    """Fetch a single user file by ID for the current user.

    Includes files in any status (including FAILED) to allow status polling.
    """
    user_id = user.id if user is not None else None
    user_file = (
        db_session.query(UserFile)
        .filter(UserFile.id == file_id, UserFile.user_id == user_id)
        .filter(UserFile.status != UserFileStatus.DELETING)
        .one_or_none()
    )
    if user_file is None:
        raise HTTPException(status_code=404, detail="File not found")
    return UserFileSnapshot.from_model(user_file)


class UserFileIdsRequest(BaseModel):
    file_ids: list[UUID]


@router.post("/file/statuses", response_model=list[UserFileSnapshot])
def get_user_file_statuses(
    body: UserFileIdsRequest,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> list[UserFileSnapshot]:
    """Fetch statuses for a set of user file IDs owned by the current user.

    Includes files in any status so the client can detect transitions to FAILED.
    """
    if not body.file_ids:
        return []

    user_id = user.id if user is not None else None
    user_files = (
        db_session.query(UserFile)
        .filter(UserFile.user_id == user_id)
        .filter(UserFile.id.in_(body.file_ids))
        .filter(UserFile.status != UserFileStatus.DELETING)
        .all()
    )

    return [UserFileSnapshot.from_model(user_file) for user_file in user_files]


@router.post("/{project_id}/move_chat_session")
def move_chat_session(
    project_id: int,
    body: ChatSessionRequest,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> Response:
    user_id = user.id if user is not None else None
    chat_session = (
        db_session.query(ChatSession)
        .filter(ChatSession.id == body.chat_session_id, ChatSession.user_id == user_id)
        .one_or_none()
    )
    if chat_session is None:
        raise HTTPException(status_code=404, detail="Chat session not found")
    chat_session.project_id = project_id
    db_session.commit()
    return Response(status_code=204)


@router.post("/remove_chat_session")
def remove_chat_session(
    body: ChatSessionRequest,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> Response:
    user_id = user.id if user is not None else None
    chat_session = (
        db_session.query(ChatSession)
        .filter(ChatSession.id == body.chat_session_id, ChatSession.user_id == user_id)
        .one_or_none()
    )
    if chat_session is None:
        raise HTTPException(status_code=404, detail="Chat session not found")
    chat_session.project_id = None
    db_session.commit()
    return Response(status_code=204)


@router.get("/session/{chat_session_id}/token-count", response_model=TokenCountResponse)
def get_chat_session_project_token_count(
    chat_session_id: str,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> TokenCountResponse:
    """Return sum of token_count for all user files in the project linked to the given chat session.

    If the chat session has no project, returns 0.
    """
    user_id = user.id if user is not None else None
    chat_session = (
        db_session.query(ChatSession)
        .filter(ChatSession.id == chat_session_id, ChatSession.user_id == user_id)
        .one_or_none()
    )
    if chat_session is None:
        raise HTTPException(status_code=404, detail="Chat session not found")

    if chat_session.project_id is None:
        return TokenCountResponse(total_tokens=0)

    total_tokens = (
        db_session.query(func.coalesce(func.sum(UserFile.token_count), 0))
        .filter(
            UserFile.user_id == user_id,
            UserFile.projects.any(id=chat_session.project_id),
        )
        .scalar()
        or 0
    )

    return TokenCountResponse(total_tokens=int(total_tokens))


@router.get("/session/{chat_session_id}/files")
def get_chat_session_project_files(
    chat_session_id: str,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> list[UserFileSnapshot]:
    """Return user files for the project linked to the given chat session.

    If the chat session has no project, returns an empty list.
    Only returns files owned by the current user and not FAILED.
    """
    user_id = user.id if user is not None else None

    chat_session = (
        db_session.query(ChatSession)
        .filter(ChatSession.id == chat_session_id, ChatSession.user_id == user_id)
        .one_or_none()
    )
    if chat_session is None:
        raise HTTPException(status_code=404, detail="Chat session not found")

    if chat_session.project_id is None:
        return []

    user_files = (
        db_session.query(UserFile)
        .filter(
            UserFile.projects.any(id=chat_session.project_id),
            UserFile.user_id == user_id,
            UserFile.status != UserFileStatus.FAILED,
        )
        .order_by(UserFile.created_at.desc())
        .all()
    )

    return [UserFileSnapshot.from_model(user_file) for user_file in user_files]


@router.get("/{project_id}/token-count", response_model=TokenCountResponse)
def get_project_token_count(
    project_id: int,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> TokenCountResponse:
    """Return sum of token_count for all user files in the given project for the current user."""

    # Verify the project belongs to the current user
    user_id = user.id if user is not None else None
    project = (
        db_session.query(UserProject)
        .filter(UserProject.id == project_id, UserProject.user_id == user_id)
        .one_or_none()
    )
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    total_tokens = (
        db_session.query(func.coalesce(func.sum(UserFile.token_count), 0))
        .filter(
            UserFile.user_id == user_id,
            UserFile.projects.any(id=project_id),
        )
        .scalar()
        or 0
    )

    return TokenCountResponse(total_tokens=int(total_tokens))
