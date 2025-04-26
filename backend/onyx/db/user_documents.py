import datetime
import time
from typing import List
from uuid import UUID

from fastapi import UploadFile
from sqlalchemy import and_
from sqlalchemy import func
from sqlalchemy.orm import joinedload
from sqlalchemy.orm import Session

from onyx.auth.users import get_current_tenant_id
from onyx.configs.constants import DocumentSource
from onyx.connectors.models import InputType
from onyx.db.connector import create_connector
from onyx.db.connector_credential_pair import add_credential_to_connector
from onyx.db.credentials import create_credential
from onyx.db.enums import AccessType
from onyx.db.models import ConnectorCredentialPair
from onyx.db.models import Document
from onyx.db.models import DocumentByConnectorCredentialPair
from onyx.db.models import Persona
from onyx.db.models import Persona__UserFile
from onyx.db.models import User
from onyx.db.models import UserFile
from onyx.db.models import UserFolder
from onyx.server.documents.connector import trigger_indexing_for_cc_pair
from onyx.server.documents.connector import upload_files
from onyx.server.documents.models import ConnectorBase
from onyx.server.documents.models import CredentialBase
from onyx.server.models import StatusResponse

USER_FILE_CONSTANT = "USER_FILE_CONNECTOR"


def create_user_files(
    files: List[UploadFile],
    folder_id: int | None,
    user: User | None,
    db_session: Session,
    link_url: str | None = None,
) -> list[UserFile]:
    """NOTE(rkuo): This function can take -1 (RECENT_DOCS_FOLDER_ID for folder_id.
    Document what this does?
    """

    # NOTE: At the moment, zip metadata is not used for user files.
    # Should revisit to decide whether this should be a feature.
    upload_response = upload_files(files, db_session)
    user_files = []

    for file_path, file in zip(upload_response.file_paths, files):
        new_file = UserFile(
            user_id=user.id if user else None,
            folder_id=folder_id,
            file_id=file_path,
            document_id="USER_FILE_CONNECTOR__" + file_path,
            name=file.filename,
            token_count=None,
            link_url=link_url,
            content_type=file.content_type,
        )
        db_session.add(new_file)
        user_files.append(new_file)
    db_session.commit()
    return user_files


def upload_files_to_user_files_with_indexing(
    files: List[UploadFile],
    folder_id: int | None,
    user: User,
    db_session: Session,
    trigger_index: bool = True,
) -> list[UserFile]:
    """NOTE(rkuo): This function can take -1 (RECENT_DOCS_FOLDER_ID for folder_id.
    Document what this does?

    Create user files and trigger immediate indexing"""
    # Create the user files first
    user_files = create_user_files(files, folder_id, user, db_session)

    # Create connector and credential for each file
    for user_file in user_files:
        cc_pair = create_file_connector_credential(user_file, user, db_session)
        user_file.cc_pair_id = cc_pair.data

    db_session.commit()

    # Trigger immediate high-priority indexing for all created files
    if trigger_index:
        tenant_id = get_current_tenant_id()
        for user_file in user_files:
            # Use the existing trigger_indexing_for_cc_pair function but with highest priority
            if user_file.cc_pair_id:
                trigger_indexing_for_cc_pair(
                    [],
                    user_file.cc_pair.connector_id,
                    False,
                    tenant_id,
                    db_session,
                    is_user_file=True,
                )

    return user_files


