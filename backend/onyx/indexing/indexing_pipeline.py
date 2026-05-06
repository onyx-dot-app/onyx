import time
from collections import defaultdict
from collections.abc import Callable
from collections.abc import Generator
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Protocol

import sentry_sdk
from pydantic import BaseModel
from pydantic import ConfigDict
from sqlalchemy.orm import Session

from onyx.configs.app_configs import DEFAULT_CONTEXTUAL_RAG_LLM_NAME
from onyx.configs.app_configs import DEFAULT_CONTEXTUAL_RAG_LLM_PROVIDER
from onyx.configs.app_configs import ENABLE_CONTEXTUAL_RAG
from onyx.configs.app_configs import MAX_CHUNKS_PER_DOC_BATCH
from onyx.configs.app_configs import MAX_DOCUMENT_CHARS
from onyx.configs.app_configs import MAX_TOKENS_FOR_FULL_INCLUSION
from onyx.configs.app_configs import USE_CHUNK_SUMMARY
from onyx.configs.app_configs import USE_DOCUMENT_SUMMARY
from onyx.configs.llm_configs import get_image_extraction_and_analysis_enabled
from onyx.connectors.cross_connector_utils.miscellaneous_utils import (
    get_experts_stores_representations,
)
from onyx.connectors.models import ConnectorFailure
from onyx.connectors.models import ConnectorStopSignal
from onyx.connectors.models import Document
from onyx.connectors.models import DocumentFailure
from onyx.connectors.models import ImageSection
from onyx.connectors.models import IndexAttemptMetadata
from onyx.connectors.models import IndexingDocument
from onyx.connectors.models import Section
from onyx.connectors.models import SectionType
from onyx.connectors.models import TextSection
from onyx.db.document import get_documents_by_ids
from onyx.db.document import upsert_document_by_connector_credential_pair
from onyx.db.document import upsert_documents
from onyx.db.enums import HookPoint
from onyx.db.hierarchy import link_hierarchy_nodes_to_documents
from onyx.db.index_attempt_metrics import IndexAttemptStage
from onyx.db.index_attempt_metrics import safe_record_single_event_if_set
from onyx.db.index_attempt_metrics import time_stage_if_set
from onyx.db.models import Document as DBDocument
from onyx.db.models import IndexModelStatus
from onyx.db.search_settings import get_active_search_settings
from onyx.db.tag import upsert_document_tags
from onyx.document_index.document_index_utils import get_multipass_config
from onyx.document_index.interfaces import DocumentIndex
from onyx.document_index.interfaces import DocumentInsertionRecord
from onyx.document_index.interfaces import DocumentMetadata
from onyx.document_index.interfaces import IndexBatchParams
from onyx.file_processing.image_summarization import summarize_image_with_error_handling
from onyx.file_store.file_store import get_default_file_store
from onyx.file_store.staging import promote_staged_file
from onyx.hooks.executor import execute_hook
from onyx.hooks.executor import HookSkipped
from onyx.hooks.executor import HookSoftFailed
from onyx.hooks.points.document_ingestion import DocumentIngestionOwner
from onyx.hooks.points.document_ingestion import DocumentIngestionPayload
from onyx.hooks.points.document_ingestion import DocumentIngestionResponse
from onyx.hooks.points.document_ingestion import DocumentIngestionSection
from onyx.indexing.chunk_batch_store import ChunkBatchStore
from onyx.indexing.chunker import Chunker
from onyx.indexing.embedder import embed_chunks_with_failure_handling
from onyx.indexing.embedder import IndexingEmbedder
from onyx.indexing.models import DocAwareChunk
from onyx.indexing.models import DocMetadataAwareIndexChunk
from onyx.indexing.models import IndexingBatchAdapter
from onyx.indexing.models import UpdatableChunkData
from onyx.indexing.vector_db_insertion import write_chunks_to_vector_db_with_backoff
from onyx.llm.factory import get_default_llm_with_vision
from onyx.llm.factory import get_llm_for_contextual_rag
from onyx.llm.interfaces import LLM
from onyx.llm.models import UserMessage
from onyx.llm.multi_llm import LLMRateLimitError
from onyx.llm.utils import llm_response_to_string
from onyx.llm.utils import MAX_CONTEXT_TOKENS
from onyx.natural_language_processing.utils import BaseTokenizer
from onyx.natural_language_processing.utils import get_tokenizer
from onyx.natural_language_processing.utils import tokenizer_trim_middle
from onyx.prompts.contextual_retrieval import CONTEXTUAL_RAG_PROMPT1
from onyx.prompts.contextual_retrieval import CONTEXTUAL_RAG_PROMPT2
from onyx.prompts.contextual_retrieval import DOCUMENT_SUMMARY_PROMPT
from onyx.tracing.flows import LLMFlow
from onyx.tracing.llm_utils import llm_generation_span
from onyx.tracing.llm_utils import record_llm_response
from onyx.utils.batching import batch_generator
from onyx.utils.logger import setup_logger
from onyx.utils.postgres_sanitization import sanitize_documents_for_postgres
from onyx.utils.threadpool_concurrency import run_functions_tuples_in_parallel
from onyx.utils.timing import log_function_time

logger = setup_logger()

MAX_CONTEXTUAL_RAG_WORKERS = 128  # Assume 8mb of memory per worker
MAX_IMAGE_WORKERS = 16


class _PendingImageSummarization(BaseModel):
    """An image section awaiting LLM summarization."""

    section: Section
    image_data: bytes
    context_name: str

    model_config = ConfigDict(arbitrary_types_allowed=True)


class DocumentBatchPrepareContext(BaseModel):
    updatable_docs: list[Document]
    id_to_boost_map: dict[str, int]
    indexable_docs: list[IndexingDocument] = []
    model_config = ConfigDict(arbitrary_types_allowed=True)


