import datetime
import uuid
from typing import List
from uuid import UUID

from fastapi import UploadFile
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func
from sqlalchemy.orm import Session

from onyx.configs.constants import (
    FileOrigin,
)
from onyx.db.enums import UserFileStatus
from onyx.db.models import Project__UserFile, User, UserFile, UserProject
from onyx.server.documents.connector import upload_files
from onyx.server.features.projects.projects_file_utils import (
    RejectedFile,
    categorize_uploaded_files,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()


class CategorizedFilesResult(BaseModel):
    user_files: list[UserFile]
    rejected_files: list[RejectedFile]
    id_to_temp_id: dict[str, str]
    # Allow SQLAlchemy ORM models inside this result container
    model_config = ConfigDict(arbitrary_types_allowed=True)

    @property
    def indexable_files(self) -> list[UserFile]:
        return [uf for uf in self.user_files if uf.status != UserFileStatus.SKIPPED]


def build_hashed_file_key(file: UploadFile) -> str:
    name_prefix = (file.filename or "")[:50]
    return f"{file.size}|{name_prefix}"


def create_user_files(
    files: List[UploadFile],
    project_id: int | None,
    user: User,
    db_session: Session,
    link_url: str | None = None,
    temp_id_map: dict[str, str] | None = None,
    incognito_session_id: UUID | None = None,
    temp_ids: list[str] | None = None,
) -> CategorizedFilesResult:
    """`temp_ids`: the client's temporary ID of each of `files`, in order.
    When given, it sets the ID of each file, also an empty one. `temp_id_map`,
    by `build_hashed_file_key`, serves a client that sends no `temp_ids`;
    files of one name and size share its key."""
    # Categorize the files
    categorized_files = categorize_uploaded_files(files, db_session)
    # NOTE: At the moment, zip metadata is not used for user files.
    # Should revisit to decide whether this should be a feature.
    upload_response = upload_files(categorized_files.acceptable, FileOrigin.USER_FILE)
    user_files = []
    rejected_files = categorized_files.rejected
    id_to_temp_id: dict[str, str] = {}
    temp_id_by_upload = (
        dict(zip(files, temp_ids, strict=True)) if temp_ids is not None else None
    )
    # Pair returned storage paths with the same set of acceptable files we uploaded
    for file_path, file, token_count, should_skip in zip(
        upload_response.file_paths,
        categorized_files.acceptable,
        categorized_files.acceptable_token_counts,
        categorized_files.acceptable_skip_indexing,
        strict=True,
    ):
        new_id = uuid.uuid4()
        if temp_id_by_upload is not None:
            new_temp_id: str | None = temp_id_by_upload[file]
        elif temp_id_map is not None:
            new_temp_id = temp_id_map.get(build_hashed_file_key(file))
        else:
            new_temp_id = None
        if new_temp_id is not None:
            id_to_temp_id[str(new_id)] = new_temp_id
        new_file = UserFile(
            id=new_id,
            user_id=user.id,
            file_id=file_path,
            name=file.filename,
            token_count=token_count,
            link_url=link_url,
            content_type=file.content_type,
            file_type=file.content_type,
            status=UserFileStatus.SKIPPED if should_skip else UserFileStatus.PROCESSING,
            incognito=incognito_session_id is not None,
            incognito_session_id=incognito_session_id,
            last_accessed_at=datetime.datetime.now(datetime.timezone.utc),
        )
        # Persist the UserFile first to satisfy FK constraints for association table
        db_session.add(new_file)
        db_session.flush()
        # Incognito uploads may use a project as context but never join it.
        if project_id and incognito_session_id is None:
            project_to_user_file = Project__UserFile(
                project_id=project_id,
                user_file_id=new_file.id,
            )
            db_session.add(project_to_user_file)
        user_files.append(new_file)
    db_session.commit()
    return CategorizedFilesResult(
        user_files=user_files,
        rejected_files=rejected_files,
        id_to_temp_id=id_to_temp_id,
    )


def check_project_ownership(
    project_id: int, user_id: UUID | None, db_session: Session
) -> bool:
    # In no-auth mode, all projects are accessible
    if user_id is None:
        # Verify project exists
        return (
            db_session.query(UserProject).filter(UserProject.id == project_id).first()
            is not None
        )

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


def get_project_user_files_by_file_ids(
    project_id: int, file_ids: list[str], db_session: Session
) -> list[UserFile]:
    """The project's user files whose file_id is in file_ids."""
    return (
        db_session.query(UserFile)
        .join(Project__UserFile)
        .filter(
            Project__UserFile.project_id == project_id,
            UserFile.file_id.in_(file_ids),
        )
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


def get_project_token_count(
    project_id: int | None,
    user_id: UUID | None,
    db_session: Session,
) -> int:
    """Return sum of token_count for all user files in the given project.

    If project_id is None, returns 0.
    """
    if project_id is None:
        return 0

    total_tokens = (
        db_session.query(func.coalesce(func.sum(UserFile.token_count), 0))
        .filter(
            UserFile.user_id == user_id,
            UserFile.projects.any(id=project_id),
        )
        .scalar()
        or 0
    )

    return int(total_tokens)


def get_user_projects(user_id: UUID, db_session: Session) -> list[UserProject]:
    return db_session.query(UserProject).filter(UserProject.user_id == user_id).all()


def get_owned_user_project(
    project_id: int, user_id: UUID, db_session: Session
) -> UserProject | None:
    return (
        db_session.query(UserProject)
        .filter(UserProject.id == project_id, UserProject.user_id == user_id)
        .one_or_none()
    )


def create_user_project__no_commit(
    name: str, user_id: UUID, db_session: Session
) -> UserProject:
    project = UserProject(name=name, user_id=user_id)
    db_session.add(project)
    return project


def delete_user_project__no_commit(project: UserProject, db_session: Session) -> None:
    db_session.delete(project)


def get_owned_user_file(
    file_id: UUID, user_id: UUID, db_session: Session
) -> UserFile | None:
    return (
        db_session.query(UserFile)
        .filter(UserFile.id == file_id, UserFile.user_id == user_id)
        .one_or_none()
    )


def get_owned_user_file_not_deleting(
    file_id: UUID, user_id: UUID, db_session: Session
) -> UserFile | None:
    return (
        db_session.query(UserFile)
        .filter(UserFile.id == file_id, UserFile.user_id == user_id)
        .filter(UserFile.status != UserFileStatus.DELETING)
        .one_or_none()
    )


def get_owned_user_files_not_deleting_by_ids(
    file_ids: list[UUID], user_id: UUID, db_session: Session
) -> list[UserFile]:
    return (
        db_session.query(UserFile)
        .filter(UserFile.user_id == user_id)
        .filter(UserFile.id.in_(file_ids))
        .filter(UserFile.status != UserFileStatus.DELETING)
        .all()
    )


def get_owned_project_user_files_by_link_date(
    project_id: int, user_id: UUID, db_session: Session
) -> list[UserFile]:
    """The user's non-FAILED files in the project, most recently linked first."""
    return (
        db_session.query(UserFile)
        .join(Project__UserFile, UserFile.id == Project__UserFile.user_file_id)
        .filter(
            Project__UserFile.project_id == project_id,
            UserFile.user_id == user_id,
            UserFile.status != UserFileStatus.FAILED,
        )
        .order_by(Project__UserFile.created_at.desc())
        .all()
    )


def get_owned_project_user_files_by_upload_date(
    project_id: int, user_id: UUID, db_session: Session
) -> list[UserFile]:
    """The user's non-FAILED files in the project, most recently created first."""
    return (
        db_session.query(UserFile)
        .filter(
            UserFile.projects.any(id=project_id),
            UserFile.user_id == user_id,
            UserFile.status != UserFileStatus.FAILED,
        )
        .order_by(UserFile.created_at.desc())
        .all()
    )
