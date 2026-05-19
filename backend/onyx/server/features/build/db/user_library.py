"""Database operations for User Library (CRAFT_FILE connector).

Handles file storage, document tracking, quota, and connector setup for the
User Library feature in Craft.
"""

import hashlib
import io
from uuid import UUID

from sqlalchemy import and_
from sqlalchemy import cast
from sqlalchemy import func
from sqlalchemy import Integer
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.configs.constants import FileOrigin
from onyx.connectors.models import InputType
from onyx.db.connector import create_connector
from onyx.db.connector import fetch_connectors
from onyx.db.connector_credential_pair import add_credential_to_connector
from onyx.db.connector_credential_pair import get_connector_credential_pairs_for_user
from onyx.db.credentials import create_credential
from onyx.db.credentials import fetch_credentials_for_user
from onyx.db.document import delete_document_by_id__no_commit
from onyx.db.document import get_document
from onyx.db.document import get_documents_by_source
from onyx.db.document import update_document_metadata__no_commit
from onyx.db.document import upsert_document_by_connector_credential_pair
from onyx.db.document import upsert_documents
from onyx.db.enums import AccessType
from onyx.db.enums import ProcessingMode
from onyx.db.models import Connector
from onyx.db.models import ConnectorCredentialPair
from onyx.db.models import Document as DbDocument
from onyx.db.models import DocumentByConnectorCredentialPair
from onyx.db.models import User
from onyx.document_index.document_metadata import DocumentMetadata
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.file_store.file_store import get_default_file_store
from onyx.server.documents.models import ConnectorBase
from onyx.server.documents.models import CredentialBase
from onyx.server.features.build.configs import USER_LIBRARY_CONNECTOR_NAME
from onyx.server.features.build.configs import USER_LIBRARY_CREDENTIAL_NAME
from onyx.server.features.build.configs import USER_LIBRARY_SOURCE_DIR
from onyx.utils.logger import setup_logger

logger = setup_logger()


def build_document_id(user_id: UUID, path: str) -> str:
    """Deterministic document ID for a user library path."""
    path_hash = hashlib.sha256(path.encode()).hexdigest()[:16]
    return f"CRAFT_FILE__{user_id}__{path_hash}"


def list_user_files(db_session: Session, user_id: UUID) -> list[DbDocument]:
    """Return all CRAFT_FILE documents for a user."""
    return get_documents_by_source(
        db_session=db_session,
        source=DocumentSource.CRAFT_FILE,
        creator_id=user_id,
    )


def fetch_user_file_for_user(
    db_session: Session, doc_id: str, user_id: UUID
) -> DbDocument:
    """Fetch a CRAFT_FILE document and verify ownership.

    Raises NOT_FOUND if the doc doesn't exist or doesn't belong to the user.
    Ownership is encoded in the deterministic document_id prefix.
    """
    if not doc_id.startswith(f"CRAFT_FILE__{user_id}__"):
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "File not found")

    doc = get_document(doc_id, db_session)
    if doc is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "File not found")
    return doc


def store_user_file(
    *,
    db_session: Session,
    user_id: UUID,
    connector_id: int,
    credential_id: int,
    file_path: str,
    content: bytes,
    mime_type: str,
) -> tuple[str, str, str | None]:
    """Store a file in the default file store and upsert its document record.

    Returns (doc_id, file_id, old_blob_id_to_delete). The new blob is saved
    first; the caller must delete the returned old_blob_id *after* its final
    DB commit by passing it to ``cleanup_old_blobs``. Deleting before commit
    risks permanent data loss if the commit later fails.
    """
    file_store = get_default_file_store()
    doc_id = build_document_id(user_id, file_path)
    existing = get_document(doc_id, db_session)
    old_blob_id = existing.link if existing else None

    filename = file_path.split("/")[-1]
    file_id = file_store.save_file(
        content=io.BytesIO(content),
        display_name=filename,
        file_origin=FileOrigin.USER_FILE,
        file_type=mime_type,
    )

    metadata = DocumentMetadata(
        connector_id=connector_id,
        credential_id=credential_id,
        document_id=doc_id,
        semantic_identifier=f"{USER_LIBRARY_SOURCE_DIR}{file_path}",
        first_link=file_id,
        file_id=file_id,
        doc_metadata={
            "file_store_id": file_id,
            "file_path": file_path,
            "file_size": len(content),
            "mime_type": mime_type,
            "is_directory": False,
        },
    )
    upsert_documents(db_session, [metadata])
    upsert_document_by_connector_credential_pair(
        db_session, connector_id, credential_id, [doc_id]
    )

    stale = old_blob_id if old_blob_id and old_blob_id != file_id else None
    return doc_id, file_id, stale