class IndexingPipelineResult(BaseModel):
    # number of documents that are completely new (e.g. did
    # not exist as a part of this OR any other connector)
    new_docs: int
    # NOTE: need total_docs, since the pipeline can skip some docs
    # (e.g. not even insert them into Postgres)
    total_docs: int
    # number of chunks that were inserted into Vespa
    total_chunks: int

    failures: list[ConnectorFailure]

    @classmethod
    def empty(cls, total_docs: int) -> "IndexingPipelineResult":
        return cls(
            new_docs=0,
            total_docs=total_docs,
            total_chunks=0,
            failures=[],
        )


class ChunkEmbeddingResult(BaseModel):
    successful_chunk_ids: list[tuple[int, str]]  # (chunk_id, document_id)
    connector_failures: list[ConnectorFailure]


class IndexingPipelineProtocol(Protocol):
    def __call__(
        self,
        document_batch: list[Document],
        index_attempt_metadata: IndexAttemptMetadata,
    ) -> IndexingPipelineResult: ...


def _upsert_documents_in_db(
    documents: list[Document],
    index_attempt_metadata: IndexAttemptMetadata,
    db_session: Session,
) -> None:
    # Metadata here refers to basic document info, not metadata about the actual content
    document_metadata_list: list[DocumentMetadata] = []
    for doc in documents:
        first_link = next(
            (section.link for section in doc.sections if section.link), ""
        )
        db_doc_metadata = DocumentMetadata(
            connector_id=index_attempt_metadata.connector_id,
            credential_id=index_attempt_metadata.credential_id,
            document_id=doc.id,
            semantic_identifier=doc.semantic_identifier,
            first_link=first_link,
            primary_owners=get_experts_stores_representations(doc.primary_owners),
            secondary_owners=get_experts_stores_representations(doc.secondary_owners),
            from_ingestion_api=doc.from_ingestion_api,
            external_access=doc.external_access,
            doc_metadata=doc.doc_metadata,
            # parent_hierarchy_node_id is resolved in docfetching using Redis cache
            parent_hierarchy_node_id=doc.parent_hierarchy_node_id,
            file_id=doc.file_id,
        )
        document_metadata_list.append(db_doc_metadata)

    upsert_documents(db_session, document_metadata_list)

    # Insert document content metadata
    for doc in documents:
        upsert_document_tags(
            document_id=doc.id,
            source=doc.source,
            metadata=doc.metadata,
            db_session=db_session,
        )


def _get_failed_doc_ids(failures: list[ConnectorFailure]) -> set[str]:
    """Extract document IDs from a list of connector failures."""
    return {f.failed_document.document_id for f in failures if f.failed_document}


def _embed_chunks_to_store(
    chunks: list[DocAwareChunk],
    embedder: IndexingEmbedder,
    tenant_id: str,
    request_id: str | None,
    store: ChunkBatchStore,
) -> ChunkEmbeddingResult:
    """Embed chunks in batches, spilling each batch to *store*.

    If a document fails embedding in any batch, its chunks are excluded from
    all batches (including earlier ones already written) so that the output
    is all-or-nothing per document.
    """
    successful_chunk_ids: list[tuple[int, str]] = []
    all_embedding_failures: list[ConnectorFailure] = []
    # Track failed doc IDs across all batches so that a failure in batch N
    # causes chunks for that doc to be skipped in batch N+1 and stripped
    # from earlier batches.
    all_failed_doc_ids: set[str] = set()

    for batch_idx, chunk_batch in enumerate(
        batch_generator(chunks, MAX_CHUNKS_PER_DOC_BATCH)
    ):
        # Skip chunks belonging to documents that failed in earlier batches.
        chunk_batch = [
            c for c in chunk_batch if c.source_document.id not in all_failed_doc_ids
        ]
        if not chunk_batch:
            continue

        logger.debug("Embedding batch %s: %s chunks", batch_idx, len(chunk_batch))

        chunks_with_embeddings, embedding_failures = embed_chunks_with_failure_handling(
            chunks=chunk_batch,
            embedder=embedder,
            tenant_id=tenant_id,
            request_id=request_id,
        )
        all_embedding_failures.extend(embedding_failures)
        all_failed_doc_ids.update(_get_failed_doc_ids(embedding_failures))

        # Only keep successfully embedded chunks for non-failed docs.
        chunks_with_embeddings = [
            c
            for c in chunks_with_embeddings
            if c.source_document.id not in all_failed_doc_ids
        ]

        successful_chunk_ids.extend(
            (c.chunk_id, c.source_document.id) for c in chunks_with_embeddings
        )

        store.save(chunks_with_embeddings, batch_idx)
        del chunks_with_embeddings

    # Scrub earlier batches for docs that failed in later batches.
    if all_failed_doc_ids:
        store.scrub_failed_docs(all_failed_doc_ids)
        successful_chunk_ids = [
            (chunk_id, doc_id)
            for chunk_id, doc_id in successful_chunk_ids
            if doc_id not in all_failed_doc_ids
        ]

    return ChunkEmbeddingResult(
        successful_chunk_ids=successful_chunk_ids,
        connector_failures=all_embedding_failures,
    )


@contextmanager
def embed_and_stream(
    chunks: list[DocAwareChunk],
    embedder: IndexingEmbedder,
    tenant_id: str,
    request_id: str | None,
    attempt_id: int | None = None,
) -> Generator[tuple[ChunkEmbeddingResult, ChunkBatchStore], None, None]:
    """Embed chunks to disk and yield a ``(result, store)`` pair.

    The store owns the temp directory — files are cleaned up when the context
    manager exits.

    When ``attempt_id`` is provided, records the EMBEDDING stage timing for
    just the actual embedding call (which finishes before ``yield``). Doing
    this inside the context manager avoids the caller's ``with``-body work
    (vector-db writes, post_index, etc.) being included in the embedding
    measurement.

    Usage::

        with embed_and_stream(chunks, embedder, tenant_id, req_id) as (result, store):
            for chunk in store.stream():
                ...
    """
    with ChunkBatchStore() as store:
        embed_start = time.monotonic()
        result = _embed_chunks_to_store(
            chunks=chunks,
            embedder=embedder,
            tenant_id=tenant_id,
            request_id=request_id,
            store=store,
        )
        embed_duration_ms = max(0, int((time.monotonic() - embed_start) * 1000))
        safe_record_single_event_if_set(
            IndexAttemptStage.EMBEDDING, attempt_id, embed_duration_ms
        )
        yield result, store