def create_file_connector_credential(
    user_file: UserFile, user: User, db_session: Session
) -> StatusResponse:
    """Create connector and credential for a user file"""
    connector_base = ConnectorBase(
        name=f"UserFile-{user_file.file_id}-{int(time.time())}",
        source=DocumentSource.FILE,
        input_type=InputType.LOAD_STATE,
        connector_specific_config={
            "file_locations": [user_file.file_id],
            "zip_metadata": {},
        },
        refresh_freq=None,
        prune_freq=None,
        indexing_start=None,
    )

    connector = create_connector(db_session=db_session, connector_data=connector_base)

    credential_info = CredentialBase(
        credential_json={},
        admin_public=True,
        source=DocumentSource.FILE,
        curator_public=True,
        groups=[],
        name=f"UserFileCredential-{user_file.file_id}-{int(time.time())}",
        is_user_file=True,
    )

    credential = create_credential(credential_info, user, db_session)

    return add_credential_to_connector(
        db_session=db_session,
        user=user,
        connector_id=connector.id,
        credential_id=credential.id,
        cc_pair_name=f"UserFileCCPair-{user_file.file_id}-{int(time.time())}",
        access_type=AccessType.PRIVATE,
        auto_sync_options=None,
        groups=[],
        is_user_file=True,
    )


def get_user_file_indexing_status(
    file_ids: list[int], db_session: Session
) -> dict[int, bool]:
    """Get indexing status for multiple user files"""
    status_dict = {}

    # Query UserFile with cc_pair join
    files_with_pairs = (
        db_session.query(UserFile)
        .filter(UserFile.id.in_(file_ids))
        .options(joinedload(UserFile.cc_pair))
        .all()
    )

    for file in files_with_pairs:
        if file.cc_pair and file.cc_pair.last_successful_index_time:
            status_dict[file.id] = True
        else:
            status_dict[file.id] = False

    return status_dict


def calculate_user_files_token_count(
    file_ids: list[int], folder_ids: list[int], db_session: Session
) -> int:
    """Calculate total token count for specified files and folders"""
    total_tokens = 0

    # Get tokens from individual files
    if file_ids:
        file_tokens = (
            db_session.query(func.sum(UserFile.token_count))
            .filter(UserFile.id.in_(file_ids))
            .scalar()
            or 0
        )
        total_tokens += file_tokens

    # Get tokens from folders
    if folder_ids:
        folder_files_tokens = (
            db_session.query(func.sum(UserFile.token_count))
            .filter(UserFile.folder_id.in_(folder_ids))
            .scalar()
            or 0
        )
        total_tokens += folder_files_tokens

    return total_tokens


def load_all_user_files(
    file_ids: list[int], folder_ids: list[int], db_session: Session
) -> list[UserFile]:
    """Load all user files from specified file IDs and folder IDs"""
    result = []

    # Get individual files
    if file_ids:
        files = db_session.query(UserFile).filter(UserFile.id.in_(file_ids)).all()
        result.extend(files)

    # Get files from folders
    if folder_ids:
        folder_files = (
            db_session.query(UserFile).filter(UserFile.folder_id.in_(folder_ids)).all()
        )
        result.extend(folder_files)

    return result


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
) -> dict[str, int | None]:
    """
    Fetches user file IDs for the given document IDs.

    Args:
        document_ids: List of document IDs to fetch user files for
        db_session: Database session

    Returns:
        Dictionary mapping document IDs to user file IDs (or None if no user file exists)
    """
    # First, get the document to cc_pair mapping
    doc_cc_pairs = (
        db_session.query(Document.id, ConnectorCredentialPair.id)
        .join(
            DocumentByConnectorCredentialPair,
            Document.id == DocumentByConnectorCredentialPair.id,
        )
        .join(
            ConnectorCredentialPair,
            and_(
                DocumentByConnectorCredentialPair.connector_id
                == ConnectorCredentialPair.connector_id,
                DocumentByConnectorCredentialPair.credential_id
                == ConnectorCredentialPair.credential_id,
            ),
        )
        .filter(Document.id.in_(document_ids))
        .all()
    )

    # Get cc_pair to user_file mapping
    cc_pair_to_user_file = (
        db_session.query(ConnectorCredentialPair.id, UserFile.id)
        .join(UserFile, UserFile.cc_pair_id == ConnectorCredentialPair.id)
        .filter(
            ConnectorCredentialPair.id.in_(
                [cc_pair_id for _, cc_pair_id in doc_cc_pairs]
            )
        )
        .all()
    )

    # Create mapping from cc_pair_id to user_file_id
    cc_pair_to_user_file_dict = {
        cc_pair_id: user_file_id for cc_pair_id, user_file_id in cc_pair_to_user_file
    }

    # Create the final result mapping document_id to user_file_id
    result: dict[str, int | None] = {doc_id: None for doc_id in document_ids}
    for doc_id, cc_pair_id in doc_cc_pairs:
        if cc_pair_id in cc_pair_to_user_file_dict:
            result[doc_id] = cc_pair_to_user_file_dict[cc_pair_id]

    return result


