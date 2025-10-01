import io
import time
from datetime import datetime
from datetime import timedelta
from typing import List

import requests
import sqlalchemy.exc
from bs4 import BeautifulSoup
from fastapi import APIRouter
from fastapi import Depends
from fastapi import File
from fastapi import Form
from fastapi import HTTPException
from fastapi import Query
from fastapi import UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from onyx.auth.users import current_user
from onyx.configs.constants import DocumentSource
from onyx.connectors.models import InputType
from onyx.db.connector import create_connector
from onyx.db.connector_credential_pair import add_credential_to_connector
from onyx.db.credentials import create_credential
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import AccessType
from onyx.db.enums import ConnectorCredentialPairStatus
from onyx.db.models import ConnectorCredentialPair
from onyx.db.models import User
from onyx.db.models import UserFile
from onyx.db.models import UserFolder
from onyx.db.user_documents import calculate_user_files_token_count
from onyx.db.user_documents import create_user_files
from onyx.db.user_documents import get_user_file_indexing_status
from onyx.db.user_documents import share_file_with_assistant
from onyx.db.user_documents import share_folder_with_assistant
from onyx.db.user_documents import unshare_file_with_assistant
from onyx.db.user_documents import unshare_folder_with_assistant
from onyx.db.user_documents import upload_files_to_user_files_with_indexing
from onyx.file_processing.html_utils import web_html_cleanup
from onyx.server.documents.connector import trigger_indexing_for_cc_pair
from onyx.server.documents.models import ConnectorBase
from onyx.server.documents.models import CredentialBase
from onyx.server.query_and_chat.chat_backend import RECENT_DOCS_FOLDER_ID
from onyx.server.user_documents.models import MessageResponse
from onyx.server.user_documents.models import UserFileSnapshot
from onyx.server.user_documents.models import UserFolderSnapshot
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()

router = APIRouter()


class FolderCreationRequest(BaseModel):
    name: str
    description: str


