"""API endpoints for User Library file management in Craft."""

import mimetypes
import re
import zipfile
from datetime import datetime
from datetime import timezone
from io import BytesIO

from fastapi import APIRouter
from fastapi import Depends
from fastapi import File
from fastapi import Form
from fastapi import UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from onyx.auth.permissions import require_permission
from onyx.configs.app_configs import MAX_EMBEDDED_IMAGES_PER_FILE
from onyx.configs.app_configs import MAX_EMBEDDED_IMAGES_PER_UPLOAD
from onyx.db.connector_credential_pair import update_connector_credential_pair
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import ConnectorCredentialPairStatus
from onyx.db.enums import Permission
from onyx.db.models import User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.file_processing.extract_file_text import count_pdf_embedded_images
from onyx.server.features.build.configs import USER_LIBRARY_MAX_FILE_SIZE_BYTES
from onyx.server.features.build.configs import USER_LIBRARY_MAX_FILES_PER_UPLOAD
from onyx.server.features.build.configs import USER_LIBRARY_MAX_TOTAL_SIZE_BYTES
from onyx.server.features.build.db.user_library import cleanup_old_blobs
from onyx.server.features.build.db.user_library import create_directory_record
from onyx.server.features.build.db.user_library import delete_user_file
from onyx.server.features.build.db.user_library import fetch_user_file_for_user
from onyx.server.features.build.db.user_library import get_or_create_craft_connector
from onyx.server.features.build.db.user_library import get_user_storage_bytes
from onyx.server.features.build.db.user_library import list_user_files
from onyx.server.features.build.db.user_library import store_user_file
from onyx.server.features.build.sandbox.user_library import (
    sync_user_library_to_active_sandboxes,
)
from onyx.server.features.build.utils import sanitize_filename as api_sanitize_filename
from onyx.utils.logger import setup_logger

logger = setup_logger()

router = APIRouter(prefix="/user-library")


class LibraryEntryResponse(BaseModel):
    id: str  # document_id
    name: str
    path: str
    is_directory: bool
    file_size: int | None
    mime_type: str | None
    sync_enabled: bool
    created_at: datetime
    children: list["LibraryEntryResponse"] | None = None


class CreateDirectoryRequest(BaseModel):
    name: str
    parent_path: str = "/"


class UploadResponse(BaseModel):
    entries: list[LibraryEntryResponse]
    total_uploaded: int
    total_size_bytes: int


class DeleteFileResponse(BaseModel):
    success: bool
    deleted: str


def _looks_like_pdf(filename: str, content_type: str | None) -> bool:
    """True if either the filename or the content-type indicates a PDF.

    Falls back to extension-based detection because client-supplied
    content_type can be wrong (e.g. ``application/octet-stream``).
    """
    if content_type == "application/pdf":
        return True
    guessed, _ = mimetypes.guess_type(filename)
    return guessed == "application/pdf"


def _check_pdf_image_caps(
    filename: str, content: bytes, content_type: str | None, batch_total: int
) -> int:
    """Return embedded image count (0 for non-PDFs); raises on cap violation."""
    if not _looks_like_pdf(filename, content_type):
        return 0
    file_cap = MAX_EMBEDDED_IMAGES_PER_FILE
    batch_cap = MAX_EMBEDDED_IMAGES_PER_UPLOAD
    # Short-circuit at the larger cap so we get a useful count for both checks.
    count = count_pdf_embedded_images(BytesIO(content), max(file_cap, batch_cap))
    if count > file_cap:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"PDF '{filename}' contains too many embedded images "
            f"(more than {file_cap}). Try splitting the document into smaller files.",
        )
    if batch_total + count > batch_cap:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"Upload would exceed the {batch_cap}-image limit across all "
            f"files in this batch. Try uploading fewer image-heavy files at once.",
        )
    return count


