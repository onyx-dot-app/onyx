"""API endpoints for User Library file management in Craft.

This module provides endpoints for uploading and managing raw binary files
(xlsx, pptx, docx, csv, etc.) that are stored directly in S3 for sandbox access.

Files are stored at:
    s3://{bucket}/{tenant_id}/knowledge/{user_id}/user_library/{path}

And synced to sandbox at:
    /workspace/files/user_library/{path}

Known Issues / TODOs:
    - Memory: Upload endpoints read entire file content into memory (up to 500MB).
      Should be refactored to stream uploads directly to S3 via multipart upload
      for better memory efficiency under concurrent load.
    - Transaction safety: Multi-file uploads are not atomic. If the endpoint fails
      mid-batch (e.g., file 3 of 5 exceeds storage quota), files 1-2 are already
      persisted to S3 and DB. A partial upload is not catastrophic but the response
      implies atomicity that doesn't exist.
"""

import hashlib
import mimetypes
import re
import zipfile
from datetime import datetime
from datetime import timezone
from io import BytesIO
from typing import Any

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
from onyx.background.celery.versioned_apps.client import app as celery_app
from onyx.configs.constants import DocumentSource
from onyx.configs.constants import OnyxCeleryQueues
from onyx.configs.constants import OnyxCeleryTask
from onyx.db.connector_credential_pair import update_connector_credential_pair
from onyx.db.document import upsert_document_by_connector_credential_pair
from onyx.db.document import upsert_documents
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import ConnectorCredentialPairStatus
from onyx.db.models import User
from onyx.document_index.interfaces import DocumentMetadata
from onyx.server.features.build.configs import USER_LIBRARY_MAX_FILE_SIZE_BYTES
from onyx.server.features.build.configs import USER_LIBRARY_MAX_FILES_PER_UPLOAD
from onyx.server.features.build.configs import USER_LIBRARY_MAX_TOTAL_SIZE_BYTES
from onyx.server.features.build.configs import USER_LIBRARY_SOURCE_DIR
from onyx.server.features.build.db.user_library import get_or_create_craft_connector
from onyx.server.features.build.db.user_library import get_user_storage_bytes
from onyx.server.features.build.indexing.persistent_document_writer import (
    get_persistent_document_writer,
)
from onyx.server.features.build.indexing.persistent_document_writer import (
    PersistentDocumentWriter,
)
from onyx.server.features.build.indexing.persistent_document_writer import (
    S3PersistentDocumentWriter,
)
from onyx.server.features.build.utils import sanitize_filename as api_sanitize_filename
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()

router = APIRouter(prefix="/user-library")


# =============================================================================
# Pydantic Models
# =============================================================================


class LibraryEntryResponse(BaseModel):
    """Response for a single library entry (file or directory)."""

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
    """Request to create a virtual directory."""

    name: str
    parent_path: str = "/"


class UploadResponse(BaseModel):
    """Response after successful file upload."""

    entries: list[LibraryEntryResponse]
    total_uploaded: int
    total_size_bytes: int


class ToggleSyncResponse(BaseModel):
    """Response after toggling file sync."""

    success: bool
    sync_enabled: bool


class DeleteFileResponse(BaseModel):
    """Response after deleting a file."""

    success: bool
    deleted: str


# =============================================================================
# Helper Functions
# =============================================================================


def _sanitize_path(path: str) -> str:
    """Sanitize a file path, removing traversal attempts and normalizing.

    Removes '..' and '.' segments and ensures the path starts with '/'.
    Only allows alphanumeric characters, hyphens, underscores, dots, spaces,
    and forward slashes. All other characters are stripped.
    """
    parts = path.split("/")
    sanitized_parts: list[str] = []
    for p in parts:
        if not p or p == ".." or p == ".":
            continue
        # Strip any character not in the whitelist
        cleaned = re.sub(r"[^a-zA-Z0-9\-_. ]", "", p)
        if cleaned:
            sanitized_parts.append(cleaned)
    return "/" + "/".join(sanitized_parts)


def _build_document_id(user_id: str, path: str) -> str:
    """Build a document ID for a craft file.

    Deterministic: re-uploading the same file to the same path will produce the
    same document ID, allowing upsert to overwrite the previous record.

    Uses a hash of the path to avoid collisions from separator replacement
    (e.g., "/a/b_c" vs "/a_b/c" would collide with naive slash-to-underscore).
    """
    path_hash = hashlib.sha256(path.encode()).hexdigest()[:16]
    return f"CRAFT_FILE__{user_id}__{path_hash}"


