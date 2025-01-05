import traceback
from collections.abc import Callable
from functools import partial
from http import HTTPStatus
from typing import Protocol

import httpx
from pydantic import BaseModel
from pydantic import ConfigDict
from sqlalchemy.orm import Session

from onyx.access.access import get_access_for_documents
from onyx.access.models import DocumentAccess
from onyx.configs.app_configs import ENABLE_MULTIPASS_INDEXING
from onyx.configs.app_configs import INDEXING_EXCEPTION_LIMIT
from onyx.configs.app_configs import MAX_DOCUMENT_CHARS
from onyx.configs.constants import DEFAULT_BOOST
from onyx.connectors.cross_connector_utils.miscellaneous_utils import (
    get_experts_stores_representations,
)
from onyx.connectors.models import Document
from onyx.connectors.models import IndexAttemptMetadata
from onyx.db.document import fetch_chunk_counts_for_documents
from onyx.db.document import get_documents_by_ids
from onyx.db.document import prepare_to_modify_documents
from onyx.db.document import update_docs_chunk_count__no_commit
from onyx.db.document import update_docs_last_modified__no_commit
from onyx.db.document import update_docs_updated_at__no_commit
from onyx.db.document import upsert_document_by_connector_credential_pair
from onyx.db.document import upsert_documents
from onyx.db.document_set import fetch_document_sets_for_documents
from onyx.db.index_attempt import create_index_attempt_error
from onyx.db.models import Document as DBDocument
from onyx.db.search_settings import get_current_search_settings
from onyx.db.tag import create_or_add_document_tag
from onyx.db.tag import create_or_add_document_tag_list
from onyx.document_index.interfaces import DocumentIndex
from onyx.document_index.interfaces import DocumentMetadata
from onyx.document_index.interfaces import IndexBatchParams
from onyx.indexing.chunker import Chunker
from onyx.indexing.embedder import IndexingEmbedder
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.indexing.models import DocAwareChunk
from onyx.indexing.models import DocMetadataAwareIndexChunk
from onyx.utils.logger import setup_logger
from onyx.utils.timing import log_function_time
from shared_configs.enums import EmbeddingProvider

logger = setup_logger()


class DocumentBatchPrepareContext(BaseModel):
    updatable_docs: list[Document]
    id_to_db_doc_map: dict[str, DBDocument]
    model_config = ConfigDict(arbitrary_types_allowed=True)


