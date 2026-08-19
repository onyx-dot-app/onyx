from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from onyx.auth.permissions import require_permission
from onyx.configs.constants import DEFAULT_CC_PAIR_ID, PUBLIC_API_TAGS
from onyx.connectors.models import Document, IndexAttemptMetadata
from onyx.db.connector_credential_pair import (
    get_cc_pair_ids_for_document,
    get_connector_credential_pair_from_id,
    verify_user_can_edit_all_cc_pairs,
    verify_user_has_access_to_cc_pair,
)
from onyx.db.document import (
    delete_documents_complete,
    get_document,
    get_documents_by_cc_pair,
    get_ingestion_documents,
)
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import Permission
from onyx.db.models import User
from onyx.db.port_orphan_candidate import (
    delete_port_orphan_candidates_by_id,
    record_port_orphan_candidates_for_document,
)
from onyx.db.search_settings import (
    get_active_search_settings,
    get_current_search_settings,
    get_secondary_search_settings,
)
from onyx.db.user_file import get_user_file_by_id
from onyx.document_index.factory import get_all_document_indices
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.indexing.adapters.document_indexing_adapter import (
    DocumentIndexingBatchAdapter,
)
from onyx.indexing.embedder import DefaultIndexingEmbedder
from onyx.indexing.indexing_pipeline import run_indexing_pipeline
from onyx.server.onyx_api.models import (
    DocMinimalInfo,
    IngestionDocument,
    IngestionResult,
)
from onyx.server.utils_vector_db import require_vector_db
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()

# not using /api to avoid confusion with nginx api path routing
router = APIRouter(prefix="/onyx-api", tags=PUBLIC_API_TAGS)


@router.get("/connector-docs/{cc_pair_id}")
def get_docs_by_connector_credential_pair(
    cc_pair_id: int,
    user: User = Depends(
        require_permission(Permission.MANAGE_CONNECTORS, allow_scope=True)
    ),
    db_session: Session = Depends(get_session),
) -> list[DocMinimalInfo]:
    # GATE 2
    if not verify_user_has_access_to_cc_pair(cc_pair_id, db_session, user):
        raise OnyxError(
            OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
            "Connection not found for current user's permissions",
        )

    db_docs = get_documents_by_cc_pair(cc_pair_id=cc_pair_id, db_session=db_session)
    return [
        DocMinimalInfo(
            document_id=doc.id,
            semantic_id=doc.semantic_id,
            link=doc.link,
        )
        for doc in db_docs
    ]


@router.get("/ingestion")
def get_ingestion_docs(
    _: User = Depends(require_permission(Permission.MANAGE_CONNECTORS)),
    db_session: Session = Depends(get_session),
) -> list[DocMinimalInfo]:
    # no allow_scope: lists every ingested doc org-wide, which no group scope can bound
    db_docs = get_ingestion_documents(db_session)
    return [
        DocMinimalInfo(
            document_id=doc.id,
            semantic_id=doc.semantic_id,
            link=doc.link,
        )
        for doc in db_docs
    ]


