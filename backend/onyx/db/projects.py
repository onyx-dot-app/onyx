import datetime
import uuid
from typing import List
from uuid import UUID

from fastapi import UploadFile
from sqlalchemy.orm import Session

from onyx.background.celery.versioned_apps.client import app as client_app
from onyx.configs.constants import OnyxCeleryPriority
from onyx.configs.constants import OnyxCeleryQueues
from onyx.configs.constants import OnyxCeleryTask
from onyx.db.models import Project__UserFile
from onyx.db.models import User
from onyx.db.models import UserFile
from onyx.db.models import UserFolder
from onyx.server.documents.connector import upload_files
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()


def create_user_files(
    files: List[UploadFile],
    project_id: int | None,
    user: User | None,
    db_session: Session,
    link_url: str | None = None,
) -> list[UserFile]:
    """NOTE(rkuo): This function can take -1 (RECENT_DOCS_FOLDER_ID for folder_id.
    Document what this does?
    """

    # NOTE: At the moment, zip metadata is not used for user files.
    # Should revisit to decide whether this should be a feature.
    upload_response = upload_files(files)
    user_files = []

    for file_path, file in zip(upload_response.file_paths, files):
        new_file = UserFile(
            id=uuid.uuid4(),
            user_id=user.id if user else None,
            file_id=file_path,
            document_id=uuid.uuid4(),  # TODO: remove this column
            name=file.filename,
            token_count=None,
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
    return user_files


def upload_files_to_user_files_with_indexing(
    files: List[UploadFile],
    project_id: int | None,
    user: User,
    db_session: Session,
) -> list[UserFile]:
    user_files = create_user_files(files, project_id, user, db_session)

    # Trigger per-file processing immediately for the current tenant
    tenant_id = get_current_tenant_id()
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

    return user_files


def check_project_ownership(
    project_id: int, user_id: UUID, db_session: Session
) -> bool:
    return (
        db_session.query(UserFolder)
        .filter(UserFolder.id == project_id, UserFolder.user_id == user_id)
        .first()
        is not None
    )


def get_user_files_from_project(
    project_id: int, user_id: UUID, db_session: Session
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