def get_doc_ids_to_update(
    documents: list[Document], db_docs: list[DBDocument]
) -> list[Document]:
    """Figures out which documents actually need to be updated. If a document is already present
    and the `updated_at` hasn't changed, we shouldn't need to do anything with it.

    NB: Still need to associate the document in the DB if multiple connectors are
    indexing the same doc."""
    id_update_time_map = {
        doc.id: doc.doc_updated_at for doc in db_docs if doc.doc_updated_at
    }

    updatable_docs: list[Document] = []
    for doc in documents:
        if (
            doc.id in id_update_time_map
            and doc.doc_updated_at
            and doc.doc_updated_at <= id_update_time_map[doc.id]
        ):
            continue
        updatable_docs.append(doc)

    return updatable_docs


def index_doc_batch_with_handler(
    *,
    chunker: Chunker,
    embedder: IndexingEmbedder,
    document_indices: list[DocumentIndex],
    document_batch: list[Document],
    request_id: str | None,
    tenant_id: str,
    db_session: Session,
    adapter: IndexingBatchAdapter,
    ignore_time_skip: bool = False,
    enable_contextual_rag: bool = False,
    llm: LLM | None = None,
) -> IndexingPipelineResult:
    try:
        index_pipeline_result = index_doc_batch(
            chunker=chunker,
            embedder=embedder,
            document_indices=document_indices,
            document_batch=document_batch,
            request_id=request_id,
            tenant_id=tenant_id,
            db_session=db_session,
            adapter=adapter,
            ignore_time_skip=ignore_time_skip,
            enable_contextual_rag=enable_contextual_rag,
            llm=llm,
        )

    except ConnectorStopSignal as e:
        logger.warning("Connector stop signal detected in index_doc_batch_with_handler")
        raise e
    except Exception as e:
        # don't log the batch directly, it's too much text
        document_ids = [doc.id for doc in document_batch]
        with sentry_sdk.new_scope() as scope:
            scope.set_tag("stage", "indexing_pipeline")
            scope.set_tag("tenant_id", tenant_id)
            scope.set_tag("batch_size", str(len(document_batch)))
            scope.set_extra("document_ids", document_ids)
            scope.fingerprint = ["indexing-pipeline-failure", type(e).__name__]
            sentry_sdk.capture_exception(e)
        logger.exception("Failed to index document batch: %s", document_ids)

        index_pipeline_result = IndexingPipelineResult(
            new_docs=0,
            total_docs=len(document_batch),
            total_chunks=0,
            failures=[
                ConnectorFailure(
                    failed_document=DocumentFailure(
                        document_id=document.id,
                        document_link=(
                            document.sections[0].link if document.sections else None
                        ),
                    ),
                    failure_message=str(e),
                    exception=e,
                )
                for document in document_batch
            ],
        )

    return index_pipeline_result


def _promote_new_staged_files(
    documents: list[Document],
    previous_file_ids: dict[str, str],
    db_session: Session,
) -> None:
    """Queue STAGING → CONNECTOR origin flips for every new file_id in the batch.

    Intended to run immediately before `_upsert_documents_in_db` so the origin
    flip lands in the same commit as the `Document.file_id` write. Does not
    commit — the caller's next commit flushes these UPDATEs.
    """
    for doc in documents:
        new_file_id = doc.file_id
        if new_file_id is None or new_file_id == previous_file_ids.get(doc.id):
            continue
        promote_staged_file(db_session=db_session, file_id=new_file_id)


def _delete_replaced_files(
    documents: list[Document],
    previous_file_ids: dict[str, str],
) -> None:
    """Best-effort blob deletes for file_ids replaced in this batch.

    Must run AFTER `Document.file_id` has been committed to the new
    file_id.
    """
    file_store = get_default_file_store()
    for doc in documents:
        new_file_id = doc.file_id
        old_file_id = previous_file_ids.get(doc.id)
        if old_file_id is None or old_file_id == new_file_id:
            continue
        try:
            file_store.delete_file(old_file_id, error_on_missing=False)
        except Exception:
            logger.exception("Failed to delete replaced file_id=%s.", old_file_id)


def index_doc_batch_prepare(
    documents: list[Document],
    index_attempt_metadata: IndexAttemptMetadata,
    db_session: Session,
    ignore_time_skip: bool = False,
) -> DocumentBatchPrepareContext | None:
    """Sets up the documents in the relational DB (source of truth) for permissions, metadata, etc.
    This preceeds indexing it into the actual document index."""
    documents = sanitize_documents_for_postgres(documents)

    # Create a trimmed list of docs that don't have a newer updated at
    # Shortcuts the time-consuming flow on connector index retries
    document_ids: list[str] = [document.id for document in documents]
    db_docs: list[DBDocument] = get_documents_by_ids(
        db_session=db_session,
        document_ids=document_ids,
    )

    # Capture previous file_ids BEFORE any writes so we know what to reap.
    previous_file_ids: dict[str, str] = {
        db_doc.id: db_doc.file_id for db_doc in db_docs if db_doc.file_id is not None
    }

    updatable_docs = (
        get_doc_ids_to_update(documents=documents, db_docs=db_docs)
        if not ignore_time_skip
        else documents
    )
    if len(updatable_docs) != len(documents):
        updatable_doc_ids = [doc.id for doc in updatable_docs]
        skipped_doc_ids = [
            doc.id for doc in documents if doc.id not in updatable_doc_ids
        ]
        logger.info(
            "Skipping %s documents because they are up to date. Skipped doc IDs: %s",
            len(skipped_doc_ids),
            skipped_doc_ids,
        )

    # for all updatable docs, upsert into the DB
    # Does not include doc_updated_at which is also used to indicate a successful update
    if updatable_docs:
        # Queue the STAGING → CONNECTOR origin flips BEFORE the Document upsert
        # so `upsert_documents`' commit flushes Document.file_id and the origin
        # flip atomically
        _promote_new_staged_files(
            documents=updatable_docs,
            previous_file_ids=previous_file_ids,
            db_session=db_session,
        )
        _upsert_documents_in_db(
            documents=updatable_docs,
            index_attempt_metadata=index_attempt_metadata,
            db_session=db_session,
        )
        # Blob deletes run only after Document.file_id is durable.
        _delete_replaced_files(
            documents=updatable_docs,
            previous_file_ids=previous_file_ids,
        )

    logger.info(
        "Upserted %s changed docs out of %s total docs into the DB",
        len(updatable_docs),
        len(documents),
    )

    # for all docs, upsert the document to cc pair relationship
    upsert_document_by_connector_credential_pair(
        db_session,
        index_attempt_metadata.connector_id,
        index_attempt_metadata.credential_id,
        document_ids,
    )

    # Link hierarchy nodes to documents for sources where pages can be both
    # hierarchy nodes AND documents (e.g., Notion, Confluence).
    # This must happen after documents are upserted due to FK constraint.
    if documents:
        link_hierarchy_nodes_to_documents(
            db_session=db_session,
            document_ids=document_ids,
            source=documents[0].source,
            commit=False,  # We'll commit with the rest of the transaction
        )

    # No docs to process because the batch is empty or every doc was already indexed
    if not updatable_docs:
        return None

    id_to_boost_map = {doc.id: doc.boost for doc in db_docs}
    return DocumentBatchPrepareContext(
        updatable_docs=updatable_docs, id_to_boost_map=id_to_boost_map
    )


