from functools import partial
from itertools import chain
from typing import Protocol

from sqlalchemy.orm import Session

from danswer.access.access import get_access_for_documents
from danswer.configs.constants import DEFAULT_BOOST
from danswer.connectors.cross_connector_utils.miscellaneous_utils import (
    get_experts_stores_representations,
)
from danswer.connectors.models import Document
from danswer.connectors.models import IndexAttemptMetadata
from danswer.db.document import get_documents_by_ids
from danswer.db.document import prepare_to_modify_documents
from danswer.db.document import update_docs_updated_at
from danswer.db.document import upsert_documents_complete
from danswer.db.document_set import fetch_document_sets_for_documents
from danswer.db.models import Document as DBDocument
from danswer.db.tag import create_or_add_document_tag
from danswer.db.tag import create_or_add_document_tag_list
from danswer.document_index.interfaces import DocumentIndex
from danswer.document_index.interfaces import DocumentMetadata
from danswer.indexing.chunker import Chunker
from danswer.indexing.chunker import DefaultChunker
from danswer.indexing.embedder import IndexingEmbedder
from danswer.indexing.models import DocAwareChunk
from danswer.indexing.models import DocMetadataAwareIndexChunk
from danswer.utils.logger import setup_logger
from danswer.utils.timing import log_function_time

logger = setup_logger()


class IndexingPipelineProtocol(Protocol):
    def __call__(
        self, documents: list[Document], index_attempt_metadata: IndexAttemptMetadata
    ) -> tuple[int, int]:
        ...


def upsert_documents_in_db(
    documents: list[Document],
    index_attempt_metadata: IndexAttemptMetadata,
    db_session: Session,
) -> None:
    # Metadata here refers to basic document info, not metadata about the actual content
    doc_m_batch: list[DocumentMetadata] = []
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
        doc_m_batch.append(db_doc_metadata)

    upsert_documents_complete(
        db_session=db_session,
        document_metadata_batch=doc_m_batch,
    )

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
            else:
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
    and the `updated_at` hasn't changed, we shouldn't need to do anything with it."""
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


@log_function_time()
def index_doc_batch(
    *,
    chunker: Chunker,
    embedder: IndexingEmbedder,
    document_index: DocumentIndex,
    documents: list[Document],
    index_attempt_metadata: IndexAttemptMetadata,
    db_session: Session,
    ignore_time_skip: bool = False,
) -> tuple[int, int]:
    """Takes different pieces of the indexing pipeline and applies it to a batch of documents
    Note that the documents should already be batched at this point so that it does not inflate the
    memory requirements"""
    document_ids = [document.id for document in documents]
    db_docs = get_documents_by_ids(
        document_ids=document_ids,
        db_session=db_session,
    )
    id_to_db_doc_map = {doc.id: doc for doc in db_docs}

    # Skip indexing docs that don't have a newer updated at
    # Shortcuts the time-consuming flow on connector index retries
    updatable_docs = (
        get_doc_ids_to_update(documents=documents, db_docs=db_docs)
        if not ignore_time_skip
        else documents
    )
    updatable_ids = [doc.id for doc in updatable_docs]

    # Create records in the source of truth about these documents,
    # does not include doc_updated_at which is also used to indicate a successful update
    upsert_documents_in_db(
        documents=documents,
        index_attempt_metadata=index_attempt_metadata,
        db_session=db_session,
    )

    logger.debug("Starting chunking")

    # The first chunk additionally contains the Title of the Document
    chunks: list[DocAwareChunk] = list(
        chain(*[chunker.chunk(document=document) for document in updatable_docs])
    )

    logger.debug("Starting embedding")
    chunks_with_embeddings = embedder.embed_chunks(chunks=chunks)

    # Acquires a lock on the documents so that no other process can modify them
    # NOTE: don't need to acquire till here, since this is when the actual race condition
    # with Vespa can occur.
    with prepare_to_modify_documents(db_session=db_session, document_ids=updatable_ids):
        # Attach the latest status from Postgres (source of truth for access) to each
        # chunk. This access status will be attached to each chunk in the document index
        # TODO: attach document sets to the chunk based on the status of Postgres as well
        document_id_to_access_info = get_access_for_documents(
            document_ids=updatable_ids, db_session=db_session
        )
        document_id_to_document_set = {
            document_id: document_sets
            for document_id, document_sets in fetch_document_sets_for_documents(
                document_ids=updatable_ids, db_session=db_session
            )
        }
        access_aware_chunks = [
            DocMetadataAwareIndexChunk.from_index_chunk(
                index_chunk=chunk,
                access=document_id_to_access_info[chunk.source_document.id],
                document_sets=set(
                    document_id_to_document_set.get(chunk.source_document.id, [])
                ),
                boost=(
                    id_to_db_doc_map[chunk.source_document.id].boost
                    if chunk.source_document.id in id_to_db_doc_map
                    else DEFAULT_BOOST
                ),
            )
            for chunk in chunks_with_embeddings
        ]

        logger.debug(
            f"Indexing the following chunks: {[chunk.to_short_descriptor() for chunk in chunks]}"
        )
        # A document will not be spread across different batches, so all the
        # documents with chunks in this set, are fully represented by the chunks
        # in this set
        insertion_records = document_index.index(chunks=access_aware_chunks)

        successful_doc_ids = [record.document_id for record in insertion_records]
        successful_docs = [
            doc for doc in updatable_docs if doc.id in successful_doc_ids
        ]

        # Update the time of latest version of the doc successfully indexed
        ids_to_new_updated_at = {}
        for doc in successful_docs:
            if doc.doc_updated_at is None:
                continue
            ids_to_new_updated_at[doc.id] = doc.doc_updated_at

        update_docs_updated_at(
            ids_to_new_updated_at=ids_to_new_updated_at, db_session=db_session
        )

    return len([r for r in insertion_records if r.already_existed is False]), len(
        chunks
    )


def build_indexing_pipeline(
    *,
    embedder: IndexingEmbedder,
    document_index: DocumentIndex,
    db_session: Session,
    chunker: Chunker | None = None,
    ignore_time_skip: bool = False,
) -> IndexingPipelineProtocol:
    """Builds a pipline which takes in a list (batch) of docs and indexes them."""
    chunker = chunker or DefaultChunker()

    return partial(
        index_doc_batch,
        chunker=chunker,
        embedder=embedder,
        document_index=document_index,
        ignore_time_skip=ignore_time_skip,
        db_session=db_session,
    )
