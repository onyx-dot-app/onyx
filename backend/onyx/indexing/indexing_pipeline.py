from collections.abc import Callable
from functools import partial
from typing import Protocol

from pydantic import BaseModel
from pydantic import ConfigDict
from sqlalchemy.orm import Session

from onyx.access.access import get_access_for_documents
from onyx.access.models import DocumentAccess
from onyx.configs.app_configs import MAX_DOCUMENT_CHARS
from onyx.configs.constants import DEFAULT_BOOST
from onyx.connectors.cross_connector_utils.miscellaneous_utils import (
    get_experts_stores_representations,
)
from onyx.connectors.models import ConnectorFailure
from onyx.connectors.models import Document
from onyx.connectors.models import DocumentFailure
from onyx.connectors.models import IndexAttemptMetadata
from onyx.db.document import fetch_chunk_counts_for_documents
from onyx.db.document import get_documents_by_ids
from onyx.db.document import mark_document_as_indexed_for_cc_pair__no_commit
from onyx.db.document import prepare_to_modify_documents
from onyx.db.document import update_docs_chunk_count__no_commit
from onyx.db.document import update_docs_last_modified__no_commit
from onyx.db.document import update_docs_updated_at__no_commit
from onyx.db.document import upsert_document_by_connector_credential_pair
from onyx.db.document import upsert_documents
from onyx.db.document_set import fetch_document_sets_for_documents
from onyx.db.models import Document as DBDocument
from onyx.db.search_settings import get_current_search_settings
from onyx.db.tag import create_or_add_document_tag
from onyx.db.tag import create_or_add_document_tag_list
from onyx.document_index.document_index_utils import (
    get_multipass_config,
)
from onyx.document_index.interfaces import DocumentIndex
from onyx.document_index.interfaces import DocumentMetadata
from onyx.document_index.interfaces import IndexBatchParams
from onyx.indexing.chunker import Chunker
from onyx.indexing.embedder import embed_chunks_with_failure_handling
from onyx.indexing.embedder import IndexingEmbedder
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.indexing.models import DocAwareChunk
from onyx.indexing.models import DocMetadataAwareIndexChunk
from onyx.indexing.vector_db_insertion import write_chunks_to_vector_db_with_backoff
from onyx.utils.logger import setup_logger
from onyx.utils.timing import log_function_time

logger = setup_logger()


class DocumentBatchPrepareContext(BaseModel):
    updatable_docs: list[Document]
    id_to_db_doc_map: dict[str, DBDocument]
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


class IndexingPipelineProtocol(Protocol):
    def __call__(
        self,
        document_batch: list[Document],
        index_attempt_metadata: IndexAttemptMetadata,
    ) -> IndexingPipelineResult:
        ...


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
        )
        document_metadata_list.append(db_doc_metadata)

    upsert_documents(db_session, document_metadata_list)

    # Insert document content metadata
    for doc in documents:
        for k, v in doc.metadata.items():
            if isinstance(v, list):
                create_or_add_document_tag_list(
                    tag_key=k,
                    tag_values=v,
                    source=doc.source,
                    document_id=doc.id,
                    db_session=db_session,
                )
                continue

            create_or_add_document_tag(
                tag_key=k,
                tag_value=v,
                source=doc.source,
                document_id=doc.id,
                db_session=db_session,
            )


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
    document_index: DocumentIndex,
    document_batch: list[Document],
    index_attempt_metadata: IndexAttemptMetadata,
    db_session: Session,
    ignore_time_skip: bool = False,
    tenant_id: str | None = None,
) -> IndexingPipelineResult:
    try:
        index_pipeline_result = index_doc_batch(
            chunker=chunker,
            embedder=embedder,
            document_index=document_index,
            document_batch=document_batch,
            index_attempt_metadata=index_attempt_metadata,
            db_session=db_session,
            ignore_time_skip=ignore_time_skip,
            tenant_id=tenant_id,
        )
    except Exception as e:
        logger.exception(f"Failed to index document batch: {document_batch}")
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


def index_doc_batch_prepare(
    documents: list[Document],
    index_attempt_metadata: IndexAttemptMetadata,
    db_session: Session,
    ignore_time_skip: bool = False,
) -> DocumentBatchPrepareContext | None:
    """Sets up the documents in the relational DB (source of truth) for permissions, metadata, etc.
    This preceeds indexing it into the actual document index."""
    # Create a trimmed list of docs that don't have a newer updated at
    # Shortcuts the time-consuming flow on connector index retries
    document_ids: list[str] = [document.id for document in documents]
    db_docs: list[DBDocument] = get_documents_by_ids(
        db_session=db_session,
        document_ids=document_ids,
    )

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
            f"Skipping {len(skipped_doc_ids)} documents "
            f"because they are up to date. Skipped doc IDs: {skipped_doc_ids}"
        )

    # for all updatable docs, upsert into the DB
    # Does not include doc_updated_at which is also used to indicate a successful update
    if updatable_docs:
        _upsert_documents_in_db(
            documents=updatable_docs,
            index_attempt_metadata=index_attempt_metadata,
            db_session=db_session,
        )

    logger.info(
        f"Upserted {len(updatable_docs)} changed docs out of "
        f"{len(documents)} total docs into the DB"
    )

    # for all docs, upsert the document to cc pair relationship
    upsert_document_by_connector_credential_pair(
        db_session,
        index_attempt_metadata.connector_id,
        index_attempt_metadata.credential_id,
        document_ids,
    )

    # No docs to process because the batch is empty or every doc was already indexed
    if not updatable_docs:
        return None

    id_to_db_doc_map = {doc.id: doc for doc in db_docs}
    return DocumentBatchPrepareContext(
        updatable_docs=updatable_docs, id_to_db_doc_map=id_to_db_doc_map
    )