def filter_documents(
    document_batch: list[Document],
) -> tuple[list[Document], list[ConnectorFailure]]:
    documents: list[Document] = []
    failures: list[ConnectorFailure] = []
    total_chars_in_batch = 0
    skipped_too_long = []

    for document in document_batch:
        empty_contents = not any(
            isinstance(section, TextSection)
            and section.text is not None
            and section.text.strip()
            for section in document.sections
        )
        if (
            (not document.title or not document.title.strip())
            and not document.semantic_identifier.strip()
            and empty_contents
        ):
            # Skip documents that have neither title nor content
            # If the document doesn't have either, then there is no useful information in it
            # This is again verified later in the pipeline after chunking but at that point there should
            # already be no documents that are empty.
            logger.warning(
                "Skipping document with ID %s as it has neither title nor content.",
                document.id,
            )
            continue

        if document.title is not None and not document.title.strip() and empty_contents:
            # The title is explicitly empty ("" and not None) and the document is empty
            # so when building the chunk text representation, it will be empty and unuseable
            logger.warning(
                "Skipping document with ID %s as the chunks will be empty.", document.id
            )
            continue

        section_chars = sum(
            (
                len(section.text)
                if isinstance(section, TextSection) and section.text is not None
                else 0
            )
            for section in document.sections
        )
        doc_total_chars = (
            len(document.title or document.semantic_identifier) + section_chars
        )

        if MAX_DOCUMENT_CHARS and doc_total_chars > MAX_DOCUMENT_CHARS:
            # Skip documents that are too long, later on there are more memory intensive steps done on the text
            # and the container will run out of memory and crash. Several other checks are included upstream but
            # those are at the connector level so a catchall is still needed.
            # Assumption here is that files that are that long, are generated files and not the type users
            # generally care for.
            logger.warning(
                "Skipping document with ID %s as it is too long (%s chars, max=%s)",
                document.id,
                format(doc_total_chars, ","),
                format(MAX_DOCUMENT_CHARS, ","),
            )
            skipped_too_long.append((document.id, doc_total_chars))
            failures.append(
                ConnectorFailure(
                    failed_document=DocumentFailure(
                        document_id=document.id,
                        document_link=(
                            document.sections[0].link if document.sections else None
                        ),
                    ),
                    failure_message=(
                        f"Document '{document.semantic_identifier}' is too large to index "
                        f"({format(doc_total_chars, ',')} chars). "
                        f"The limit is {format(MAX_DOCUMENT_CHARS, ',')} chars "
                        f"(set by MAX_DOCUMENT_CHARS). "
                        "Split the document into smaller parts to index it."
                    ),
                )
            )
            continue

        total_chars_in_batch += doc_total_chars
        documents.append(document)

    # Log batch statistics for OOM debugging
    if documents:
        avg_chars = total_chars_in_batch / len(documents)
        # Get the source from the first document (all in batch should be same source)
        source = documents[0].source.value if documents[0].source else "unknown"
        logger.debug(
            "Document batch filter [%s]: %s docs kept, %s skipped (too long). Total chars: %s, Avg: %s chars/doc",
            source,
            len(documents),
            len(skipped_too_long),
            format(total_chars_in_batch, ","),
            format(avg_chars, ",.0f"),
        )
        if skipped_too_long:
            logger.warning(
                "Skipped oversized documents [%s]: %s", source, skipped_too_long[:5]
            )  # Log first 5

    return documents, failures