def _trigger_sandbox_sync(
    user_id: str, tenant_id: str, source: str | None = None
) -> None:
    """Trigger sandbox file sync task.

    Args:
        user_id: The user ID whose sandbox should be synced
        tenant_id: The tenant ID for S3 path construction
        source: Optional source type (e.g., "user_library"). If specified,
                only syncs that source's directory with --delete flag.
    """
    celery_app.send_task(
        OnyxCeleryTask.SANDBOX_FILE_SYNC,
        kwargs={"user_id": user_id, "tenant_id": tenant_id, "source": source},
        queue=OnyxCeleryQueues.SANDBOX,
    )


def _validate_zip_contents(
    zip_file: zipfile.ZipFile,
    existing_usage: int,
) -> None:
    """Validate zip file contents before extraction.

    Checks file count limit and total decompressed size against storage quota.
    Raises HTTPException on validation failure.
    """
    if len(zip_file.namelist()) > USER_LIBRARY_MAX_FILES_PER_UPLOAD:
        raise HTTPException(
            status_code=400,
            detail=f"Zip contains too many files. Maximum is {USER_LIBRARY_MAX_FILES_PER_UPLOAD}.",
        )

    # Zip bomb protection: check total decompressed size before extracting
    declared_total = sum(
        info.file_size for info in zip_file.infolist() if not info.is_dir()
    )
    if existing_usage + declared_total > USER_LIBRARY_MAX_TOTAL_SIZE_BYTES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Zip decompressed size ({declared_total // (1024*1024)}MB) "
                f"would exceed storage limit."
            ),
        )


def _verify_ownership_and_get_document(
    document_id: str,
    user: User,
    db_session: Session,
) -> Any:
    """Verify the user owns the document and return it.

    Raises HTTPException on authorization failure or if document not found.
    """
    from onyx.db.document import get_document

    user_prefix = f"CRAFT_FILE__{user.id}__"
    if not document_id.startswith(user_prefix):
        raise HTTPException(
            status_code=403, detail="Not authorized to modify this file"
        )

    doc = get_document(document_id, db_session)
    if doc is None:
        raise HTTPException(status_code=404, detail="File not found")

    return doc


def _store_and_track_file(
    *,
    writer: "PersistentDocumentWriter | S3PersistentDocumentWriter",
    file_path: str,
    content: bytes,
    content_type: str | None,
    user_id: str,
    connector_id: int,
    credential_id: int,
    db_session: Session,
) -> tuple[str, str]:
    """Write a file to storage and upsert its document record.

    Returns:
        Tuple of (document_id, storage_key)
    """
    storage_key = writer.write_raw_file(
        path=file_path,
        content=content,
        content_type=content_type,
    )

    doc_id = _build_document_id(user_id, file_path)
    doc_metadata = DocumentMetadata(
        connector_id=connector_id,
        credential_id=credential_id,
        document_id=doc_id,
        semantic_identifier=f"{USER_LIBRARY_SOURCE_DIR}{file_path}",
        first_link=storage_key,
        doc_metadata={
            "storage_key": storage_key,
            "file_path": file_path,
            "file_size": len(content),
            "mime_type": content_type,
            "is_directory": False,
        },
    )
    upsert_documents(db_session, [doc_metadata])
    upsert_document_by_connector_credential_pair(
        db_session, connector_id, credential_id, [doc_id]
    )

    return doc_id, storage_key


# =============================================================================
# API Endpoints
# =============================================================================