def _sanitize_path(path: str) -> str:
    """Remove traversal segments and non-whitelisted characters, returning a /-prefixed path."""
    parts = path.split("/")
    sanitized_parts: list[str] = []
    for part in parts:
        if not part or part == ".." or part == ".":
            continue
        cleaned = re.sub(r"[^a-zA-Z0-9\-_. ]", "", part)
        if cleaned:
            sanitized_parts.append(cleaned)
    return "/" + "/".join(sanitized_parts)


def _validate_zip_contents(
    zip_file: zipfile.ZipFile,
    existing_usage: int,
) -> None:
    """Check file count limit and total decompressed size against storage quota."""
    if len(zip_file.namelist()) > USER_LIBRARY_MAX_FILES_PER_UPLOAD:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"Zip contains too many files. Maximum is {USER_LIBRARY_MAX_FILES_PER_UPLOAD}.",
        )

    # Zip bomb protection: check total decompressed size before extracting
    declared_total = sum(
        info.file_size for info in zip_file.infolist() if not info.is_dir()
    )
    if existing_usage + declared_total > USER_LIBRARY_MAX_TOTAL_SIZE_BYTES:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"Zip decompressed size ({declared_total // (1024 * 1024)}MB) would exceed storage limit.",
        )


@router.get("/tree")
def get_library_tree(
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> list[LibraryEntryResponse]:
    """Get user's uploaded files as a tree structure."""
    user_docs = list_user_files(db_session, user.id)

    entries: list[LibraryEntryResponse] = []
    now = datetime.now(timezone.utc)
    for doc in user_docs:
        doc_metadata = doc.doc_metadata or {}
        entries.append(
            LibraryEntryResponse(
                id=doc.id,
                name=doc.semantic_id.split("/")[-1] if doc.semantic_id else "unknown",
                path=doc.semantic_id or "",
                is_directory=doc_metadata.get("is_directory", False),
                file_size=doc_metadata.get("file_size"),
                mime_type=doc_metadata.get("mime_type"),
                sync_enabled=not doc_metadata.get("sync_disabled", False),
                created_at=doc.last_modified or now,
            )
        )

    return entries


@router.post("/upload")
async def upload_files(
    files: list[UploadFile] = File(...),
    path: str = Form("/"),
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> UploadResponse:
    """Upload files as raw binary (no text extraction) for sandbox access."""
    if len(files) > USER_LIBRARY_MAX_FILES_PER_UPLOAD:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"Too many files. Maximum is {USER_LIBRARY_MAX_FILES_PER_UPLOAD} per upload.",
        )

    existing_usage = get_user_storage_bytes(db_session, user.id)
    connector_id, credential_id = get_or_create_craft_connector(db_session, user)

    uploaded_entries: list[LibraryEntryResponse] = []
    stale_blobs: list[str | None] = []
    total_size = 0
    batch_image_total = 0
    now = datetime.now(timezone.utc)

    base_path = _sanitize_path(path)

    for file in files:
        content = await file.read()
        file_size = len(content)

        if file_size > USER_LIBRARY_MAX_FILE_SIZE_BYTES:
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                f"File '{file.filename}' exceeds maximum size of {USER_LIBRARY_MAX_FILE_SIZE_BYTES // (1024 * 1024)}MB",
            )

        batch_image_total += _check_pdf_image_caps(
            filename=file.filename or "unnamed",
            content=content,
            content_type=file.content_type,
            batch_total=batch_image_total,
        )

        total_size += file_size
        if existing_usage + total_size > USER_LIBRARY_MAX_TOTAL_SIZE_BYTES:
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                f"Total storage would exceed maximum of {USER_LIBRARY_MAX_TOTAL_SIZE_BYTES // (1024 * 1024 * 1024)}GB",
            )

        safe_filename = api_sanitize_filename(file.filename or "unnamed")
        file_path = f"{base_path}/{safe_filename}".replace("//", "/")

        doc_id, _, old_blob = store_user_file(
            db_session=db_session,
            user_id=user.id,
            connector_id=connector_id,
            credential_id=credential_id,
            file_path=file_path,
            content=content,
            mime_type=file.content_type or "application/octet-stream",
        )
        stale_blobs.append(old_blob)

        uploaded_entries.append(
            LibraryEntryResponse(
                id=doc_id,
                name=safe_filename,
                path=file_path,
                is_directory=False,
                file_size=file_size,
                mime_type=file.content_type,
                sync_enabled=True,
                created_at=now,
            )
        )

    update_connector_credential_pair(
        db_session=db_session,
        connector_id=connector_id,
        credential_id=credential_id,
        status=ConnectorCredentialPairStatus.ACTIVE,
        net_docs=len(uploaded_entries),
        run_dt=now,
    )

    db_session.commit()
    cleanup_old_blobs(stale_blobs)

    logger.info(
        "Uploaded %s files (%s bytes) for user %s",
        len(uploaded_entries),
        total_size,
        user.id,
    )

    sync_user_library_to_active_sandboxes(user.id, db_session)

    return UploadResponse(
        entries=uploaded_entries,
        total_uploaded=len(uploaded_entries),
        total_size_bytes=total_size,
    )