def process_image_sections(documents: list[Document]) -> list[IndexingDocument]:
    """
    Process all sections in documents by:
    1. Converting both TextSection and ImageSection objects to base Section objects
    2. Processing ImageSections to generate text summaries using a vision-capable LLM
    3. Returning IndexingDocument objects with both original and processed sections

    Args:
        documents: List of documents with TextSection | ImageSection objects

    Returns:
        List of IndexingDocument objects with processed_sections as list[Section]
    """
    # Check if image extraction and analysis is enabled before trying to get a vision LLM.
    # Use section.type rather than isinstance because sections can round-trip
    # through pydantic as base Section instances (not the concrete subclass).
    has_image_section = any(
        section.type == SectionType.IMAGE
        for document in documents
        for section in document.sections
    )
    if not get_image_extraction_and_analysis_enabled() or not has_image_section:
        llm = None
    else:
        # Only get the vision LLM if image processing is enabled
        llm = get_default_llm_with_vision()

    if not llm:
        if get_image_extraction_and_analysis_enabled():
            logger.warning(
                "Image analysis is enabled but no vision-capable LLM is "
                "available — images will not be summarized. Configure a "
                "vision model in the admin LLM settings."
            )
        # Even without LLM, we still convert to IndexingDocument with base Sections
        return [
            IndexingDocument(
                **document.model_dump(),
                processed_sections=[
                    Section(
                        type=section.type,
                        text="" if isinstance(section, ImageSection) else section.text,
                        link=section.link,
                        image_file_id=(
                            section.image_file_id
                            if isinstance(section, ImageSection)
                            else None
                        ),
                    )
                    for section in document.sections
                ],
            )
            for document in documents
        ]

    indexed_documents: list[IndexingDocument] = []
    # Sections that need LLM summarization, paired with their image data.
    # Each Section is already placed in its document's processed_sections
    # list — we just fill in .text after the parallel run.
    pending: list[_PendingImageSummarization] = []
    file_store = get_default_file_store()

    for document in documents:
        processed_sections: list[Section] = []

        for section in document.sections:
            if not isinstance(section, ImageSection):
                processed_sections.append(
                    Section(
                        type=section.type,
                        text=section.text or "",
                        link=section.link,
                        image_file_id=None,
                    )
                )
                continue

            processed_section = Section(
                type=section.type,
                link=section.link,
                image_file_id=section.image_file_id,
                text="",
            )
            processed_sections.append(processed_section)

            try:
                file_record = file_store.read_file_record(file_id=section.image_file_id)
                if not file_record:
                    logger.warning(
                        "Image file %s not found in FileStore", section.image_file_id
                    )
                    processed_section.text = "[Image could not be processed]"
                    continue

                image_data = file_store.read_file(file_id=section.image_file_id).read()
                pending.append(
                    _PendingImageSummarization(
                        section=processed_section,
                        image_data=image_data,
                        context_name=file_record.display_name or "Image",
                    )
                )
            except Exception as e:
                logger.error("Error reading image section: %s", e)
                processed_section.text = "[Error processing image]"

        indexed_documents.append(
            IndexingDocument(
                **document.model_dump(), processed_sections=processed_sections
            )
        )

    # Summarize all images in parallel
    if pending:

        def _summarize(image_data: bytes, context_name: str) -> str:
            return (
                summarize_image_with_error_handling(
                    llm=llm, image_data=image_data, context_name=context_name
                )
                or "[Image could not be summarized]"
            )

        results = run_functions_tuples_in_parallel(
            [(_summarize, (p.image_data, p.context_name)) for p in pending],
            allow_failures=True,
            max_workers=MAX_IMAGE_WORKERS,
        )

        for p, result in zip(pending, results):
            p.section.text = result or "[Error processing image]"

    return indexed_documents


def add_document_summaries(
    chunks_by_doc: list[DocAwareChunk],
    llm: LLM,
    tokenizer: BaseTokenizer,
    trunc_doc_tokens: int,
) -> list[int] | None:
    """
    Adds a document summary to a list of chunks from the same document.
    Returns the number of tokens in the document.
    """

    doc_tokens = []
    # this is value is the same for each chunk in the document; 0 indicates
    # There is not enough space for contextual RAG (the chunk content
    # and possibly metadata took up too much space)
    if chunks_by_doc[0].contextual_rag_reserved_tokens == 0:
        return None

    doc_tokens = tokenizer.encode(chunks_by_doc[0].source_document.get_text_content())
    doc_content = tokenizer_trim_middle(doc_tokens, trunc_doc_tokens, tokenizer)

    # Apply prompt caching: cache the static prompt, document content is the suffix
    # Note: For document summarization, there's no cacheable prefix since the document changes
    # So we just pass the full prompt without caching
    summary_prompt = DOCUMENT_SUMMARY_PROMPT.format(document=doc_content)
    prompt_msg = UserMessage(content=summary_prompt)

    with llm_generation_span(
        llm=llm,
        flow=LLMFlow.CONTEXTUAL_RAG_DOC_SUMMARY,
        input_messages=[prompt_msg],
    ) as span_generation:
        response = llm.invoke(prompt_msg, max_tokens=MAX_CONTEXT_TOKENS)
        record_llm_response(span_generation, response)
    doc_summary = llm_response_to_string(response)

    for chunk in chunks_by_doc:
        chunk.doc_summary = doc_summary

    return doc_tokens


def add_chunk_summaries(
    chunks_by_doc: list[DocAwareChunk],
    llm: LLM,
    tokenizer: BaseTokenizer,
    trunc_doc_chunk_tokens: int,
    doc_tokens: list[int] | None,
) -> None:
    """
    Adds chunk summaries to the chunks grouped by document id.
    Chunk summaries look at the chunk as well as the entire document (or a summary,
    if the document is too long) and describe how the chunk relates to the document.
    """
    # all chunks within a document have the same contextual_rag_reserved_tokens
    if chunks_by_doc[0].contextual_rag_reserved_tokens == 0:
        return

    # use values computed in above doc summary section if available
    doc_tokens = doc_tokens or tokenizer.encode(
        chunks_by_doc[0].source_document.get_text_content()
    )
    doc_content = tokenizer_trim_middle(doc_tokens, trunc_doc_chunk_tokens, tokenizer)

    # only compute doc summary if needed
    doc_info = (
        doc_content
        if len(doc_tokens) <= MAX_TOKENS_FOR_FULL_INCLUSION
        else chunks_by_doc[0].doc_summary
    )
    if not doc_info:
        # This happens if the document is too long AND document summaries are turned off
        # In this case we compute a doc summary using the LLM
        fallback_prompt = UserMessage(
            content=DOCUMENT_SUMMARY_PROMPT.format(document=doc_content)
        )
        with llm_generation_span(
            llm=llm,
            flow=LLMFlow.CONTEXTUAL_RAG_DOC_SUMMARY,
            input_messages=[fallback_prompt],
        ) as span_generation:
            response = llm.invoke(fallback_prompt, max_tokens=MAX_CONTEXT_TOKENS)
            record_llm_response(span_generation, response)
        doc_info = llm_response_to_string(response)

    from onyx.llm.prompt_cache.processor import process_with_prompt_cache

    context_prompt1 = CONTEXTUAL_RAG_PROMPT1.format(document=doc_info)

    def assign_context(chunk: DocAwareChunk) -> None:
        context_prompt2 = CONTEXTUAL_RAG_PROMPT2.format(chunk=chunk.content)
        try:
            # Apply prompt caching: cache the document context (prompt1), chunk content is the suffix
            # For string inputs with continuation=True, the result will be a concatenated string
            processed_prompt, _ = process_with_prompt_cache(
                llm_config=llm.config,
                cacheable_prefix=UserMessage(content=context_prompt1),
                suffix=UserMessage(content=context_prompt2),
                continuation=True,  # Append chunk to the document context
            )

            with llm_generation_span(
                llm=llm,
                flow=LLMFlow.CONTEXTUAL_RAG_CHUNK_CONTEXT,
                input_messages=[processed_prompt],
            ) as span_generation:
                response = llm.invoke(processed_prompt, max_tokens=MAX_CONTEXT_TOKENS)
                record_llm_response(span_generation, response)
            chunk.chunk_context = llm_response_to_string(response)

        except LLMRateLimitError as e:
            # Erroring during chunker is undesirable, so we log the error and continue
            # TODO: for v2, add robust retry logic
            logger.exception("Rate limit adding chunk summary: %s", e, exc_info=e)
            chunk.chunk_context = ""
        except Exception as e:
            logger.exception("Error adding chunk summary: %s", e, exc_info=e)
            chunk.chunk_context = ""

    run_functions_tuples_in_parallel(
        functions_with_args=[(assign_context, (chunk,)) for chunk in chunks_by_doc],
        max_workers=MAX_CONTEXTUAL_RAG_WORKERS,
    )