@router.get("/tree")
def get_library_tree(
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> list[LibraryEntryResponse]:
    """Get user's uploaded files as a tree structure.

    Returns all CRAFT_FILE documents for the user, organized hierarchically.
    """
    from onyx.db.document import get_documents_by_source

    # Get CRAFT_FILE documents for this user (filtered at SQL level)
    user_docs = get_documents_by_source(
        db_session=db_session,
        source=DocumentSource.CRAFT_FILE,
        creator_id=user.id,
    )

    # Build tree structure
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
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> UploadResponse:
    """Upload files directly to S3 and track in PostgreSQL.

    Files are stored as raw binary (no text extraction) for access by
    the sandbox agent using Python libraries like openpyxl, python-pptx, etc.
    """
    tenant_id = get_current_tenant_id()
    if tenant_id is None:
        raise HTTPException(status_code=500, detail="Tenant ID not found")

    # Validate file count
    if len(files) > USER_LIBRARY_MAX_FILES_PER_UPLOAD:
        raise HTTPException(
            status_code=400,
            detail=f"Too many files. Maximum is {USER_LIBRARY_MAX_FILES_PER_UPLOAD} per upload.",
        )

    # Check cumulative storage usage
    existing_usage = get_user_storage_bytes(db_session, user.id)

    # Get or create connector
    connector_id, credential_id = get_or_create_craft_connector(db_session, user)

    # Get the persistent document writer
    writer = get_persistent_document_writer(
        user_id=str(user.id),
        tenant_id=tenant_id,
    )

    uploaded_entries: list[LibraryEntryResponse] = []
    total_size = 0
    now = datetime.now(timezone.utc)

    # Sanitize the base path
    base_path = _sanitize_path(path)

    for file in files:
        # TODO: Stream directly to S3 via multipart upload instead of reading
        # entire file into memory. With 500MB max file size, this can OOM under
        # concurrent uploads.
        content = await file.read()
        file_size = len(content)

        # Validate individual file size
        if file_size > USER_LIBRARY_MAX_FILE_SIZE_BYTES:
            raise HTTPException(
                status_code=400,
                detail=f"File '{file.filename}' exceeds maximum size of {USER_LIBRARY_MAX_FILE_SIZE_BYTES // (1024*1024)}MB",
            )

        # Validate cumulative storage (existing + this upload batch)
        total_size += file_size
        if existing_usage + total_size > USER_LIBRARY_MAX_TOTAL_SIZE_BYTES:
            raise HTTPException(
                status_code=400,
                detail=f"Total storage would exceed maximum of {USER_LIBRARY_MAX_TOTAL_SIZE_BYTES // (1024*1024*1024)}GB",
            )

        # Sanitize filename
        safe_filename = api_sanitize_filename(file.filename or "unnamed")
        file_path = f"{base_path}/{safe_filename}".replace("//", "/")

        doc_id, _ = _store_and_track_file(
            writer=writer,
            file_path=file_path,
            content=content,
            content_type=file.content_type,
            user_id=str(user.id),
            connector_id=connector_id,
            credential_id=credential_id,
            db_session=db_session,
        )

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

    # Mark connector as having succeeded (sets last_successful_index_time)
    # This allows the demo data toggle to be disabled
    update_connector_credential_pair(
        db_session=db_session,
        connector_id=connector_id,
        credential_id=credential_id,
        status=ConnectorCredentialPairStatus.ACTIVE,
        net_docs=len(uploaded_entries),
        run_dt=now,
    )

    # Trigger sandbox sync for user_library source only
    _trigger_sandbox_sync(str(user.id), tenant_id, source=USER_LIBRARY_SOURCE_DIR)

    logger.info(
        f"Uploaded {len(uploaded_entries)} files ({total_size} bytes) for user {user.id}"
    )

    return UploadResponse(
        entries=uploaded_entries,
        total_uploaded=len(uploaded_entries),
        total_size_bytes=total_size,
    )


@router.post("/upload-zip")
async def upload_zip(
    file: UploadFile = File(...),
    path: str = Form("/"),
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> UploadResponse:
    """Upload and extract a zip file, storing each extracted file to S3.

    Preserves the directory structure from the zip file.
    """
    tenant_id = get_current_tenant_id()
    if tenant_id is None:
        raise HTTPException(status_code=500, detail="Tenant ID not found")

    # Read zip content
    content = await file.read()
    if len(content) > USER_LIBRARY_MAX_TOTAL_SIZE_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"Zip file exceeds maximum size of {USER_LIBRARY_MAX_TOTAL_SIZE_BYTES // (1024*1024*1024)}GB",
        )

    # Check cumulative storage usage
    existing_usage = get_user_storage_bytes(db_session, user.id)

    # Get or create connector
    connector_id, credential_id = get_or_create_craft_connector(db_session, user)

    # Get the persistent document writer
    writer = get_persistent_document_writer(
        user_id=str(user.id),
        tenant_id=tenant_id,
    )

    uploaded_entries: list[LibraryEntryResponse] = []
    total_size = 0

    # Extract zip contents into a subfolder named after the zip file
    zip_name = api_sanitize_filename(file.filename or "upload")
    if zip_name.lower().endswith(".zip"):
        zip_name = zip_name[:-4]
    folder_path = f"{_sanitize_path(path)}/{zip_name}".replace("//", "/")
    base_path = folder_path

    now = datetime.now(timezone.utc)

    # Track all directory paths we need to create records for
    directory_paths: set[str] = set()

    try:
        with zipfile.ZipFile(BytesIO(content), "r") as zip_file:
            _validate_zip_contents(zip_file, existing_usage)

            for zip_info in zip_file.infolist():
                # Skip hidden files and __MACOSX
                if (
                    zip_info.filename.startswith("__MACOSX")
                    or "/." in zip_info.filename
                ):
                    continue

                # Skip directories - we'll create records from file paths below
                if zip_info.is_dir():
                    continue

                # Read file content
                file_content = zip_file.read(zip_info.filename)
                file_size = len(file_content)

                # Validate individual file size
                if file_size > USER_LIBRARY_MAX_FILE_SIZE_BYTES:
                    logger.warning(f"Skipping '{zip_info.filename}' - exceeds max size")
                    continue

                total_size += file_size

                # Validate cumulative storage
                if existing_usage + total_size > USER_LIBRARY_MAX_TOTAL_SIZE_BYTES:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Total storage would exceed maximum of {USER_LIBRARY_MAX_TOTAL_SIZE_BYTES // (1024*1024*1024)}GB",
                    )

                # Build path preserving zip structure
                sanitized_zip_path = _sanitize_path(zip_info.filename)
                file_path = f"{base_path}{sanitized_zip_path}".replace("//", "/")
                file_name = file_path.split("/")[-1]

                # Collect all intermediate directories for this file
                parts = file_path.split("/")
                for i in range(
                    2, len(parts)
                ):  # start at 2 to skip empty + first segment
                    directory_paths.add("/".join(parts[:i]))

                # Guess content type
                content_type, _ = mimetypes.guess_type(file_name)

                doc_id, _ = _store_and_track_file(
                    writer=writer,
                    file_path=file_path,
                    content=file_content,
                    content_type=content_type,
                    user_id=str(user.id),
                    connector_id=connector_id,
                    credential_id=credential_id,
                    db_session=db_session,
                )

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
        raise HTTPException(status_code=400, detail="Invalid zip file")

    # Create directory document records so they appear in the tree view
    if directory_paths:
        dir_doc_ids: list[str] = []
        for dir_path in sorted(directory_paths):
            dir_doc_id = _build_document_id(str(user.id), dir_path)
            dir_doc_ids.append(dir_doc_id)
            dir_metadata = DocumentMetadata(
                connector_id=connector_id,
                credential_id=credential_id,
                document_id=dir_doc_id,
                semantic_identifier=f"{USER_LIBRARY_SOURCE_DIR}{dir_path}",
                first_link="",
                doc_metadata={"is_directory": True},
            )
            upsert_documents(db_session, [dir_metadata])
        upsert_document_by_connector_credential_pair(
            db_session, connector_id, credential_id, dir_doc_ids
        )

    # Mark connector as having succeeded (sets last_successful_index_time)
    # This allows the demo data toggle to be disabled
    update_connector_credential_pair(
        db_session=db_session,
        connector_id=connector_id,
        credential_id=credential_id,
        status=ConnectorCredentialPairStatus.ACTIVE,
        net_docs=len(uploaded_entries),
        run_dt=now,
    )

    # Trigger sandbox sync for user_library source only
    _trigger_sandbox_sync(str(user.id), tenant_id, source=USER_LIBRARY_SOURCE_DIR)

    logger.info(
        f"Extracted {len(uploaded_entries)} files ({total_size} bytes) from zip for user {user.id}"
    )

    return UploadResponse(
        entries=uploaded_entries,
        total_uploaded=len(uploaded_entries),
        total_size_bytes=total_size,
    )


@router.post("/directories")
def create_directory(
    request: CreateDirectoryRequest,
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> LibraryEntryResponse:
    """Create a virtual directory.

    Directories are tracked as documents with is_directory=True.
    No S3 object is created (S3 doesn't have real directories).
    """
    # Get or create connector
    connector_id, credential_id = get_or_create_craft_connector(db_session, user)

    # Build path
    parent_path = _sanitize_path(request.parent_path)
    safe_name = api_sanitize_filename(request.name)
    dir_path = f"{parent_path}/{safe_name}".replace("//", "/")

    # Track in document table
    doc_id = _build_document_id(str(user.id), dir_path)
    doc_metadata = DocumentMetadata(
        connector_id=connector_id,
        credential_id=credential_id,
        document_id=doc_id,
        semantic_identifier=f"{USER_LIBRARY_SOURCE_DIR}{dir_path}",
        first_link="",
        doc_metadata={
            "is_directory": True,
        },
    )
    upsert_documents(db_session, [doc_metadata])
    upsert_document_by_connector_credential_pair(
        db_session, connector_id, credential_id, [doc_id]
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


@router.patch("/files/{document_id}/toggle")
def toggle_file_sync(
    document_id: str,
    enabled: bool = Query(...),
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> ToggleSyncResponse:
    """Enable/disable syncing a file to sandboxes.

    When sync is disabled, the file's metadata is updated with sync_disabled=True.
    The sandbox sync task will exclude these files when syncing to the sandbox.

    If the item is a directory, all children are also toggled.
    """
    from onyx.db.document import get_documents_by_source
    from onyx.db.document import update_document_metadata__no_commit

    tenant_id = get_current_tenant_id()
    if tenant_id is None:
        raise HTTPException(status_code=500, detail="Tenant ID not found")

    doc = _verify_ownership_and_get_document(document_id, user, db_session)

    # Update metadata for this document
    new_metadata = dict(doc.doc_metadata or {})
    new_metadata["sync_disabled"] = not enabled
    update_document_metadata__no_commit(db_session, document_id, new_metadata)

    # If this is a directory, also toggle all children
    doc_metadata = doc.doc_metadata or {}
    if doc_metadata.get("is_directory"):
        folder_path = doc.semantic_id
        if folder_path:
            all_docs = get_documents_by_source(
                db_session=db_session,
                source=DocumentSource.CRAFT_FILE,
                creator_id=user.id,
            )
            for child_doc in all_docs:
                if child_doc.semantic_id and child_doc.semantic_id.startswith(
                    folder_path + "/"
                ):
                    child_metadata = dict(child_doc.doc_metadata or {})
                    child_metadata["sync_disabled"] = not enabled
                    update_document_metadata__no_commit(
                        db_session, child_doc.id, child_metadata
                    )

    db_session.commit()

    return ToggleSyncResponse(success=True, sync_enabled=enabled)


@router.delete("/files/{document_id}")
def delete_file(
    document_id: str,
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> DeleteFileResponse:
    """Delete a file from both S3 and the document table."""
    from onyx.db.document import delete_document_by_id__no_commit

    tenant_id = get_current_tenant_id()
    if tenant_id is None:
        raise HTTPException(status_code=500, detail="Tenant ID not found")

    doc = _verify_ownership_and_get_document(document_id, user, db_session)

    # Delete from storage if it's a file (not directory)
    doc_metadata = doc.doc_metadata or {}
    if not doc_metadata.get("is_directory"):
        file_path = doc_metadata.get("file_path")
        if file_path:
            writer = get_persistent_document_writer(
                user_id=str(user.id),
                tenant_id=tenant_id,
            )
            try:
                if isinstance(writer, S3PersistentDocumentWriter):
                    writer.delete_raw_file_by_path(file_path)
                else:
                    writer.delete_raw_file(file_path)
            except Exception as e:
                logger.warning(f"Failed to delete file at path {file_path}: {e}")
        else:
            # Fallback for documents created before file_path was stored
            storage_key = doc_metadata.get("storage_key") or doc_metadata.get("s3_key")
            if storage_key:
                writer = get_persistent_document_writer(
                    user_id=str(user.id),
                    tenant_id=tenant_id,
                )
                try:
                    if isinstance(writer, S3PersistentDocumentWriter):
                        writer.delete_raw_file(storage_key)
                    else:
                        logger.warning(
                            f"Cannot delete file in local mode without file_path: {document_id}"
                        )
                except Exception as e:
                    logger.warning(
                        f"Failed to delete storage object {storage_key}: {e}"
                    )

    # Delete from document table
    delete_document_by_id__no_commit(db_session, document_id)
    db_session.commit()

    # Trigger sync to apply changes
    _trigger_sandbox_sync(str(user.id), tenant_id, source=USER_LIBRARY_SOURCE_DIR)

    return DeleteFileResponse(success=True, deleted=document_id)
