import datetime
import uuid
from typing import List

from fastapi import UploadFile
from sqlalchemy.orm import Session

from onyx.db.models import Project__UserFile
from onyx.db.models import User
from onyx.db.models import UserFile
from onyx.server.documents.connector import upload_files


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
            id=str(uuid.uuid4()),
            user_id=user.id if user else None,
            file_id=file_path,
            name=file.filename,
            token_count=None,
            link_url=link_url,
            content_type=file.content_type,
            last_accessed_at=datetime.datetime.now(datetime.timezone.utc),
        )
        if project_id:
            project_to_user_file = Project__UserFile(
                project_id=project_id,
                user_file_id=new_file.id,
            )
            db_session.add(project_to_user_file)
        db_session.add(new_file)
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

    # Trigger indexing immediately
    # TODO(subash): trigger indexing for all user files
    return user_files