def add_contextual_summaries(
    chunks: list[DocAwareChunk],
    llm: LLM,
    tokenizer: BaseTokenizer,
    chunk_token_limit: int,
) -> list[DocAwareChunk]:
    """
    Adds Document summary and chunk-within-document context to the chunks
    based on which environment variables are set.
    """
    doc2chunks = defaultdict(list)
    for chunk in chunks:
        doc2chunks[chunk.source_document.id].append(chunk)

    # The number of tokens allowed for the document when computing a document summary
    trunc_doc_summary_tokens = llm.config.max_input_tokens - len(
        tokenizer.encode(DOCUMENT_SUMMARY_PROMPT)
    )

    prompt_tokens = len(
        tokenizer.encode(CONTEXTUAL_RAG_PROMPT1 + CONTEXTUAL_RAG_PROMPT2)
    )
    # The number of tokens allowed for the document when computing a
    # "chunk in context of document" summary
    trunc_doc_chunk_tokens = (
        llm.config.max_input_tokens - prompt_tokens - chunk_token_limit
    )
    for chunks_by_doc in doc2chunks.values():
        doc_tokens = None
        if USE_DOCUMENT_SUMMARY:
            doc_tokens = add_document_summaries(
                chunks_by_doc, llm, tokenizer, trunc_doc_summary_tokens
            )

        if USE_CHUNK_SUMMARY:
            add_chunk_summaries(
                chunks_by_doc, llm, tokenizer, trunc_doc_chunk_tokens, doc_tokens
            )

    return chunks


def _verify_indexing_completeness(
    insertion_records: list[DocumentInsertionRecord],
    write_failures: list[ConnectorFailure],
    embedding_failed_doc_ids: set[str],
    updatable_ids: list[str],
    document_index_name: str,
) -> None:
    """Verify that every updatable document was either indexed or reported as failed."""
    all_returned_doc_ids = (
        {r.document_id for r in insertion_records}
        | {f.failed_document.document_id for f in write_failures if f.failed_document}
        | embedding_failed_doc_ids
    )
    if all_returned_doc_ids != set(updatable_ids):
        raise RuntimeError(
            f"Some documents were not successfully indexed. "
            f"Updatable IDs: {updatable_ids}, "
            f"Returned IDs: {all_returned_doc_ids}. "
            f"This should never happen. "
            f"This occured for document index {document_index_name}"
        )


def _apply_document_ingestion_hook(
    documents: list[Document],
    db_session: Session,
) -> list[Document]:
    """Apply the Document Ingestion hook to each document in the batch.

    - HookSkipped / HookSoftFailed → document passes through unchanged.
    - Response with sections=None → document is dropped (logged).
    - Response with sections → document sections are replaced with the hook's output.
    """

    def _build_payload(doc: Document) -> DocumentIngestionPayload:
        return DocumentIngestionPayload(
            document_id=doc.id or "",
            title=doc.title,
            semantic_identifier=doc.semantic_identifier,
            source=doc.source.value if doc.source is not None else "",
            sections=[
                DocumentIngestionSection(
                    text=s.text if isinstance(s, TextSection) else None,
                    link=s.link,
                    image_file_id=(
                        s.image_file_id if isinstance(s, ImageSection) else None
                    ),
                )
                for s in doc.sections
            ],
            metadata={
                k: v if isinstance(v, list) else [v] for k, v in doc.metadata.items()
            },
            doc_updated_at=(
                doc.doc_updated_at.isoformat() if doc.doc_updated_at else None
            ),
            primary_owners=(
                [
                    DocumentIngestionOwner(
                        display_name=o.get_semantic_name() or None,
                        email=o.email,
                    )
                    for o in doc.primary_owners
                ]
                if doc.primary_owners
                else None
            ),
            secondary_owners=(
                [
                    DocumentIngestionOwner(
                        display_name=o.get_semantic_name() or None,
                        email=o.email,
                    )
                    for o in doc.secondary_owners
                ]
                if doc.secondary_owners
                else None
            ),
        )

    def _apply_result(
        doc: Document,
        hook_result: DocumentIngestionResponse | HookSkipped | HookSoftFailed,
    ) -> Document | None:
        """Return the modified doc, original doc (skip/soft-fail), or None (drop)."""
        if isinstance(hook_result, (HookSkipped, HookSoftFailed)):
            return doc
        if not hook_result.sections:
            reason = hook_result.rejection_reason or "Document rejected by hook"
            logger.info(
                "Document ingestion hook dropped document doc_id=%r: %s", doc.id, reason
            )
            return None
        new_sections: list[TextSection | ImageSection] = []
        for s in hook_result.sections:
            if s.image_file_id is not None:
                new_sections.append(
                    ImageSection(image_file_id=s.image_file_id, link=s.link)
                )
            elif s.text is not None:
                new_sections.append(TextSection(text=s.text, link=s.link))
            else:
                logger.warning(
                    "Document ingestion hook returned a section with neither text nor image_file_id for doc_id=%r — skipping section.",
                    doc.id,
                )
        if not new_sections:
            logger.info(
                "Document ingestion hook produced no valid sections for doc_id=%r — dropping document.",
                doc.id,
            )
            return None
        return doc.model_copy(update={"sections": new_sections})

    if not documents:
        return documents

    # Run the hook for the first document. If it returns HookSkipped the hook
    # is not configured — skip the remaining N-1 DB lookups.
    first_doc = documents[0]
    first_payload = _build_payload(first_doc).model_dump()
    first_hook_result = execute_hook(
        db_session=db_session,
        hook_point=HookPoint.DOCUMENT_INGESTION,
        payload=first_payload,
        response_type=DocumentIngestionResponse,
    )
    if isinstance(first_hook_result, HookSkipped):
        return documents

    result: list[Document] = []
    first_applied = _apply_result(first_doc, first_hook_result)
    if first_applied is not None:
        result.append(first_applied)

    for doc in documents[1:]:
        payload = _build_payload(doc).model_dump()
        hook_result = execute_hook(
            db_session=db_session,
            hook_point=HookPoint.DOCUMENT_INGESTION,
            payload=payload,
            response_type=DocumentIngestionResponse,
        )
        applied = _apply_result(doc, hook_result)
        if applied is not None:
            result.append(applied)

    return result