def filter_documents(document_batch: list[Document]) -> list[Document]:
    documents: list[Document] = []
    for document in document_batch:
        empty_contents = not any(section.text.strip() for section in document.sections)
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
                f"Skipping document with ID {document.id} as it has neither title nor content."
            )
            continue

        if document.title is not None and not document.title.strip() and empty_contents:
            # The title is explicitly empty ("" and not None) and the document is empty
            # so when building the chunk text representation, it will be empty and unuseable
            logger.warning(
                f"Skipping document with ID {document.id} as the chunks will be empty."
            )
            continue

        section_chars = sum(len(section.text) for section in document.sections)
        if (
            MAX_DOCUMENT_CHARS
            and len(document.title or document.semantic_identifier) + section_chars
            > MAX_DOCUMENT_CHARS
        ):
            # Skip documents that are too long, later on there are more memory intensive steps done on the text
            # and the container will run out of memory and crash. Several other checks are included upstream but
            # those are at the connector level so a catchall is still needed.
            # Assumption here is that files that are that long, are generated files and not the type users
            # generally care for.
            logger.warning(
                f"Skipping document with ID {document.id} as it is too long."
            )
            continue

        documents.append(document)
    return documents


@log_function_time(debug_only=True)
def index_doc_batch(
    *,
    document_batch: list[Document],
    chunker: Chunker,
    embedder: IndexingEmbedder,
    document_index: DocumentIndex,
    index_attempt_metadata: IndexAttemptMetadata,
    db_session: Session,
    ignore_time_skip: bool = False,
    tenant_id: str | None = None,
    filter_fnc: Callable[[list[Document]], list[Document]] = filter_documents,
) -> IndexingPipelineResult:
    """Takes different pieces of the indexing pipeline and applies it to a batch of documents
    Note that the documents should already be batched at this point so that it does not inflate the
    memory requirements

    Returns a tuple where the first element is the number of new docs and the
    second element is the number of chunks."""

    no_access = DocumentAccess.build(
        user_emails=[],
        user_groups=[],
        external_user_emails=[],
        external_user_group_ids=[],
        is_public=False,
    )

    filtered_documents = filter_fnc(document_batch)

    ctx = index_doc_batch_prepare(
        documents=filtered_documents,
        index_attempt_metadata=index_attempt_metadata,
        ignore_time_skip=ignore_time_skip,
        db_session=db_session,
    )
    if not ctx:
        # even though we didn't actually index anything, we should still
        # mark them as "completed" for the CC Pair in order to make the
        # counts match
        mark_document_as_indexed_for_cc_pair__no_commit(
            connector_id=index_attempt_metadata.connector_id,
            credential_id=index_attempt_metadata.credential_id,
            document_ids=[doc.id for doc in filtered_documents],
            db_session=db_session,
        )
        db_session.commit()
        return IndexingPipelineResult(
            new_docs=0,
            total_docs=len(filtered_documents),
            total_chunks=0,
            failures=[],
        )

    doc_descriptors = [
        {
            "doc_id": doc.id,
            "doc_length": doc.get_total_char_length(),
        }
        for doc in ctx.updatable_docs
    ]
    logger.debug(f"Starting indexing process for documents: {doc_descriptors}")

    logger.debug("Starting chunking")
    # NOTE: no special handling for failures here, since the chunker is not
    # a common source of failure for the indexing pipeline
    chunks: list[DocAwareChunk] = chunker.chunk(ctx.updatable_docs)

    logger.debug("Starting embedding")
    chunks_with_embeddings, embedding_failures = (
        embed_chunks_with_failure_handling(
            chunks=chunks,
            embedder=embedder,
        )
        if chunks
        else ([], [])
    )

    updatable_ids = [doc.id for doc in ctx.updatable_docs]

    # Acquires a lock on the documents so that no other process can modify them
    # NOTE: don't need to acquire till here, since this is when the actual race condition
    # with Vespa can occur.
    with prepare_to_modify_documents(db_session=db_session, document_ids=updatable_ids):
        doc_id_to_access_info = get_access_for_documents(
            document_ids=updatable_ids, db_session=db_session
        )
        doc_id_to_document_set = {
            document_id: document_sets
            for document_id, document_sets in fetch_document_sets_for_documents(
                document_ids=updatable_ids, db_session=db_session
            )
        }

        doc_id_to_previous_chunk_cnt: dict[str, int | None] = {
            document_id: chunk_count
            for document_id, chunk_count in fetch_chunk_counts_for_documents(
                document_ids=updatable_ids,
                db_session=db_session,
            )
        }

        doc_id_to_new_chunk_cnt: dict[str, int] = {
            document_id: len(
                [
                    chunk
                    for chunk in chunks_with_embeddings
                    if chunk.source_document.id == document_id
                ]
            )
            for document_id in updatable_ids
        }

        # we're concerned about race conditions where multiple simultaneous indexings might result
        # in one set of metadata overwriting another one in vespa.
        # we still write data here for the immediate and most likely correct sync, but
        # to resolve this, an update of the last modified field at the end of this loop
        # always triggers a final metadata sync via the celery queue
        access_aware_chunks = [
            DocMetadataAwareIndexChunk.from_index_chunk(
                index_chunk=chunk,
                access=doc_id_to_access_info.get(chunk.source_document.id, no_access),
                document_sets=set(
                    doc_id_to_document_set.get(chunk.source_document.id, [])
                ),
                boost=(
                    ctx.id_to_db_doc_map[chunk.source_document.id].boost
                    if chunk.source_document.id in ctx.id_to_db_doc_map
                    else DEFAULT_BOOST
                ),
                tenant_id=tenant_id,
            )
            for chunk in chunks_with_embeddings
        ]

        logger.debug(
            "Indexing the following chunks: "
            f"{[chunk.to_short_descriptor() for chunk in access_aware_chunks]}"
        )
        # A document will not be spread across different batches, so all the
        # documents with chunks in this set, are fully represented by the chunks
        # in this set
        (
            insertion_records,
            vector_db_write_failures,
        ) = write_chunks_to_vector_db_with_backoff(
            document_index=document_index,
            chunks=access_aware_chunks,
            index_batch_params=IndexBatchParams(
                doc_id_to_previous_chunk_cnt=doc_id_to_previous_chunk_cnt,
                doc_id_to_new_chunk_cnt=doc_id_to_new_chunk_cnt,
                tenant_id=tenant_id,
                large_chunks_enabled=chunker.enable_large_chunks,
            ),
        )

        successful_doc_ids = {record.document_id for record in insertion_records}
        if successful_doc_ids != set(updatable_ids):
            raise RuntimeError(
                f"Some documents were not successfully indexed. "
                f"Updatable IDs: {updatable_ids}, "
                f"Successful IDs: {successful_doc_ids}"
            )

        last_modified_ids = []
        ids_to_new_updated_at = {}
        for doc in ctx.updatable_docs:
            last_modified_ids.append(doc.id)
            # doc_updated_at is the source's idea (on the other end of the connector)
            # of when the doc was last modified
            if doc.doc_updated_at is None:
                continue
            ids_to_new_updated_at[doc.id] = doc.doc_updated_at

        update_docs_updated_at__no_commit(
            ids_to_new_updated_at=ids_to_new_updated_at, db_session=db_session
        )

        update_docs_last_modified__no_commit(
            document_ids=last_modified_ids, db_session=db_session
        )

        update_docs_chunk_count__no_commit(
            document_ids=updatable_ids,
            doc_id_to_chunk_count=doc_id_to_new_chunk_cnt,
            db_session=db_session,
        )

        # these documents can now be counted as part of the CC Pairs
        # document count, so we need to mark them as indexed
        # NOTE: even documents we skipped since they were already up
        # to date should be counted here in order to maintain parity
        # between CC Pair and index attempt counts
        mark_document_as_indexed_for_cc_pair__no_commit(
            connector_id=index_attempt_metadata.connector_id,
            credential_id=index_attempt_metadata.credential_id,
            document_ids=[doc.id for doc in filtered_documents],
            db_session=db_session,
        )

        db_session.commit()

    result = IndexingPipelineResult(
        new_docs=len([r for r in insertion_records if r.already_existed is False]),
        total_docs=len(filtered_documents),
        total_chunks=len(access_aware_chunks),
        failures=vector_db_write_failures + embedding_failures,
    )

    return result


def build_indexing_pipeline(
    *,
    embedder: IndexingEmbedder,
    document_index: DocumentIndex,
    db_session: Session,
    chunker: Chunker | None = None,
    ignore_time_skip: bool = False,
    tenant_id: str | None = None,
    callback: IndexingHeartbeatInterface | None = None,
) -> IndexingPipelineProtocol:
    """Builds a pipeline which takes in a list (batch) of docs and indexes them."""
    search_settings = get_current_search_settings(db_session)
    multipass_config = get_multipass_config(search_settings)

    chunker = chunker or Chunker(
        tokenizer=embedder.embedding_model.tokenizer,
        enable_multipass=multipass_config.multipass_indexing,
        enable_large_chunks=multipass_config.enable_large_chunks,
        # after every doc, update status in case there are a bunch of really long docs
        callback=callback,
    )

    return partial(
        index_doc_batch_with_handler,
        chunker=chunker,
        embedder=embedder,
        document_index=document_index,
        ignore_time_skip=ignore_time_skip,
        db_session=db_session,
        tenant_id=tenant_id,
    )