def cleanup_old_blobs(blob_ids: list[str | None]) -> None:
    """Delete superseded file-store blobs. Call after the final DB commit."""
    file_store = get_default_file_store()
    for blob_id in blob_ids:
        if not blob_id:
            continue
        try:
            file_store.delete_file(blob_id, error_on_missing=False)
        except Exception as e:
            logger.warning("Failed to delete stale blob %s: %s", blob_id, e)


def create_directory_record(
    *,
    db_session: Session,
    user_id: UUID,
    connector_id: int,
    credential_id: int,
    dir_path: str,
) -> str:
    """Create a virtual-directory document record. Returns the doc_id."""
    doc_id = build_document_id(user_id, dir_path)
    metadata = DocumentMetadata(
        connector_id=connector_id,
        credential_id=credential_id,
        document_id=doc_id,
        semantic_identifier=f"{USER_LIBRARY_SOURCE_DIR}{dir_path}",
        first_link="",
        doc_metadata={"is_directory": True},
    )
    upsert_documents(db_session, [metadata])
    upsert_document_by_connector_credential_pair(
        db_session, connector_id, credential_id, [doc_id]
    )
    return doc_id


def set_sync_disabled(
    db_session: Session,
    user_id: UUID,
    doc: DbDocument,
    sync_disabled: bool,
) -> None:
    """Set sync_disabled on a document. For directories, applies to all children."""
    new_metadata = dict(doc.doc_metadata or {})
    new_metadata["sync_disabled"] = sync_disabled
    update_document_metadata__no_commit(db_session, doc.id, new_metadata)

    if (doc.doc_metadata or {}).get("is_directory") and doc.semantic_id:
        prefix = doc.semantic_id + "/"
        for child in list_user_files(db_session, user_id):
            if child.semantic_id and child.semantic_id.startswith(prefix):
                child_meta = dict(child.doc_metadata or {})
                child_meta["sync_disabled"] = sync_disabled
                update_document_metadata__no_commit(db_session, child.id, child_meta)


def delete_user_file(db_session: Session, doc: DbDocument) -> None:
    """Delete a user file's blob from the file store and its document record."""
    meta = doc.doc_metadata or {}
    if not meta.get("is_directory"):
        file_id = doc.link or meta.get("file_store_id")
        if file_id:
            try:
                get_default_file_store().delete_file(file_id, error_on_missing=False)
            except Exception as e:
                logger.warning("Failed to delete file blob %s: %s", file_id, e)

    delete_document_by_id__no_commit(db_session, doc.id)


def get_user_storage_bytes(db_session: Session, user_id: UUID) -> int:
    """Total storage usage (bytes) for a user's library files."""
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


def get_or_create_craft_connector(db_session: Session, user: User) -> tuple[int, int]:
    """Idempotent: return the user's CRAFT_FILE (connector_id, credential_id).

    A no-auth credential is created if needed since cc_pairs require one.
    Commits internally — pre-existing convention, not aligned with skill.py.
    """
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
        if (
            cc_pair.connector.source == DocumentSource.CRAFT_FILE
            and cc_pair.creator_id == user.id
        ):
            return cc_pair.connector.id, cc_pair.credential.id

    # No cc_pair for this user — find or create the shared CRAFT_FILE connector
    existing_connectors = fetch_connectors(
        db_session, sources=[DocumentSource.CRAFT_FILE]
    )
    connector_id: int | None = None
    for conn in existing_connectors:
        if conn.name == USER_LIBRARY_CONNECTOR_NAME:
            connector_id = conn.id
            break

    if connector_id is None:
        connector_data = ConnectorBase(
            name=USER_LIBRARY_CONNECTOR_NAME,
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
            and cred.name == USER_LIBRARY_CREDENTIAL_NAME
        ):
            credential = cred
            break

    if credential is None:
        credential_data = CredentialBase(
            credential_json={},
            admin_public=False,
            source=DocumentSource.CRAFT_FILE,
            name=USER_LIBRARY_CREDENTIAL_NAME,
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
        cc_pair_name=USER_LIBRARY_CONNECTOR_NAME,
        access_type=AccessType.PRIVATE,
        groups=None,
        processing_mode=ProcessingMode.RAW_BINARY,
    )

    db_session.commit()
    return connector_id, credential.id