@log_function_time(debug_only=True)
def index_doc_batch(
    *,
    document_batch: list[Document],
    chunker: Chunker,
    embedder: IndexingEmbedder,
    document_indices: list[DocumentIndex],
    request_id: str | None,
    tenant_id: str,
    db_session: Session,
    adapter: IndexingBatchAdapter,
    enable_contextual_rag: bool = False,
    llm: LLM | None = None,
    ignore_time_skip: bool = False,
    filter_fnc: Callable[
        [list[Document]], tuple[list[Document], list[ConnectorFailure]]
    ] = filter_documents,
) -> IndexingPipelineResult:
    """End-to-end indexing for a pre-batched set of documents."""
    """Takes different pieces of the indexing pipeline and applies it to a batch of documents
    Note that the documents should already be batched at this point so that it does not inflate the
    memory requirements

    Returns a tuple where the first element is the number of new docs and the
    second element is the number of chunks."""

    # Log connector info for debugging OOM issues
    connector_id = getattr(adapter, "connector_id", None)
    credential_id = getattr(adapter, "credential_id", None)
    logger.debug(
        "Starting index_doc_batch: connector_id=%s, credential_id=%s, tenant_id=%s, num_docs=%s",
        connector_id,
        credential_id,
        tenant_id,
        len(document_batch),
    )

    # Pull the attempt id off the adapter (when present) so per-stage metrics
    # can be attributed to the right ``IndexAttempt``. The protocol does not
    # mandate an ``index_attempt_metadata`` field, so non-attempt callers
    # (ingestion API, user file processing) get None and the
    # ``*_if_set`` helpers no-op.
    _attempt_metadata = getattr(adapter, "index_attempt_metadata", None)
    attempt_id: int | None = (
        _attempt_metadata.attempt_id if _attempt_metadata is not None else None
    )

    filtered_documents, filter_failures = filter_fnc(document_batch)
    filtered_documents = _apply_document_ingestion_hook(filtered_documents, db_session)
    with time_stage_if_set(IndexAttemptStage.DOC_DB_PREPARE, attempt_id):
        context = adapter.prepare(filtered_documents, ignore_time_skip)
    if not context:
        result = IndexingPipelineResult.empty(len(filtered_documents))
        result.failures.extend(filter_failures)
        return result

    # Convert documents to IndexingDocument objects with processed section.
    # Only record IMAGE_PROCESSING when there's actually image work to do --
    # otherwise the average/stddev gets polluted with no-op zero events.
    has_image_section = any(
        section.type == SectionType.IMAGE
        for document in context.updatable_docs
        for section in document.sections
    )
    if has_image_section:
        with time_stage_if_set(IndexAttemptStage.IMAGE_PROCESSING, attempt_id):
            context.indexable_docs = process_image_sections(context.updatable_docs)
    else:
        context.indexable_docs = process_image_sections(context.updatable_docs)

    doc_descriptors = [
        {
            "doc_id": doc.id,
            "doc_length": doc.get_total_char_length(),
        }
        for doc in context.indexable_docs
    ]
    logger.debug("Starting indexing process for documents: %s", doc_descriptors)

    logger.debug("Starting chunking")
    # NOTE: no special handling for failures here, since the chunker is not
    # a common source of failure for the indexing pipeline
    with time_stage_if_set(IndexAttemptStage.CHUNKING, attempt_id):
        chunks: list[DocAwareChunk] = chunker.chunk(context.indexable_docs)
    llm_tokenizer: BaseTokenizer | None = None

    # contextual RAG
    if enable_contextual_rag:
        assert llm is not None, "must provide an LLM for contextual RAG"
        llm_tokenizer = get_tokenizer(
            model_name=llm.config.model_name,
            provider_type=llm.config.model_provider,
        )

        # Because the chunker's tokens are different from the LLM's tokens,
        # We add a fudge factor to ensure we truncate prompts to the LLM's token limit
        with time_stage_if_set(IndexAttemptStage.CONTEXTUAL_RAG, attempt_id):
            chunks = add_contextual_summaries(
                chunks=chunks,
                llm=llm,
                tokenizer=llm_tokenizer,
                chunk_token_limit=chunker.chunk_token_limit * 2,
            )

    logger.debug("Starting embedding")
    # ``embed_and_stream`` records EMBEDDING internally so the timer captures
    # only the actual embedding work (which finishes before ``yield``), not
    # the surrounding vector-db write loop in the ``with`` body.
    with embed_and_stream(
        chunks, embedder, tenant_id, request_id, attempt_id=attempt_id
    ) as (
        embedding_result,
        chunk_store,
    ):
        updatable_ids = [doc.id for doc in context.updatable_docs]
        updatable_chunk_data = [
            UpdatableChunkData(
                chunk_id=chunk_id,
                document_id=document_id,
                boost_score=1.0,
            )
            for chunk_id, document_id in embedding_result.successful_chunk_ids
        ]

        embedding_failed_doc_ids = _get_failed_doc_ids(
            embedding_result.connector_failures
        )

        # Filter to only successfully embedded chunks so
        # doc_id_to_new_chunk_cnt reflects what's actually written to Vespa.
        embedded_chunks = [
            c for c in chunks if c.source_document.id not in embedding_failed_doc_ids
        ]

        # Acquires a lock on the documents so that no other process can modify
        # them.  Not needed until here, since this is when the actual race
        # condition with vector db can occur.
        with adapter.lock_context(context.updatable_docs):
            enricher = adapter.prepare_enrichment(
                context=context,
                tenant_id=tenant_id,
                chunks=embedded_chunks,
            )

            index_batch_params = IndexBatchParams(
                doc_id_to_previous_chunk_cnt=enricher.doc_id_to_previous_chunk_cnt,
                doc_id_to_new_chunk_cnt=enricher.doc_id_to_new_chunk_cnt,
                tenant_id=tenant_id,
                large_chunks_enabled=chunker.enable_large_chunks,
            )

            primary_doc_idx_insertion_records: list[DocumentInsertionRecord] | None = (
                None
            )
            primary_doc_idx_vector_db_write_failures: list[ConnectorFailure] | None = (
                None
            )

            # Sum vector-db write time across all configured indices and
            # record once per batch. Most deployments have a single index
            # (primary), but during a switchover both primary and secondary
            # are written; we want a single combined number per batch rather
            # than one event per index (avoids inflating event_count).
            vector_db_write_ms = 0
            for document_index in document_indices:

                def _enriched_stream() -> Iterator[DocMetadataAwareIndexChunk]:
                    for chunk in chunk_store.stream():
                        yield enricher.enrich_chunk(chunk, 1.0)

                vector_db_write_start = time.monotonic()
                insertion_records, write_failures = (
                    write_chunks_to_vector_db_with_backoff(
                        document_index=document_index,
                        make_chunks=_enriched_stream,
                        index_batch_params=index_batch_params,
                    )
                )
                vector_db_write_ms += max(
                    0, int((time.monotonic() - vector_db_write_start) * 1000)
                )

                _verify_indexing_completeness(
                    insertion_records=insertion_records,
                    write_failures=write_failures,
                    embedding_failed_doc_ids=embedding_failed_doc_ids,
                    updatable_ids=updatable_ids,
                    document_index_name=document_index.__class__.__name__,
                )
                # We treat the first document index we got as the primary one used
                # for reporting the state of indexing.
                if primary_doc_idx_insertion_records is None:
                    primary_doc_idx_insertion_records = insertion_records
                if primary_doc_idx_vector_db_write_failures is None:
                    primary_doc_idx_vector_db_write_failures = write_failures

            safe_record_single_event_if_set(
                IndexAttemptStage.VECTOR_DB_WRITE, attempt_id, vector_db_write_ms
            )

            with time_stage_if_set(IndexAttemptStage.POST_INDEX_DB_UPDATE, attempt_id):
                adapter.post_index(
                    context=context,
                    updatable_chunk_data=updatable_chunk_data,
                    filtered_documents=filtered_documents,
                    enrichment=enricher,
                )

    assert primary_doc_idx_insertion_records is not None
    assert primary_doc_idx_vector_db_write_failures is not None
    return IndexingPipelineResult(
        new_docs=sum(
            1 for r in primary_doc_idx_insertion_records if not r.already_existed
        ),
        total_docs=len(filtered_documents),
        total_chunks=len(embedding_result.successful_chunk_ids),
        failures=primary_doc_idx_vector_db_write_failures
        + embedding_result.connector_failures
        + filter_failures,
    )


