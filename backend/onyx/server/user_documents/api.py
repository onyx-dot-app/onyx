import io
import time
from typing import List

import requests
import sqlalchemy.exc
from bs4 import BeautifulSoup
from fastapi import APIRouter
from fastapi import Depends
from fastapi import File
from fastapi import Form
from fastapi import HTTPException
from fastapi import UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from onyx.auth.users import current_user
from onyx.configs.constants import DocumentSource
from onyx.connectors.models import InputType
from onyx.db.connector import create_connector
from onyx.db.connector_credential_pair import add_credential_to_connector
from onyx.db.credentials import create_credential
from onyx.db.engine import get_session
from onyx.db.enums import AccessType
from onyx.db.models import User
from onyx.db.models import UserFile
from onyx.db.models import UserFolder
from onyx.db.user_documents import create_user_files
from onyx.db.user_documents import share_file_with_assistant
from onyx.db.user_documents import share_folder_with_assistant
from onyx.db.user_documents import unshare_file_with_assistant
from onyx.db.user_documents import unshare_folder_with_assistant
from onyx.file_processing.html_utils import web_html_cleanup
from onyx.server.documents.models import ConnectorBase
from onyx.server.documents.models import CredentialBase
from onyx.server.documents.models import FileUploadResponse
from onyx.server.user_documents.models import MessageResponse
from onyx.server.user_documents.models import UserFileSnapshot
from onyx.server.user_documents.models import UserFolderSnapshot

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
def get_folders(
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> list[UserFolderSnapshot]:
    user_id = user.id if user else None
    folders = db_session.query(UserFolder).filter(UserFolder.user_id == user_id).all()
    return [UserFolderSnapshot.from_model(folder) for folder in folders]


@router.get("/user/folder/{folder_id}")
def get_folder(
    folder_id: int,
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

    return UserFolderSnapshot.from_model(folder)


RECENT_DOCS_FOLDER_ID = -1


@router.post("/user/file/upload")
def upload_user_files(
    files: List[UploadFile] = File(...),
    folder_id: int | None = Form(None),
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> FileUploadResponse:
    if folder_id == 0:
        folder_id = None

    user_files = create_user_files(files, folder_id, user, db_session)
    for user_file in user_files:
        connector_base = ConnectorBase(
            name=f"UserFile-{user_file.file_id}-{int(time.time())}",
            source=DocumentSource.FILE,
            input_type=InputType.LOAD_STATE,
            connector_specific_config={
                "file_locations": [user_file.file_id],
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
            is_user_file=True,
        )
        credential = create_credential(credential_info, user, db_session)

        cc_pair = add_credential_to_connector(
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
        user_file.cc_pair_id = cc_pair.data
        print("A")
        db_session.commit()

    db_session.commit()
    # TODO: functional document indexing
    # trigger_document_indexing(db_session, user.id)
    return FileUploadResponse(
        file_paths=[user_file.file_id for user_file in user_files],
    )


@router.put("/user/folder/{folder_id}")
def update_folder(
    folder_id: int,
    name: str,
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
    folder.name = name

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
) -> FileUploadResponse:
    try:
        response = requests.get(request.url)
        response.raise_for_status()
        content = response.text
        soup = BeautifulSoup(content, "html.parser")
        parsed_html = web_html_cleanup(soup, mintlify_cleanup_enabled=False)

        file_name = f"{parsed_html.title or 'Untitled'}.txt"
        file_content = parsed_html.cleaned_text.encode()

        file = UploadFile(filename=file_name, file=io.BytesIO(file_content))
        user_files = create_user_files([file], request.folder_id, user, db_session)

        # Create connector and credential (same as in upload_user_files)
        for user_file in user_files:
            connector_base = ConnectorBase(
                name=f"UserFile-{user_file.file_id}-{int(time.time())}",
                source=DocumentSource.FILE,
                input_type=InputType.LOAD_STATE,
                connector_specific_config={
                    "file_locations": [user_file.file_id],
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

        db_session.commit()
        return FileUploadResponse(
            file_paths=[user_file.file_id for user_file in user_files]
        )
    except requests.RequestException as e:
        raise HTTPException(status_code=400, detail=f"Failed to fetch URL: {str(e)}")
