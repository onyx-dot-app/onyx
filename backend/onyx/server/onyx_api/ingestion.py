from datetime import datetime
from datetime import timezone

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from sqlalchemy.orm import Session

from onyx.auth.users import api_key_dep
from onyx.configs.constants import DEFAULT_CC_PAIR_ID
from onyx.configs.constants import DocumentSource
from onyx.connectors.models import Document
from onyx.connectors.models import IndexAttemptMetadata
from onyx.db.connector_credential_pair import get_connector_credential_pair_from_id
from onyx.db.document import get_documents_by_cc_pair
from onyx.db.document import get_ingestion_documents
from onyx.db.engine.sql_engine import get_session
from onyx.db.models import User
from onyx.db.search_settings import get_active_search_settings
from onyx.db.search_settings import get_current_search_settings
from onyx.db.search_settings import get_secondary_search_settings
from onyx.document_index.factory import get_default_document_index
from onyx.indexing.adapters.document_indexing_adapter import (
    DocumentIndexingBatchAdapter,
)
from onyx.indexing.embedder import DefaultIndexingEmbedder
from onyx.indexing.indexing_pipeline import run_indexing_pipeline
from onyx.natural_language_processing.search_nlp_models import (
    InformationContentClassificationModel,
)
from onyx.server.onyx_api.models import DocMinimalInfo
from onyx.server.onyx_api.models import IngestionDocument
from onyx.server.onyx_api.models import IngestionResult
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()

# not using /api to avoid confusion with nginx api path routing
router = APIRouter(prefix="/onyx-api")


@router.get("/connector-docs/{cc_pair_id}")
def get_docs_by_connector_credential_pair(
    cc_pair_id: int,
    _: User | None = Depends(api_key_dep),
    db_session: Session = Depends(get_session),
) -> list[DocMinimalInfo]:
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
    _: User | None = Depends(api_key_dep),
    db_session: Session = Depends(get_session),
) -> list[DocMinimalInfo]:
    db_docs = get_ingestion_documents(db_session)
    return [
        DocMinimalInfo(
            document_id=doc.id,
            semantic_id=doc.semantic_id,
            link=doc.link,
        )
        for doc in db_docs
    ]


@router.post("/ingestion")
def upsert_ingestion_doc(
    doc_info: IngestionDocument,
    _: User | None = Depends(api_key_dep),
    db_session: Session = Depends(get_session),
) -> IngestionResult:
    tenant_id = get_current_tenant_id()

    doc_info.document.from_ingestion_api = True

    if doc_info.document.doc_updated_at is None:
        doc_info.document.doc_updated_at = datetime.now(tz=timezone.utc)

    document = Document.from_base(doc_info.document)

    # TODO once the frontend is updated with this enum, remove this logic
    if document.source == DocumentSource.INGESTION_API:
        document.source = DocumentSource.FILE

    cc_pair = get_connector_credential_pair_from_id(
        db_session=db_session,
        cc_pair_id=doc_info.cc_pair_id or DEFAULT_CC_PAIR_ID,
    )
    if cc_pair is None:
        raise HTTPException(
            status_code=400, detail="Connector-Credential Pair specified does not exist"
        )

    # Need to index for both the primary and secondary index if possible
    active_search_settings = get_active_search_settings(db_session)
    curr_doc_index = get_default_document_index(
        active_search_settings.primary,
        None,
    )

    search_settings = get_current_search_settings(db_session)

    index_embedding_model = DefaultIndexingEmbedder.from_db_search_settings(
        search_settings=search_settings
    )

    information_content_classification_model = InformationContentClassificationModel()

    # Build adapter for primary indexing
    adapter = DocumentIndexingBatchAdapter(
        db_session=db_session,
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
        information_content_classification_model=information_content_classification_model,
        document_index=curr_doc_index,
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

        sec_doc_index = get_default_document_index(
            active_search_settings.secondary, None
        )

        run_indexing_pipeline(
            embedder=new_index_embedding_model,
            information_content_classification_model=information_content_classification_model,
            document_index=sec_doc_index,
            ignore_time_skip=True,
            db_session=db_session,
            tenant_id=tenant_id,
            document_batch=[document],
            request_id=None,
            adapter=adapter,
        )

    return IngestionResult(
        document_id=document.id,
        already_existed=indexing_pipeline_result.new_docs > 0,
    )
