import datetime
import uuid
from typing import List
from uuid import UUID

from fastapi import HTTPException
from fastapi import UploadFile
from pydantic import BaseModel
from pydantic import ConfigDict
from sqlalchemy.orm import Session

from onyx.background.celery.versioned_apps.client import app as client_app
from onyx.configs.constants import FileOrigin
from onyx.configs.constants import OnyxCeleryPriority
from onyx.configs.constants import OnyxCeleryQueues
from onyx.configs.constants import OnyxCeleryTask
from onyx.db.models import Project__UserFile
from onyx.db.models import User
from onyx.db.models import UserFile
from onyx.db.models import UserProject
from onyx.server.documents.connector import upload_files
from onyx.server.features.projects.projects_file_utils import categorize_uploaded_files
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()


class CategorizedFilesResult(BaseModel):
    user_files: list[UserFile]
    non_accepted_files: list[str]
    unsupported_files: list[str]
    id_to_temp_id: dict[str, str]
    # Allow SQLAlchemy ORM models inside this result container
    model_config = ConfigDict(arbitrary_types_allowed=True)


def build_hashed_file_key(file: UploadFile) -> str:
    name_prefix = (file.filename or "")[:50]
    return f"{file.size}|{name_prefix}"


def create_user_files(
    files: List[UploadFile],
    project_id: int | None,
    user: User | None,
    db_session: Session,
    link_url: str | None = None,
    temp_id_map: dict[str, str] | None = None,
) -> CategorizedFilesResult:

    # Categorize the files
    categorized_files = categorize_uploaded_files(files)
    # NOTE: At the moment, zip metadata is not used for user files.
    # Should revisit to decide whether this should be a feature.
    upload_response = upload_files(categorized_files.acceptable, FileOrigin.USER_FILE)
    user_files = []
    non_accepted_files = categorized_files.non_accepted
    unsupported_files = categorized_files.unsupported
    id_to_temp_id: dict[str, str] = {}
    # Pair returned storage paths with the same set of acceptable files we uploaded
    for file_path, file in zip(
        upload_response.file_paths, categorized_files.acceptable
    ):
        new_id = uuid.uuid4()
        new_temp_id = (
            temp_id_map.get(build_hashed_file_key(file)) if temp_id_map else None
        )
        if new_temp_id is not None:
            id_to_temp_id[str(new_id)] = new_temp_id
        new_file = UserFile(
            id=new_id,
            user_id=user.id if user else None,
            file_id=file_path,
            document_id=str(new_id),
            name=file.filename,
            token_count=categorized_files.acceptable_file_to_token_count[
                file.filename or ""
            ],
            link_url=link_url,
            content_type=file.content_type,
            file_type=file.content_type,
            last_accessed_at=datetime.datetime.now(datetime.timezone.utc),
        )
        # Persist the UserFile first to satisfy FK constraints for association table
        db_session.add(new_file)
        db_session.flush()
        if project_id:
            project_to_user_file = Project__UserFile(
                project_id=project_id,
                user_file_id=new_file.id,
            )
            db_session.add(project_to_user_file)
        user_files.append(new_file)
    db_session.commit()
    return CategorizedFilesResult(
        user_files=user_files,
        non_accepted_files=non_accepted_files,
        unsupported_files=unsupported_files,
        id_to_temp_id=id_to_temp_id,
    )


def upload_files_to_user_files_with_indexing(
    files: List[UploadFile],
    project_id: int | None,
    user: User | None,
    temp_id_map: dict[str, str] | None,
    db_session: Session,
) -> CategorizedFilesResult:
    # Validate project ownership if a project_id is provided
    if project_id is not None and user is not None:
        if not check_project_ownership(project_id, user.id, db_session):
            raise HTTPException(status_code=404, detail="Project not found")

    categorized_files_result = create_user_files(
        files,
        project_id,
        user,
        db_session,
        temp_id_map=temp_id_map,
    )
    user_files = categorized_files_result.user_files
    non_accepted_files = categorized_files_result.non_accepted_files
    unsupported_files = categorized_files_result.unsupported_files
    id_to_temp_id = categorized_files_result.id_to_temp_id
    # Trigger per-file processing immediately for the current tenant
    tenant_id = get_current_tenant_id()
    if non_accepted_files:
        for filename in non_accepted_files:
            logger.warning(f"Non-accepted file: {filename}")
    if unsupported_files:
        for filename in unsupported_files:
            logger.warning(f"Unsupported file: {filename}")
    for user_file in user_files:
        task = client_app.send_task(
            OnyxCeleryTask.PROCESS_SINGLE_USER_FILE,
            kwargs={"user_file_id": user_file.id, "tenant_id": tenant_id},
            queue=OnyxCeleryQueues.USER_FILE_PROCESSING,
            priority=OnyxCeleryPriority.HIGH,
        )
        logger.info(
            f"Triggered indexing for user_file_id={user_file.id} with task_id={task.id}"
        )

    return CategorizedFilesResult(
        user_files=user_files,
        non_accepted_files=non_accepted_files,
        unsupported_files=unsupported_files,
        id_to_temp_id=id_to_temp_id,
    )


def check_project_ownership(
    project_id: int, user_id: UUID | None, db_session: Session
) -> bool:
    return (
        db_session.query(UserProject)
        .filter(UserProject.id == project_id, UserProject.user_id == user_id)
        .first()
        is not None
    )


def get_user_files_from_project(
    project_id: int, user_id: UUID | None, db_session: Session
) -> list[UserFile]:
    # First check if the user owns the project
    if not check_project_ownership(project_id, user_id, db_session):
        return []

    return (
        db_session.query(UserFile)
        .join(Project__UserFile)
        .filter(Project__UserFile.project_id == project_id)
        .all()
    )


def get_project_instructions(db_session: Session, project_id: int | None) -> str | None:
    """Return the project's instruction text from the project, else None.

    Safe helper that swallows DB errors and returns None on any failure.
    """
    if not project_id:
        return None
    try:
        project = (
            db_session.query(UserProject)
            .filter(UserProject.id == project_id)
            .one_or_none()
        )
        if not project or not project.instructions:
            return None
        instructions = project.instructions.strip()
        return instructions or None
    except Exception:
        return None