@router.post("/ingestion", dependencies=[Depends(require_vector_db)])
def upsert_ingestion_doc(
    doc_info: IngestionDocument,
    user: User = Depends(
        require_permission(Permission.MANAGE_CONNECTORS, allow_scope=True)
    ),
    db_session: Session = Depends(get_session),
) -> IngestionResult:
    tenant_id = get_current_tenant_id()

    doc_info.document.from_ingestion_api = True

    if doc_info.document.doc_updated_at is None:
        doc_info.document.doc_updated_at = datetime.now(tz=timezone.utc)

    document = Document.from_base(doc_info.document)

    target_cc_pair_id = doc_info.cc_pair_id or DEFAULT_CC_PAIR_ID
    cc_pair = get_connector_credential_pair_from_id(
        db_session=db_session,
        cc_pair_id=target_cc_pair_id,
    )
    if cc_pair is None:
        raise OnyxError(
            OnyxErrorCode.CONNECTOR_NOT_FOUND,
            "Connector-Credential Pair specified does not exist",
        )

    # GATE 2: the default pair is public, so a scoped manager cannot ingest into it
    if not verify_user_has_access_to_cc_pair(target_cc_pair_id, db_session, user):
        raise OnyxError(
            OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
            "Connection not found for current user's permissions",
        )

    # GATE 2 on every pair serving this id — the upsert rewrites the shared doc row and
    # replaces its chunks. Must run before the pipeline, which adds the target as owner.
    existing_cc_pair_ids = get_cc_pair_ids_for_document(db_session, document.id)
    if existing_cc_pair_ids and not verify_user_can_edit_all_cc_pairs(
        existing_cc_pair_ids, db_session, user
    ):
        raise OnyxError(
            OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
            "Connection not found for current user's permissions",
        )

    # a user file has no doc row or cc_pair link, so the gate above sees an empty set
    # and would let this replace its chunks. get_user_file_by_id raises on a non-uuid
    try:
        posted_user_file_id: UUID | None = UUID(document.id)
    except ValueError:
        posted_user_file_id = None
    if posted_user_file_id is not None and get_user_file_by_id(
        posted_user_file_id, db_session
    ):
        raise OnyxError(
            OnyxErrorCode.VALIDATION_ERROR,
            "Document ID is reserved for a user file",
        )

    # Need to index for both the primary and secondary index if possible
    active_search_settings = get_active_search_settings(db_session)
    # This flow is for indexing so we get all indices.
    document_indices = get_all_document_indices(
        active_search_settings.primary,
        None,
        None,
    )

    search_settings = get_current_search_settings(db_session)

    index_embedding_model = DefaultIndexingEmbedder.from_db_search_settings(
        search_settings=search_settings
    )

    # Build adapter for primary indexing
    adapter = DocumentIndexingBatchAdapter(
        connector_id=cc_pair.connector_id,
        credential_id=cc_pair.credential_id,
        tenant_id=tenant_id,
        index_attempt_metadata=IndexAttemptMetadata(
            connector_id=cc_pair.connector_id,
            credential_id=cc_pair.credential_id,
        ),
    )

    indexing_pipeline_result = run_indexing_pipeline(
        embedder=index_embedding_model,
        document_indices=document_indices,
        ignore_time_skip=True,
        db_session=db_session,
        tenant_id=tenant_id,
        document_batch=[document],
        request_id=None,
        adapter=adapter,
    )

    # If there's a secondary index being built, index the doc but don't use it for return here
    if active_search_settings.secondary:
        sec_search_settings = get_secondary_search_settings(db_session)

        if sec_search_settings is None:
            # Should not ever happen
            raise RuntimeError(
                "Secondary index exists but no search settings configured"
            )

        new_index_embedding_model = DefaultIndexingEmbedder.from_db_search_settings(
            search_settings=sec_search_settings
        )

        # This flow is for indexing so we get all indices.
        sec_document_indices = get_all_document_indices(
            active_search_settings.secondary, None, None
        )

        run_indexing_pipeline(
            embedder=new_index_embedding_model,
            document_indices=sec_document_indices,
            ignore_time_skip=True,
            # FUTURE write: skip content_hash dedup, else the primary run's hash
            # suppresses this into a no-op.
            index_to_secondary=True,
            db_session=db_session,
            tenant_id=tenant_id,
            document_batch=[document],
            request_id=None,
            adapter=adapter,
        )

    return IngestionResult(
        document_id=document.id,
        already_existed=indexing_pipeline_result.new_docs == 0,
    )


@router.delete("/ingestion/{document_id}", dependencies=[Depends(require_vector_db)])
def delete_ingestion_doc(
    document_id: str,
    user: User = Depends(
        require_permission(Permission.MANAGE_CONNECTORS, allow_scope=True)
    ),
    db_session: Session = Depends(get_session),
) -> None:
    # Verify the document exists and was created via the ingestion API
    document = get_document(document_id=document_id, db_session=db_session)
    if document is None:
        raise OnyxError(OnyxErrorCode.DOCUMENT_NOT_FOUND, "Document not found")

    if not document.from_ingestion_api:
        raise OnyxError(
            OnyxErrorCode.VALIDATION_ERROR,
            "Document was not created via the ingestion API",
        )

    # GATE 2 on every owning pair — one is not enough to drop a doc another group serves
    if not verify_user_can_edit_all_cc_pairs(
        get_cc_pair_ids_for_document(db_session, document_id), db_session, user
    ):
        raise OnyxError(
            OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
            "Connection not found for current user's permissions",
        )

    active_search_settings = get_active_search_settings(db_session)

    # If a port is filling a target index, record this delete before the index delete
    # below so a racing create-only copy that resurrects the doc is swept back out.
    recorded_ids = record_port_orphan_candidates_for_document(
        db_session,
        document_id,
        active_search_settings.primary,
        active_search_settings.secondary,
    )
    if recorded_ids:
        db_session.commit()

    # This flow is for deletion so we get all indices.
    document_indices = get_all_document_indices(
        active_search_settings.primary,
        active_search_settings.secondary,
        None,
    )
    try:
        for document_index in document_indices:
            document_index.delete(
                document_id,
                chunk_count=document.chunk_count,
            )
        delete_documents_complete(db_session, [document_id])
    except Exception:
        # A failed DB delete leaves the session aborted; roll back before the candidate
        # cleanup or it raises and masks the real error. The doc stays live (no retry here),
        # so drop only the rows this call inserted to keep the sweep off its live chunks.
        db_session.rollback()
        if recorded_ids:
            delete_port_orphan_candidates_by_id(db_session, recorded_ids)
            db_session.commit()
        raise