def fetch_user_folders_for_documents(
    document_ids: list[str],
    db_session: Session,
) -> dict[str, int | None]:
    """
    Fetches user folder IDs for the given document IDs.

    For each document, returns the folder ID that the document's associated user file belongs to.

    Args:
        document_ids: List of document IDs to fetch user folders for
        db_session: Database session

    Returns:
        Dictionary mapping document IDs to user folder IDs (or None if no user folder exists)
    """
    # First, get the document to cc_pair mapping
    doc_cc_pairs = (
        db_session.query(Document.id, ConnectorCredentialPair.id)
        .join(
            DocumentByConnectorCredentialPair,
            Document.id == DocumentByConnectorCredentialPair.id,
        )
        .join(
            ConnectorCredentialPair,
            and_(
                DocumentByConnectorCredentialPair.connector_id
                == ConnectorCredentialPair.connector_id,
                DocumentByConnectorCredentialPair.credential_id
                == ConnectorCredentialPair.credential_id,
            ),
        )
        .filter(Document.id.in_(document_ids))
        .all()
    )

    # Get cc_pair to user_file and folder mapping
    cc_pair_to_folder = (
        db_session.query(ConnectorCredentialPair.id, UserFile.folder_id)
        .join(UserFile, UserFile.cc_pair_id == ConnectorCredentialPair.id)
        .filter(
            ConnectorCredentialPair.id.in_(
                [cc_pair_id for _, cc_pair_id in doc_cc_pairs]
            )
        )
        .all()
    )

    # Create mapping from cc_pair_id to folder_id
    cc_pair_to_folder_dict = {
        cc_pair_id: folder_id for cc_pair_id, folder_id in cc_pair_to_folder
    }

    # Create the final result mapping document_id to folder_id
    result: dict[str, int | None] = {doc_id: None for doc_id in document_ids}
    for doc_id, cc_pair_id in doc_cc_pairs:
        if cc_pair_id in cc_pair_to_folder_dict:
            result[doc_id] = cc_pair_to_folder_dict[cc_pair_id]

    return result


def get_user_file_from_id(db_session: Session, user_file_id: int) -> UserFile | None:
    return db_session.query(UserFile).filter(UserFile.id == user_file_id).first()


# def fetch_user_files_for_documents(
# #     document_ids: list[str],
# #     db_session: Session,
# # ) -> dict[str, int | None]:
# #     # Query UserFile objects for the given document_ids
# #     user_files = (
# #         db_session.query(UserFile).filter(UserFile.document_id.in_(document_ids)).all()
# #     )

# #     # Create a dictionary mapping document_ids to UserFile objects
# #     result: dict[str, int | None] = {doc_id: None for doc_id in document_ids}
# #     for user_file in user_files:
# #         result[user_file.document_id] = user_file.id

# #     return result


def upsert_user_folder(
    db_session: Session,
    id: int | None = None,
    user_id: UUID | None = None,
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


def update_user_file_token_count__no_commit(
    user_file_id_to_token_count: dict[int, int | None],
    db_session: Session,
) -> None:
    for user_file_id, token_count in user_file_id_to_token_count.items():
        db_session.query(UserFile).filter(UserFile.id == user_file_id).update(
            {UserFile.token_count: token_count}
        )