@router.post("/user/folder")
def create_folder(
    request: FolderCreationRequest,
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> UserFolderSnapshot:
    try:
        new_folder = UserFolder(
            user_id=user.id if user else None,
            name=request.name,
            description=request.description,
        )
        db_session.add(new_folder)
        db_session.commit()
        return UserFolderSnapshot.from_model(new_folder)
    except sqlalchemy.exc.DataError as e:
        if "StringDataRightTruncation" in str(e):
            raise HTTPException(
                status_code=400,
                detail="Folder name or description is too long. Please use a shorter name or description.",
            )
        raise


@router.get(
    "/user/folder",
)
def user_get_folders(
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> list[UserFolderSnapshot]:
    user_id = user.id if user else None
    # Get folders that belong to the user or have the RECENT_DOCS_FOLDER_ID
    folders = (
        db_session.query(UserFolder)
        .filter(
            (UserFolder.user_id == user_id) | (UserFolder.id == RECENT_DOCS_FOLDER_ID)
        )
        .all()
    )

    # For each folder, filter files to only include those belonging to the current user
    result = []
    for folder in folders:
        folder_snapshot = UserFolderSnapshot.from_model(folder)
        folder_snapshot.files = [
            file for file in folder_snapshot.files if file.user_id == user_id
        ]
        result.append(folder_snapshot)

    return result


@router.get("/user/folder/{folder_id}")
def get_folder(
    folder_id: int,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> UserFolderSnapshot:
    user_id = user.id if user else None
    folder = (
        db_session.query(UserFolder)
        .filter(
            UserFolder.id == folder_id,
            (
                (UserFolder.user_id == user_id)
                | (UserFolder.id == RECENT_DOCS_FOLDER_ID)
            ),
        )
        .first()
    )
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")

    folder_snapshot = UserFolderSnapshot.from_model(folder)
    # Filter files to only include those belonging to the current user
    folder_snapshot.files = [
        file for file in folder_snapshot.files if file.user_id == user_id
    ]

    return folder_snapshot


@router.post("/user/file/upload")
def upload_user_files(
    files: List[UploadFile] = File(...),
    folder_id: int | None = Form(None),
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> list[UserFileSnapshot]:
    if folder_id == 0:
        folder_id = None

    try:
        # Use our consolidated function that handles indexing properly
        user_files = upload_files_to_user_files_with_indexing(
            files, folder_id or RECENT_DOCS_FOLDER_ID, user, db_session
        )

        return [UserFileSnapshot.from_model(user_file) for user_file in user_files]

    except Exception as e:
        logger.error(f"Error uploading files: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to upload files: {str(e)}")


class FolderUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None


@router.put("/user/folder/{folder_id}")
def update_folder(
    folder_id: int,
    request: FolderUpdateRequest,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> UserFolderSnapshot:
    user_id = user.id if user else None
    folder = (
        db_session.query(UserFolder)
        .filter(UserFolder.id == folder_id, UserFolder.user_id == user_id)
        .first()
    )
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")
    if request.name:
        folder.name = request.name
    if request.description:
        folder.description = request.description
    db_session.commit()

    return UserFolderSnapshot.from_model(folder)


@router.delete("/user/folder/{folder_id}")
def delete_folder(
    folder_id: int,
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> MessageResponse:
    user_id = user.id if user else None
    folder = (
        db_session.query(UserFolder)
        .filter(UserFolder.id == folder_id, UserFolder.user_id == user_id)
        .first()
    )
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")
    db_session.delete(folder)
    db_session.commit()
    return MessageResponse(message="Folder deleted successfully")


@router.delete("/user/file/{file_id}")
def delete_file(
    file_id: int,
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> MessageResponse:
    user_id = user.id if user else None
    file = (
        db_session.query(UserFile)
        .filter(UserFile.id == file_id, UserFile.user_id == user_id)
        .first()
    )
    if not file:
        raise HTTPException(status_code=404, detail="File not found")
    db_session.delete(file)
    db_session.commit()
    return MessageResponse(message="File deleted successfully")


class FileMoveRequest(BaseModel):
    new_folder_id: int | None


@router.put("/user/file/{file_id}/move")
def move_file(
    file_id: int,
    request: FileMoveRequest,
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> UserFileSnapshot:
    user_id = user.id if user else None
    file = (
        db_session.query(UserFile)
        .filter(UserFile.id == file_id, UserFile.user_id == user_id)
        .first()
    )
    if not file:
        raise HTTPException(status_code=404, detail="File not found")
    file.folder_id = request.new_folder_id
    db_session.commit()
    return UserFileSnapshot.from_model(file)


@router.get("/user/file-system")
def get_file_system(
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> list[UserFolderSnapshot]:
    user_id = user.id if user else None
    folders = db_session.query(UserFolder).filter(UserFolder.user_id == user_id).all()
    return [UserFolderSnapshot.from_model(folder) for folder in folders]


@router.put("/user/file/{file_id}/rename")
def rename_file(
    file_id: int,
    name: str,
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> UserFileSnapshot:
    user_id = user.id if user else None
    file = (
        db_session.query(UserFile)
        .filter(UserFile.id == file_id, UserFile.user_id == user_id)
        .first()
    )
    if not file:
        raise HTTPException(status_code=404, detail="File not found")
    file.name = name
    db_session.commit()
    return UserFileSnapshot.from_model(file)


class ShareRequest(BaseModel):
    assistant_id: int


@router.post("/user/file/{file_id}/share")
def share_file(
    file_id: int,
    request: ShareRequest,
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> MessageResponse:
    user_id = user.id if user else None
    file = (
        db_session.query(UserFile)
        .filter(UserFile.id == file_id, UserFile.user_id == user_id)
        .first()
    )
    if not file:
        raise HTTPException(status_code=404, detail="File not found")

    share_file_with_assistant(file_id, request.assistant_id, db_session)
    return MessageResponse(message="File shared successfully with the assistant")


@router.post("/user/file/{file_id}/unshare")
def unshare_file(
    file_id: int,
    request: ShareRequest,
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> MessageResponse:
    user_id = user.id if user else None
    file = (
        db_session.query(UserFile)
        .filter(UserFile.id == file_id, UserFile.user_id == user_id)
        .first()
    )
    if not file:
        raise HTTPException(status_code=404, detail="File not found")

    unshare_file_with_assistant(file_id, request.assistant_id, db_session)
    return MessageResponse(message="File unshared successfully from the assistant")


@router.post("/user/folder/{folder_id}/share")
def share_folder(
    folder_id: int,
    request: ShareRequest,
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> MessageResponse:
    user_id = user.id if user else None
    folder = (
        db_session.query(UserFolder)
        .filter(UserFolder.id == folder_id, UserFolder.user_id == user_id)
        .first()
    )
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")

    share_folder_with_assistant(folder_id, request.assistant_id, db_session)
    return MessageResponse(
        message="Folder and its files shared successfully with the assistant"
    )


@router.post("/user/folder/{folder_id}/unshare")
def unshare_folder(
    folder_id: int,
    request: ShareRequest,
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> MessageResponse:
    user_id = user.id if user else None
    folder = (
        db_session.query(UserFolder)
        .filter(UserFolder.id == folder_id, UserFolder.user_id == user_id)
        .first()
    )
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")

    unshare_folder_with_assistant(folder_id, request.assistant_id, db_session)
    return MessageResponse(
        message="Folder and its files unshared successfully from the assistant"
    )


class CreateFileFromLinkRequest(BaseModel):
    url: str
    folder_id: int | None


@router.post("/user/file/create-from-link")
def create_file_from_link(
    request: CreateFileFromLinkRequest,
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> list[UserFileSnapshot]:
    try:
        response = requests.get(request.url)
        response.raise_for_status()
        content = response.text
        soup = BeautifulSoup(content, "html.parser")
        parsed_html = web_html_cleanup(soup, mintlify_cleanup_enabled=False)

        file_name = f"{parsed_html.title or 'Untitled'}.txt"
        file_content = parsed_html.cleaned_text.encode()

        file = UploadFile(filename=file_name, file=io.BytesIO(file_content))
        user_files = create_user_files(
            [file], request.folder_id or -1, user, db_session, link_url=request.url
        )

        # Create connector and credential (same as in upload_user_files)
        for user_file in user_files:
            connector_base = ConnectorBase(
                name=f"UserFile-{user_file.file_id}-{int(time.time())}",
                source=DocumentSource.FILE,
                input_type=InputType.LOAD_STATE,
                connector_specific_config={
                    "file_locations": [user_file.file_id],
                    "file_names": [user_file.name],
                    "zip_metadata": {},
                },
                refresh_freq=None,
                prune_freq=None,
                indexing_start=None,
            )

            connector = create_connector(
                db_session=db_session,
                connector_data=connector_base,
            )

            credential_info = CredentialBase(
                credential_json={},
                admin_public=True,
                source=DocumentSource.FILE,
                curator_public=True,
                groups=[],
                name=f"UserFileCredential-{user_file.file_id}-{int(time.time())}",
            )
            credential = create_credential(credential_info, user, db_session)

            cc_pair = add_credential_to_connector(
                db_session=db_session,
                user=user,
                connector_id=connector.id,
                credential_id=credential.id,
                cc_pair_name=f"UserFileCCPair-{int(time.time())}",
                access_type=AccessType.PRIVATE,
                auto_sync_options=None,
                groups=[],
                is_user_file=True,
            )
            user_file.cc_pair_id = cc_pair.data
            db_session.commit()

            # Trigger immediate indexing with highest priority
            tenant_id = get_current_tenant_id()
            trigger_indexing_for_cc_pair(
                [], connector.id, False, tenant_id, db_session, is_user_file=True
            )

        db_session.commit()
        return [UserFileSnapshot.from_model(user_file) for user_file in user_files]
    except requests.RequestException as e:
        raise HTTPException(status_code=400, detail=f"Failed to fetch URL: {str(e)}")


@router.get("/user/file/indexing-status")
def get_files_indexing_status(
    file_ids: list[int] = Query(...),
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> dict[int, bool]:
    """Get indexing status for multiple files"""
    return get_user_file_indexing_status(file_ids, db_session)


@router.get("/user/file/token-estimate")
def get_files_token_estimate(
    file_ids: list[int] = Query([]),
    folder_ids: list[int] = Query([]),
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> dict:
    """Get token estimate for files and folders"""
    total_tokens = calculate_user_files_token_count(file_ids, folder_ids, db_session)
    return {"total_tokens": total_tokens}


class ReindexFileRequest(BaseModel):
    file_id: int


@router.post("/user/file/reindex")
def reindex_file(
    request: ReindexFileRequest,
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> MessageResponse:
    user_id = user.id if user else None
    user_file_to_reindex = (
        db_session.query(UserFile)
        .filter(UserFile.id == request.file_id, UserFile.user_id == user_id)
        .first()
    )

    if not user_file_to_reindex:
        raise HTTPException(status_code=404, detail="File not found")

    if not user_file_to_reindex.cc_pair_id:
        raise HTTPException(
            status_code=400,
            detail="File does not have an associated connector-credential pair",
        )

    # Get the connector id from the cc_pair
    cc_pair = (
        db_session.query(ConnectorCredentialPair)
        .filter_by(id=user_file_to_reindex.cc_pair_id)
        .first()
    )
    if not cc_pair:
        raise HTTPException(
            status_code=404, detail="Associated connector-credential pair not found"
        )

    # Trigger immediate reindexing with highest priority
    tenant_id = get_current_tenant_id()
    # Update the cc_pair status to ACTIVE to ensure it's processed
    cc_pair.status = ConnectorCredentialPairStatus.ACTIVE
    db_session.commit()
    try:
        trigger_indexing_for_cc_pair(
            [], cc_pair.connector_id, True, tenant_id, db_session, is_user_file=True
        )
        return MessageResponse(
            message="File reindexing has been triggered successfully"
        )
    except Exception as e:
        logger.error(
            f"Error triggering reindexing for file {request.file_id}: {str(e)}"
        )
        raise HTTPException(
            status_code=500, detail=f"Failed to trigger reindexing: {str(e)}"
        )


class BulkCleanupRequest(BaseModel):
    folder_id: int
    days_older_than: int | None = None


@router.post("/user/file/bulk-cleanup")
def bulk_cleanup_files(
    request: BulkCleanupRequest,
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> MessageResponse:
    """Bulk delete files older than specified days in a folder"""
    user_id = user.id if user else None

    logger.info(
        f"Bulk cleanup request: folder_id={request.folder_id}, days_older_than={request.days_older_than}"
    )

    # Check if folder exists
    if request.folder_id != RECENT_DOCS_FOLDER_ID:
        folder = (
            db_session.query(UserFolder)
            .filter(UserFolder.id == request.folder_id, UserFolder.user_id == user_id)
            .first()
        )
        if not folder:
            raise HTTPException(status_code=404, detail="Folder not found")

    filter_criteria = [UserFile.user_id == user_id]

    # Filter by folder
    if request.folder_id != -2:  # -2 means all folders
        filter_criteria.append(UserFile.folder_id == request.folder_id)

    # Filter by date if days_older_than is provided
    if request.days_older_than is not None:
        cutoff_date = datetime.utcnow() - timedelta(days=request.days_older_than)
        logger.info(f"Filtering files older than {cutoff_date} (UTC)")
        filter_criteria.append(UserFile.created_at < cutoff_date)

    # Get all files matching the criteria
    files_to_delete = db_session.query(UserFile).filter(*filter_criteria).all()

    logger.info(f"Found {len(files_to_delete)} files to delete")

    # Delete files
    delete_count = 0
    for file in files_to_delete:
        logger.debug(
            f"Deleting file: id={file.id}, name={file.name}, created_at={file.created_at}"
        )
        db_session.delete(file)
        delete_count += 1

    db_session.commit()

    return MessageResponse(message=f"Successfully deleted {delete_count} files")