def run_indexing_pipeline(
    *,
    document_batch: list[Document],
    request_id: str | None,
    embedder: IndexingEmbedder,
    document_indices: list[DocumentIndex],
    db_session: Session,
    tenant_id: str,
    adapter: IndexingBatchAdapter,
    chunker: Chunker | None = None,
    ignore_time_skip: bool = False,
) -> IndexingPipelineResult:
    """Builds a pipeline which takes in a list (batch) of docs and indexes them."""
    all_search_settings = get_active_search_settings(db_session)
    if (
        all_search_settings.secondary
        and all_search_settings.secondary.status == IndexModelStatus.FUTURE
    ):
        search_settings = all_search_settings.secondary
    else:
        search_settings = all_search_settings.primary

    multipass_config = get_multipass_config(search_settings)

    enable_contextual_rag = (
        search_settings.enable_contextual_rag or ENABLE_CONTEXTUAL_RAG
    )
    llm = None
    if enable_contextual_rag:
        llm = get_llm_for_contextual_rag(
            search_settings.contextual_rag_llm_name or DEFAULT_CONTEXTUAL_RAG_LLM_NAME,
            search_settings.contextual_rag_llm_provider
            or DEFAULT_CONTEXTUAL_RAG_LLM_PROVIDER,
        )

    chunker = chunker or Chunker(
        tokenizer=embedder.embedding_model.tokenizer,
        enable_multipass=multipass_config.multipass_indexing,
        enable_large_chunks=multipass_config.enable_large_chunks,
        enable_contextual_rag=enable_contextual_rag,
        # after every doc, update status in case there are a bunch of really long docs
    )

    return index_doc_batch_with_handler(
        chunker=chunker,
        embedder=embedder,
        document_indices=document_indices,
        document_batch=document_batch,
        request_id=request_id,
        tenant_id=tenant_id,
        db_session=db_session,
        adapter=adapter,
        enable_contextual_rag=enable_contextual_rag,
        llm=llm,
        ignore_time_skip=ignore_time_skip,
    )
