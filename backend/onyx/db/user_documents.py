import datetime
from typing import List

from fastapi import UploadFile
from sqlalchemy import and_
from sqlalchemy.orm import Session

from onyx.connectors.file.connector import _read_files_and_metadata
from onyx.db.models import Persona
from onyx.db.models import Persona__UserFile
from onyx.db.models import User
from onyx.db.models import UserFile
from onyx.db.models import UserFolder
from onyx.file_processing.extract_file_text import read_text_file
from onyx.llm.factory import get_default_llms
from onyx.natural_language_processing.utils import get_tokenizer
from onyx.server.documents.connector import upload_files

USER_FILE_CONSTANT = "USER_FILE_CONNECTOR"


def create_user_files(
    files: List[UploadFile],
    folder_id: int | None,
    user: User | None,
    db_session: Session,
) -> list[UserFile]:
    upload_response = upload_files(files, db_session)
    user_files = []

    context_files = _read_files_and_metadata(
        file_name=str(upload_response.file_paths[0]), db_session=db_session
    )

    content, _ = read_text_file(next(context_files)[1])
    llm, _ = get_default_llms()

    llm_tokenizer = get_tokenizer(
        model_name=llm.config.model_name,
        provider_type=llm.config.model_provider,
    )
    token_count = len(llm_tokenizer.encode(content))

    for file_path, file in zip(upload_response.file_paths, files):
        new_file = UserFile(
            user_id=user.id if user else None,
            folder_id=folder_id,
            file_id=file_path,
            document_id="USER_FILE_CONNECTOR__" + file_path,
            name=file.filename,
            token_count=token_count,
        )
        db_session.add(new_file)
        user_files.append(new_file)
    db_session.commit()
    return user_files


def get_user_files_from_folder(folder_id: int, db_session: Session) -> list[UserFile]:
    return db_session.query(UserFile).filter(UserFile.folder_id == folder_id).all()


def share_file_with_assistant(
    file_id: int, assistant_id: int, db_session: Session
) -> None:
    file = db_session.query(UserFile).filter(UserFile.id == file_id).first()
    assistant = db_session.query(Persona).filter(Persona.id == assistant_id).first()

    if file and assistant:
        file.assistants.append(assistant)
        db_session.commit()


def unshare_file_with_assistant(
    file_id: int, assistant_id: int, db_session: Session
) -> None:
    db_session.query(Persona__UserFile).filter(
        and_(
            Persona__UserFile.user_file_id == file_id,
            Persona__UserFile.persona_id == assistant_id,
        )
    ).delete()
    db_session.commit()


def share_folder_with_assistant(
    folder_id: int, assistant_id: int, db_session: Session
) -> None:
    folder = db_session.query(UserFolder).filter(UserFolder.id == folder_id).first()
    assistant = db_session.query(Persona).filter(Persona.id == assistant_id).first()

    if folder and assistant:
        for file in folder.files:
            share_file_with_assistant(file.id, assistant_id, db_session)


def unshare_folder_with_assistant(
    folder_id: int, assistant_id: int, db_session: Session
) -> None:
    folder = db_session.query(UserFolder).filter(UserFolder.id == folder_id).first()

    if folder:
        for file in folder.files:
            unshare_file_with_assistant(file.id, assistant_id, db_session)


def fetch_user_files_for_documents(
    document_ids: list[str],
    db_session: Session,
) -> dict[str, None | int]:
    # Query UserFile objects for the given document_ids
    user_files = (
        db_session.query(UserFile).filter(UserFile.document_id.in_(document_ids)).all()
    )

    # Create a dictionary mapping document_ids to UserFile objects
    result = {doc_id: None for doc_id in document_ids}
    for user_file in user_files:
        result[user_file.document_id] = user_file.id

    return result


def upsert_user_folder(
    db_session: Session,
    id: int | None = None,
    user_id: int | None = None,
    name: str | None = None,
    description: str | None = None,
    created_at: datetime.datetime | None = None,
    user: User | None = None,
    files: list[UserFile] | None = None,
    assistants: list[Persona] | None = None,
) -> UserFolder:
    if id is not None:
        user_folder = db_session.query(UserFolder).filter_by(id=id).first()
    else:
        user_folder = (
            db_session.query(UserFolder).filter_by(name=name, user_id=user_id).first()
        )

    if user_folder:
        if user_id is not None:
            user_folder.user_id = user_id
        if name is not None:
            user_folder.name = name
        if description is not None:
            user_folder.description = description
        if created_at is not None:
            user_folder.created_at = created_at
        if user is not None:
            user_folder.user = user
        if files is not None:
            user_folder.files = files
        if assistants is not None:
            user_folder.assistants = assistants
    else:
        user_folder = UserFolder(
            id=id,
            user_id=user_id,
            name=name,
            description=description,
            created_at=created_at or datetime.datetime.utcnow(),
            user=user,
            files=files or [],
            assistants=assistants or [],
        )
        db_session.add(user_folder)

    db_session.flush()
    return user_folder


def get_user_folder_by_name(db_session: Session, name: str) -> UserFolder | None:
    return db_session.query(UserFolder).filter(UserFolder.name == name).first()