@router.post("/upload-zip")
async def upload_zip(
    file: UploadFile = File(...),
    path: str = Form("/"),
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> UploadResponse:
    """Upload and extract a zip file, preserving directory structure."""
    content = await file.read()
    if len(content) > USER_LIBRARY_MAX_TOTAL_SIZE_BYTES:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"Zip file exceeds maximum size of {USER_LIBRARY_MAX_TOTAL_SIZE_BYTES // (1024 * 1024 * 1024)}GB",
        )

    existing_usage = get_user_storage_bytes(db_session, user.id)
    connector_id, credential_id = get_or_create_craft_connector(db_session, user)

    uploaded_entries: list[LibraryEntryResponse] = []
    stale_blobs: list[str | None] = []
    total_size = 0
    batch_image_total = 0

    zip_name = api_sanitize_filename(file.filename or "upload")
    if zip_name.lower().endswith(".zip"):
        zip_name = zip_name[:-4]
    folder_path = f"{_sanitize_path(path)}/{zip_name}".replace("//", "/")
    base_path = folder_path

    now = datetime.now(timezone.utc)

    directory_paths: set[str] = set()

    try:
        with zipfile.ZipFile(BytesIO(content), "r") as zip_file:
            _validate_zip_contents(zip_file, existing_usage)

            for zip_info in zip_file.infolist():
                if (
                    zip_info.filename.startswith("__MACOSX")
                    or "/." in zip_info.filename
                ):
                    continue

                if zip_info.is_dir():
                    continue

                file_content = zip_file.read(zip_info.filename)
                file_size = len(file_content)

                if file_size > USER_LIBRARY_MAX_FILE_SIZE_BYTES:
                    logger.warning(
                        "Skipping '%s' - exceeds max size", zip_info.filename
                    )
                    continue

                zip_file_name = zip_info.filename.split("/")[-1]
                zip_content_type, _ = mimetypes.guess_type(zip_file_name)
                if zip_content_type == "application/pdf":
                    image_count = count_pdf_embedded_images(
                        BytesIO(file_content),
                        max(
                            MAX_EMBEDDED_IMAGES_PER_FILE,
                            MAX_EMBEDDED_IMAGES_PER_UPLOAD,
                        ),
                    )
                    if image_count > MAX_EMBEDDED_IMAGES_PER_FILE:
                        logger.warning(
                            "Skipping '%s' - exceeds %d per-file embedded-image cap",
                            zip_info.filename,
                            MAX_EMBEDDED_IMAGES_PER_FILE,
                        )
                        continue
                    if batch_image_total + image_count > MAX_EMBEDDED_IMAGES_PER_UPLOAD:
                        logger.warning(
                            "Skipping '%s' - would exceed %d per-batch embedded-image cap",
                            zip_info.filename,
                            MAX_EMBEDDED_IMAGES_PER_UPLOAD,
                        )
                        continue
                    batch_image_total += image_count

                total_size += file_size

                if existing_usage + total_size > USER_LIBRARY_MAX_TOTAL_SIZE_BYTES:
                    raise OnyxError(
                        OnyxErrorCode.INVALID_INPUT,
                        f"Total storage would exceed maximum of {USER_LIBRARY_MAX_TOTAL_SIZE_BYTES // (1024 * 1024 * 1024)}GB",
                    )

                sanitized_zip_path = _sanitize_path(zip_info.filename)
                file_path = f"{base_path}{sanitized_zip_path}".replace("//", "/")
                file_name = file_path.split("/")[-1]

                parts = file_path.split("/")
                # Start at 2 to skip the leading empty string + root segment
                for i in range(2, len(parts)):
                    directory_paths.add("/".join(parts[:i]))

                content_type, _ = mimetypes.guess_type(file_name)

                doc_id, _, old_blob = store_user_file(
                    db_session=db_session,
                    user_id=user.id,
                    connector_id=connector_id,
                    credential_id=credential_id,
                    file_path=file_path,
                    content=file_content,
                    mime_type=content_type or "application/octet-stream",
                )
                stale_blobs.append(old_blob)

                uploaded_entries.append(
                    LibraryEntryResponse(
                        id=doc_id,
                        name=file_name,
                        path=file_path,
                        is_directory=False,
                        file_size=file_size,
                        mime_type=content_type,
                        sync_enabled=True,
                        created_at=now,
                    )
                )

    except zipfile.BadZipFile:
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, "Invalid zip file")

    for dir_path in sorted(directory_paths):
        create_directory_record(
            db_session=db_session,
            user_id=user.id,
            connector_id=connector_id,
            credential_id=credential_id,
            dir_path=dir_path,
        )

    update_connector_credential_pair(
        db_session=db_session,
        connector_id=connector_id,
        credential_id=credential_id,
        status=ConnectorCredentialPairStatus.ACTIVE,
        net_docs=len(uploaded_entries),
        run_dt=now,
    )

    db_session.commit()
    cleanup_old_blobs(stale_blobs)

    logger.info(
        "Extracted %s files (%s bytes) from zip for user %s",
        len(uploaded_entries),
        total_size,
        user.id,
    )

    sync_user_library_to_active_sandboxes(user.id, db_session)

    return UploadResponse(
        entries=uploaded_entries,
        total_uploaded=len(uploaded_entries),
        total_size_bytes=total_size,
    )


