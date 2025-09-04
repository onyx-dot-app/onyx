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
from onyx.db.engine.sql_engine import get_session
from onyx.db.models import ChatSession
from onyx.db.models import Prompt
from onyx.db.models import User
from onyx.db.models import UserFile
from onyx.db.models import UserFolder
from onyx.db.projects import upload_files_to_user_files_with_indexing
from onyx.db.prompts import upsert_prompt
from onyx.server.features.persona.models import PromptSnapshot
from onyx.server.features.projects.models import CategorizedFilesSnapshot
from onyx.server.features.projects.models import TokenCountResponse
from onyx.server.features.projects.models import UserFileSnapshot
from onyx.server.features.projects.models import UserProjectSnapshot
from onyx.utils.logger import setup_logger

logger = setup_logger()


router = APIRouter(prefix="/user/projects")


@router.get("/")
def get_projects(
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> list[UserProjectSnapshot]:
    projects = db_session.query(UserFolder).filter(UserFolder.user_id == user.id).all()
    return [UserProjectSnapshot.from_model(project) for project in projects]


@router.post("/create")
def create_project(
    name: str,
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> UserProjectSnapshot:
    project = UserFolder(name=name, user_id=user.id)
    db_session.add(project)
    db_session.commit()
    return UserProjectSnapshot.from_model(project)


@router.post("/file/upload")
def upload_user_files(
    files: list[UploadFile] = File(...),
    project_id: int | None = Form(None),
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> CategorizedFilesSnapshot:
    try:

        # Use our consolidated function that handles indexing properly
        categorized_files_result = upload_files_to_user_files_with_indexing(
            files=files, project_id=project_id, user=user, db_session=db_session
        )

        return CategorizedFilesSnapshot.from_result(categorized_files_result)

    except Exception as e:
        logger.error(f"Error uploading files: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to upload files: {str(e)}")


@router.get("/{project_id}")
def get_project(
    project_id: int,
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> UserProjectSnapshot:
    project = (
        db_session.query(UserFolder)
        .filter(UserFolder.id == project_id, UserFolder.user_id == user.id)
        .one_or_none()
    )
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return UserProjectSnapshot.from_model(project)


@router.get("/files/{project_id}")
def get_files_in_project(
    project_id: int,
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> list[UserFileSnapshot]:
    user_files = (
        db_session.query(UserFile)
        .filter(UserFile.projects.any(id=project_id), UserFile.user_id == user.id)
        .all()
    )
    return [UserFileSnapshot.from_model(user_file) for user_file in user_files]


@router.get("/{project_id}/instructions")
def get_project_instructions(
    project_id: int,
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> PromptSnapshot:

    project = (
        db_session.query(UserFolder)
        .filter(UserFolder.id == project_id, UserFolder.user_id == user.id)
        .one_or_none()
    )

    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    prompt = db_session.query(Prompt).filter_by(id=project.prompt_id).one_or_none()
    if prompt is None:
        return None

    return PromptSnapshot.from_model(prompt)


# -------------------------
# Project Instructions
# -------------------------
class UpsertProjectInstructionsRequest(BaseModel):
    instructions: str


@router.post("/{project_id}/instructions", response_model=PromptSnapshot)
def upsert_project_instructions(
    project_id: int,
    body: UpsertProjectInstructionsRequest,
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
):
    """Create or update a Prompt that stores this project's instructions."""
    # Ensure the project exists and belongs to the user
    project = (
        db_session.query(UserFolder)
        .filter(UserFolder.id == project_id, UserFolder.user_id == user.id)
        .one_or_none()
    )
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    print("upserting instructions", body.instructions)

    prompt_name = f"project-{project_id}-instructions"
    description = f"Instructions prompt for project {project_id}"

    prompt = upsert_prompt(
        db_session=db_session,
        user=user,
        name=prompt_name,
        system_prompt=body.instructions,
        task_prompt="",
        datetime_aware=True,
        prompt_id=project.prompt_id,
        include_citations=False,
        default_prompt=False,
        description=description,
    )
    project.prompt_id = prompt.id

    db_session.commit()
    return PromptSnapshot.from_model(prompt)


class ProjectPayload(BaseModel):
    project: UserProjectSnapshot
    files: list[UserFileSnapshot] | None = None
    instructions: PromptSnapshot | None = None


@router.get("/{project_id}/details", response_model=ProjectPayload)
def get_project_details(
    project_id: int,
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> ProjectPayload:
    project = get_project(project_id, user, db_session)
    files = get_files_in_project(project_id, user, db_session)
    instructions = get_project_instructions(project_id, user, db_session)
    return ProjectPayload(project=project, files=files, instructions=instructions)


class MoveChatSessionRequest(BaseModel):
    chat_session_id: str


@router.post("/{project_id}/move_chat_session")
def move_chat_session(
    project_id: int,
    body: MoveChatSessionRequest,
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> Response:
    chat_session = (
        db_session.query(ChatSession)
        .filter(ChatSession.id == body.chat_session_id, ChatSession.user_id == user.id)
        .one_or_none()
    )
    if chat_session is None:
        raise HTTPException(status_code=404, detail="Chat session not found")
    chat_session.project_id = project_id
    db_session.commit()
    return Response(status_code=204)


@router.get("/session/{chat_session_id}/token-count", response_model=TokenCountResponse)
def get_chat_session_project_token_count(
    chat_session_id: str,
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> TokenCountResponse:
    """Return sum of token_count for all user files in the project linked to the given chat session.

    If the chat session has no project, returns 0.
    """
    chat_session = (
        db_session.query(ChatSession)
        .filter(ChatSession.id == chat_session_id, ChatSession.user_id == user.id)
        .one_or_none()
    )
    if chat_session is None:
        raise HTTPException(status_code=404, detail="Chat session not found")

    if chat_session.project_id is None:
        return TokenCountResponse(total_tokens=0)

    total_tokens = (
        db_session.query(func.coalesce(func.sum(UserFile.token_count), 0))
        .filter(
            UserFile.user_id == user.id,
            UserFile.projects.any(id=chat_session.project_id),
        )
        .scalar()
        or 0
    )

    return TokenCountResponse(total_tokens=int(total_tokens))
