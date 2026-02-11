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
from uuid import UUID

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
from onyx.server.features.build.indexing.persistent_document_writer import (
    get_persistent_document_writer,
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


def _get_user_storage_bytes(db_session: Session, user_id: UUID) -> int:
    """Get total storage usage for a user's library files.

    Uses SQL aggregation to sum file_size from doc_metadata JSONB for all
    CRAFT_FILE documents owned by this user, avoiding loading all documents
    into Python memory.
    """
    from sqlalchemy import and_
    from sqlalchemy import cast
    from sqlalchemy import func
    from sqlalchemy import Integer
    from sqlalchemy import select

    from onyx.db.models import Connector
    from onyx.db.models import ConnectorCredentialPair
    from onyx.db.models import Document as DbDocument
    from onyx.db.models import DocumentByConnectorCredentialPair

    stmt = (
        select(
            func.coalesce(
                func.sum(
                    cast(
                        DbDocument.doc_metadata["file_size"].as_string(),
                        Integer,
                    )
                ),
                0,
            )
        )
        .join(
            DocumentByConnectorCredentialPair,
            DbDocument.id == DocumentByConnectorCredentialPair.id,
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
        .join(
            Connector,
            ConnectorCredentialPair.connector_id == Connector.id,
        )
        .where(Connector.source == DocumentSource.CRAFT_FILE)
        .where(ConnectorCredentialPair.creator_id == user_id)
        .where(DbDocument.doc_metadata["is_directory"].as_boolean().is_not(True))
    )
    result = db_session.execute(stmt).scalar()
    return int(result or 0)


def _get_or_create_craft_connector(db_session: Session, user: User) -> tuple[int, int]:
    """Get or create the CRAFT_FILE connector for a user.

    Returns:
        Tuple of (connector_id, credential_id)

    Note: We need to create a credential even though CRAFT_FILE doesn't require
    authentication. This is because Onyx's connector-credential pair system
    requires a credential for all connectors. The credential is empty ({}).

    This function handles recovery from partial creation failures by detecting
    orphaned connectors (connectors without cc_pairs) and completing their setup.
    """
    from onyx.connectors.models import InputType
    from onyx.db.connector import create_connector
    from onyx.db.connector import fetch_connectors
    from onyx.db.connector_credential_pair import add_credential_to_connector
    from onyx.db.connector_credential_pair import (
        get_connector_credential_pairs_for_user,
    )
    from onyx.db.credentials import create_credential
    from onyx.db.credentials import fetch_credentials_for_user
    from onyx.db.enums import AccessType
    from onyx.db.enums import ProcessingMode
    from onyx.server.documents.models import ConnectorBase
    from onyx.server.documents.models import CredentialBase

    # Check if user already has a complete CRAFT_FILE cc_pair
    cc_pairs = get_connector_credential_pairs_for_user(
        db_session=db_session,
        user=user,
        get_editable=False,
        eager_load_connector=True,
        eager_load_credential=True,
        processing_mode=ProcessingMode.RAW_BINARY,
    )

    for cc_pair in cc_pairs:
        if cc_pair.connector.source == DocumentSource.CRAFT_FILE:
            return cc_pair.connector.id, cc_pair.credential.id

    # Check for orphaned connector (created but cc_pair creation failed previously)
    # An orphaned connector has no cc_pairs. We check credentials to verify
    # it belongs to this user (Connector doesn't have creator_id directly).
    existing_connectors = fetch_connectors(
        db_session, sources=[DocumentSource.CRAFT_FILE]
    )
    orphaned_connector = None
    for conn in existing_connectors:
        if conn.name != "User Library":
            continue
        # Verify this connector has no cc_pairs (i.e., is actually orphaned)
        # and that a matching credential exists for this user
        if not conn.credentials:
            orphaned_connector = conn
            break

    if orphaned_connector:
        connector_id = orphaned_connector.id
        logger.info(
            f"Found orphaned User Library connector {connector_id}, completing setup"
        )
    else:
        # Create new connector
        connector_data = ConnectorBase(
            name="User Library",
            source=DocumentSource.CRAFT_FILE,
            input_type=InputType.LOAD_STATE,
            connector_specific_config={"disabled_paths": []},
            refresh_freq=None,
            prune_freq=None,
        )
        connector_response = create_connector(
            db_session=db_session,
            connector_data=connector_data,
        )
        connector_id = connector_response.id

    # Try to reuse an existing User Library credential for this user
    existing_credentials = fetch_credentials_for_user(
        db_session=db_session,
        user=user,
    )
    credential = None
    for cred in existing_credentials:
        if (
            cred.source == DocumentSource.CRAFT_FILE
            and cred.name == "User Library Credential"
        ):
            credential = cred
            break

    if credential is None:
        # Create credential (empty - no auth needed, but required by the system)
        credential_data = CredentialBase(
            credential_json={},
            admin_public=False,
            source=DocumentSource.CRAFT_FILE,
            name="User Library Credential",
        )
        credential = create_credential(
            credential_data=credential_data,
            user=user,
            db_session=db_session,
        )

    # Link them with RAW_BINARY processing mode
    add_credential_to_connector(
        db_session=db_session,
        connector_id=connector_id,
        credential_id=credential.id,
        user=user,
        cc_pair_name="User Library",
        access_type=AccessType.PRIVATE,
        groups=None,
        processing_mode=ProcessingMode.RAW_BINARY,
    )

    db_session.commit()
    return connector_id, credential.id


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
    existing_usage = _get_user_storage_bytes(db_session, user.id)

    # Get or create connector
    connector_id, credential_id = _get_or_create_craft_connector(db_session, user)

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

        # Write raw binary to storage
        storage_key = writer.write_raw_file(
            path=file_path,
            content=content,
            content_type=file.content_type,
        )

        # Track in document table
        doc_id = _build_document_id(str(user.id), file_path)
        doc_metadata = DocumentMetadata(
            connector_id=connector_id,
            credential_id=credential_id,
            document_id=doc_id,
            semantic_identifier=f"user_library{file_path}",
            first_link=storage_key,
            doc_metadata={
                "storage_key": storage_key,
                "file_path": file_path,
                "file_size": file_size,
                "mime_type": file.content_type,
                "is_directory": False,
            },
        )
        upsert_documents(db_session, [doc_metadata])
        upsert_document_by_connector_credential_pair(
            db_session, connector_id, credential_id, [doc_id]
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
    _trigger_sandbox_sync(str(user.id), tenant_id, source="user_library")

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
    existing_usage = _get_user_storage_bytes(db_session, user.id)

    # Get or create connector
    connector_id, credential_id = _get_or_create_craft_connector(db_session, user)

    # Get the persistent document writer
    writer = get_persistent_document_writer(
        user_id=str(user.id),
        tenant_id=tenant_id,
    )

    uploaded_entries: list[LibraryEntryResponse] = []
    total_size = 0
    base_path = _sanitize_path(path)
    now = datetime.now(timezone.utc)

    try:
        with zipfile.ZipFile(BytesIO(content), "r") as zip_file:
            # Check file count
            if len(zip_file.namelist()) > USER_LIBRARY_MAX_FILES_PER_UPLOAD:
                raise HTTPException(
                    status_code=400,
                    detail=f"Zip contains too many files. Maximum is {USER_LIBRARY_MAX_FILES_PER_UPLOAD}.",
                )

            # Zip bomb protection: check total decompressed size before extracting
            declared_total = sum(
                info.file_size for info in zip_file.infolist() if not info.is_dir()
            )
            max_decompressed = USER_LIBRARY_MAX_TOTAL_SIZE_BYTES
            if existing_usage + declared_total > max_decompressed:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Zip decompressed size ({declared_total // (1024*1024)}MB) "
                        f"would exceed storage limit."
                    ),
                )

            for zip_info in zip_file.infolist():
                # Skip directories
                if zip_info.is_dir():
                    continue

                # Skip hidden files and __MACOSX
                if (
                    zip_info.filename.startswith("__MACOSX")
                    or "/." in zip_info.filename
                ):
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

                # Guess content type
                content_type, _ = mimetypes.guess_type(file_name)

                # Write raw binary to storage
                storage_key = writer.write_raw_file(
                    path=file_path,
                    content=file_content,
                    content_type=content_type,
                )

                # Track in document table
                doc_id = _build_document_id(str(user.id), file_path)
                doc_metadata = DocumentMetadata(
                    connector_id=connector_id,
                    credential_id=credential_id,
                    document_id=doc_id,
                    semantic_identifier=f"user_library{file_path}",
                    first_link=storage_key,
                    doc_metadata={
                        "storage_key": storage_key,
                        "file_path": file_path,
                        "file_size": file_size,
                        "mime_type": content_type,
                        "is_directory": False,
                    },
                )
                upsert_documents(db_session, [doc_metadata])
                upsert_document_by_connector_credential_pair(
                    db_session, connector_id, credential_id, [doc_id]
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
    _trigger_sandbox_sync(str(user.id), tenant_id, source="user_library")

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
    connector_id, credential_id = _get_or_create_craft_connector(db_session, user)

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
        semantic_identifier=f"user_library{dir_path}",
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
) -> dict[str, Any]:
    """Enable/disable syncing a file to sandboxes.

    When sync is disabled, the file's metadata is updated with sync_disabled=True.
    The sandbox sync task will exclude these files when syncing to the sandbox.

    If the item is a directory, all children are also toggled.
    """
    from onyx.db.document import get_document
    from onyx.db.document import get_documents_by_source
    from onyx.db.document import update_document_metadata__no_commit

    tenant_id = get_current_tenant_id()
    if tenant_id is None:
        raise HTTPException(status_code=500, detail="Tenant ID not found")

    # Verify ownership
    user_prefix = f"CRAFT_FILE__{user.id}__"
    if not document_id.startswith(user_prefix):
        raise HTTPException(
            status_code=403, detail="Not authorized to modify this file"
        )

    # Get document
    doc = get_document(document_id, db_session)
    if doc is None:
        raise HTTPException(status_code=404, detail="File not found")

    # Update metadata for this document
    new_metadata = dict(doc.doc_metadata or {})
    new_metadata["sync_disabled"] = not enabled
    update_document_metadata__no_commit(db_session, document_id, new_metadata)

    # If this is a directory, also toggle all children
    doc_metadata = doc.doc_metadata or {}
    if doc_metadata.get("is_directory"):
        folder_path = doc.semantic_id
        if folder_path:
            # Get CRAFT_FILE documents for this user (filtered at SQL level)
            all_docs = get_documents_by_source(
                db_session=db_session,
                source=DocumentSource.CRAFT_FILE,
                creator_id=user.id,
            )
            # Find children of this folder
            for child_doc in all_docs:
                if child_doc.semantic_id and child_doc.semantic_id.startswith(
                    folder_path + "/"
                ):
                    # Update metadata
                    child_metadata = dict(child_doc.doc_metadata or {})
                    child_metadata["sync_disabled"] = not enabled
                    update_document_metadata__no_commit(
                        db_session, child_doc.id, child_metadata
                    )

    db_session.commit()

    return {"success": True, "sync_enabled": enabled}


@router.delete("/files/{document_id}")
def delete_file(
    document_id: str,
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Delete a file from both S3 and the document table."""
    from onyx.db.document import delete_document_by_id__no_commit
    from onyx.db.document import get_document

    tenant_id = get_current_tenant_id()
    if tenant_id is None:
        raise HTTPException(status_code=500, detail="Tenant ID not found")

    # Verify ownership
    user_prefix = f"CRAFT_FILE__{user.id}__"
    if not document_id.startswith(user_prefix):
        raise HTTPException(
            status_code=403, detail="Not authorized to delete this file"
        )

    # Get document
    doc = get_document(document_id, db_session)
    if doc is None:
        raise HTTPException(status_code=404, detail="File not found")

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
    _trigger_sandbox_sync(str(user.id), tenant_id, source="user_library")

    return {"success": True, "deleted": document_id}