class IndexingPipelineProtocol(Protocol):
    def __call__(
        self,
        document_batch: list[Document],
        index_attempt_metadata: IndexAttemptMetadata,
    ) -> tuple[int, int]:
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
    attempt_id: int | None,
    db_session: Session,
    ignore_time_skip: bool = False,
    tenant_id: str | None = None,
) -> tuple[int, int]:
    r = (0, 0)
    try:
        r = index_doc_batch(
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
        if isinstance(e, httpx.HTTPStatusError):
            if e.response.status_code == HTTPStatus.INSUFFICIENT_STORAGE:
                logger.error(
                    "NOTE: HTTP Status 507 Insufficient Storage indicates "
                    "you need to allocate more memory or disk space to the "
                    "Vespa/index container."
                )

        if INDEXING_EXCEPTION_LIMIT == 0:
            raise

        trace = traceback.format_exc()
        create_index_attempt_error(
            attempt_id,
            batch=index_attempt_metadata.batch_num,
            docs=document_batch,
            exception_msg=str(e),
            exception_traceback=trace,
            db_session=db_session,
        )
        logger.exception(
            f"Indexing batch {index_attempt_metadata.batch_num} failed. msg='{e}' trace='{trace}'"
        )

        index_attempt_metadata.num_exceptions += 1
        if index_attempt_metadata.num_exceptions == INDEXING_EXCEPTION_LIMIT:
            logger.warning(
                f"Maximum number of exceptions for this index attempt "
                f"({INDEXING_EXCEPTION_LIMIT}) has been reached. "
                f"The next exception will abort the indexing attempt."
            )
        elif index_attempt_metadata.num_exceptions > INDEXING_EXCEPTION_LIMIT:
            logger.warning(
                f"Maximum number of exceptions for this index attempt "
                f"({INDEXING_EXCEPTION_LIMIT}) has been exceeded."
            )
            raise RuntimeError(
                f"Maximum exception limit of {INDEXING_EXCEPTION_LIMIT} exceeded."
            )
        else:
            pass

    return r


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
        # Remove any NUL characters from title/semantic_id
        # This is a known issue with the Zendesk connector
        # Postgres cannot handle NUL characters in text fields
        if document.title:
            document.title = document.title.replace("\x00", "")
        if document.semantic_identifier:
            document.semantic_identifier = document.semantic_identifier.replace(
                "\x00", ""
            )

        # Remove NUL characters from all sections
        for section in document.sections:
            if section.text is not None:
                section.text = section.text.replace("\x00", "")

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
) -> tuple[int, int]:
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

    logger.debug("Filtering Documents")
    filtered_documents = filter_fnc(document_batch)

    ctx = index_doc_batch_prepare(
        documents=filtered_documents,
        index_attempt_metadata=index_attempt_metadata,
        ignore_time_skip=ignore_time_skip,
        db_session=db_session,
    )
    if not ctx:
        return 0, 0

    logger.debug("Starting chunking")
    chunks: list[DocAwareChunk] = chunker.chunk(ctx.updatable_docs)

    logger.debug("Starting embedding")
    chunks_with_embeddings = embedder.embed_chunks(chunks) if chunks else []

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
            f"Indexing the following chunks: {[chunk.to_short_descriptor() for chunk in access_aware_chunks]}"
        )
        # A document will not be spread across different batches, so all the
        # documents with chunks in this set, are fully represented by the chunks
        # in this set
        insertion_records = document_index.index(
            chunks=access_aware_chunks,
            index_batch_params=IndexBatchParams(
                doc_id_to_previous_chunk_cnt=doc_id_to_previous_chunk_cnt,
                doc_id_to_new_chunk_cnt=doc_id_to_new_chunk_cnt,
                tenant_id=tenant_id,
                large_chunks_enabled=chunker.enable_large_chunks,
            ),
        )

        successful_doc_ids = [record.document_id for record in insertion_records]
        successful_docs = [
            doc for doc in ctx.updatable_docs if doc.id in successful_doc_ids
        ]

        last_modified_ids = []
        ids_to_new_updated_at = {}
        for doc in successful_docs:
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

        db_session.commit()

    result = (
        len([r for r in insertion_records if r.already_existed is False]),
        len(access_aware_chunks),
    )

    return result


def check_enable_large_chunks_and_multipass(
    embedder: IndexingEmbedder, db_session: Session
) -> tuple[bool, bool]:
    search_settings = get_current_search_settings(db_session)
    multipass = (
        search_settings.multipass_indexing
        if search_settings
        else ENABLE_MULTIPASS_INDEXING
    )

    enable_large_chunks = (
        multipass
        and
        # Only local models that supports larger context are from Nomic
        (embedder.model_name.startswith("nomic-ai"))
        and
        # Cohere does not support larger context they recommend not going above 512 tokens
        embedder.provider_type != EmbeddingProvider.COHERE
    )
    return multipass, enable_large_chunks


def build_indexing_pipeline(
    *,
    embedder: IndexingEmbedder,
    document_index: DocumentIndex,
    db_session: Session,
    chunker: Chunker | None = None,
    ignore_time_skip: bool = False,
    attempt_id: int | None = None,
    tenant_id: str | None = None,
    callback: IndexingHeartbeatInterface | None = None,
) -> IndexingPipelineProtocol:
    """Builds a pipeline which takes in a list (batch) of docs and indexes them."""
    multipass, enable_large_chunks = check_enable_large_chunks_and_multipass(
        embedder, db_session
    )

    chunker = chunker or Chunker(
        tokenizer=embedder.embedding_model.tokenizer,
        enable_multipass=multipass,
        enable_large_chunks=enable_large_chunks,
        # after every doc, update status in case there are a bunch of really long docs
        callback=callback,
    )

    return partial(
        index_doc_batch_with_handler,
        chunker=chunker,
        embedder=embedder,
        document_index=document_index,
        ignore_time_skip=ignore_time_skip,
        attempt_id=attempt_id,
        db_session=db_session,
        tenant_id=tenant_id,
    )