@router.post("/directories")
def create_directory(
    request: CreateDirectoryRequest,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> LibraryEntryResponse:
    """Create a virtual directory (document record only, no S3 object)."""
    connector_id, credential_id = get_or_create_craft_connector(db_session, user)

    parent_path = _sanitize_path(request.parent_path)
    safe_name = api_sanitize_filename(request.name)
    dir_path = f"{parent_path}/{safe_name}".replace("//", "/")

    doc_id = create_directory_record(
        db_session=db_session,
        user_id=user.id,
        connector_id=connector_id,
        credential_id=credential_id,
        dir_path=dir_path,
    )
    db_session.commit()

    return LibraryEntryResponse(
        id=doc_id,
        name=safe_name,
        path=dir_path,
        is_directory=True,
        file_size=None,
        mime_type=None,
        sync_enabled=True,
        created_at=datetime.now(timezone.utc),
    )


@router.delete("/files/{document_id}")
def delete_file(
    document_id: str,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> DeleteFileResponse:
    """Delete a file from the file store and the document table."""
    doc = fetch_user_file_for_user(db_session, document_id, user.id)
    delete_user_file(db_session, doc)
    db_session.commit()

    sync_user_library_to_active_sandboxes(user.id, db_session)

    return DeleteFileResponse(success=True, deleted=document_id)
