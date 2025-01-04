from typing import List

from fastapi import UploadFile
from sqlalchemy.orm import Session

from onyx.db.models import User
from onyx.db.models import UserFile
from onyx.server.documents.connector import upload_files

CHAT_FOLDER_ID = -1
RECENT_DOCUMENTS_FOLDER_ID = -2


def create_user_files(
    files: List[UploadFile],
    folder_id: int | None,
    user: User | None,
    db_session: Session,
) -> UserFile:
    upload_response = upload_files(files, db_session)
    for file_path, file in zip(upload_response.file_paths, files):
        new_file = UserFile(
            user_id=user.id if user else None,
            parent_folder_id=folder_id,
            file_id=file_path,
            document_id=file_path,  # We'll use the same ID for now
            name=file.filename,
        )
        db_session.add(new_file)

    db_session.commit()
    return upload_response
