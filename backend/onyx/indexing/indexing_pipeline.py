from collections import defaultdict
from collections.abc import Callable
from typing import Protocol

from pydantic import BaseModel
from pydantic import ConfigDict
from sqlalchemy.orm import Session

from onyx.configs.app_configs import DEFAULT_CONTEXTUAL_RAG_LLM_NAME
from onyx.configs.app_configs import DEFAULT_CONTEXTUAL_RAG_LLM_PROVIDER
from onyx.configs.app_configs import ENABLE_CONTEXTUAL_RAG
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
from onyx.connectors.models import TextSection
from onyx.db.document import get_documents_by_ids
from onyx.db.document import upsert_document_by_connector_credential_pair
from onyx.db.document import upsert_documents
from onyx.db.models import Document as DBDocument
from onyx.db.models import IndexModelStatus
from onyx.db.search_settings import get_active_search_settings
from onyx.db.tag import upsert_document_tags
from onyx.document_index.document_index_utils import (
    get_multipass_config,
)
from onyx.document_index.interfaces import DocumentIndex
from onyx.document_index.interfaces import DocumentMetadata
from onyx.document_index.interfaces import IndexBatchParams
from onyx.file_processing.image_summarization import summarize_image_with_error_handling
from onyx.file_store.file_store import get_default_file_store
from onyx.indexing.chunker import Chunker
from onyx.indexing.embedder import embed_chunks_with_failure_handling
from onyx.indexing.embedder import IndexingEmbedder
from onyx.indexing.models import DocAwareChunk
from onyx.indexing.models import IndexingBatchAdapter
from onyx.indexing.models import UpdatableChunkData
from onyx.indexing.vector_db_insertion import write_chunks_to_vector_db_with_backoff
from onyx.llm.factory import get_default_llm_with_vision
from onyx.llm.factory import get_llm_for_contextual_rag
from onyx.llm.interfaces import LLM
from onyx.llm.multi_llm import LLMRateLimitError
from onyx.llm.utils import llm_response_to_string
from onyx.llm.utils import MAX_CONTEXT_TOKENS
from onyx.natural_language_processing.utils import BaseTokenizer
from onyx.natural_language_processing.utils import get_tokenizer
from onyx.natural_language_processing.utils import tokenizer_trim_middle
from onyx.prompts.contextual_retrieval import CONTEXTUAL_RAG_PROMPT1
from onyx.prompts.contextual_retrieval import CONTEXTUAL_RAG_PROMPT2
from onyx.prompts.contextual_retrieval import DOCUMENT_SUMMARY_PROMPT
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import run_functions_tuples_in_parallel
from onyx.utils.timing import log_function_time


logger = setup_logger()


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
    request_id: str | None,
    tenant_id: str,
    adapter: IndexingBatchAdapter,
    ignore_time_skip: bool = False,
    enable_contextual_rag: bool = False,
    llm: LLM | None = None,
) -> IndexingPipelineResult:
    try:
        index_pipeline_result = index_doc_batch(
            chunker=chunker,
            embedder=embedder,
            document_index=document_index,
            document_batch=document_batch,
            request_id=request_id,
            tenant_id=tenant_id,
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
        logger.exception(f"Failed to index document batch: {document_ids}")

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

    id_to_boost_map = {doc.id: doc.boost for doc in db_docs}
    return DocumentBatchPrepareContext(
        updatable_docs=updatable_docs, id_to_boost_map=id_to_boost_map
    )


def filter_documents(document_batch: list[Document]) -> list[Document]:
    documents: list[Document] = []
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
                f"Skipping document with ID {document.id} as it is too long "
                f"({doc_total_chars:,} chars, max={MAX_DOCUMENT_CHARS:,})"
            )
            skipped_too_long.append((document.id, doc_total_chars))
            continue

        total_chars_in_batch += doc_total_chars
        documents.append(document)

    # Log batch statistics for OOM debugging
    if documents:
        avg_chars = total_chars_in_batch / len(documents)
        # Get the source from the first document (all in batch should be same source)
        source = documents[0].source.value if documents[0].source else "unknown"
        logger.debug(
            f"Document batch filter [{source}]: {len(documents)} docs kept, {len(skipped_too_long)} skipped (too long). "
            f"Total chars: {total_chars_in_batch:,}, Avg: {avg_chars:,.0f} chars/doc"
        )
        if skipped_too_long:
            logger.warning(
                f"Skipped oversized documents [{source}]: {skipped_too_long[:5]}"
            )  # Log first 5

    return documents


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
    # Check if image extraction and analysis is enabled before trying to get a vision LLM
    if not get_image_extraction_and_analysis_enabled():
        llm = None
    else:
        # Only get the vision LLM if image processing is enabled
        llm = get_default_llm_with_vision()

    if not llm:
        # Even without LLM, we still convert to IndexingDocument with base Sections
        return [
            IndexingDocument(
                **document.model_dump(),
                processed_sections=[
                    Section(
                        text=section.text if isinstance(section, TextSection) else "",
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

    for document in documents:
        processed_sections: list[Section] = []

        for section in document.sections:
            # For ImageSection, process and create base Section with both text and image_file_id
            if isinstance(section, ImageSection):
                # Default section with image path preserved - ensure text is always a string
                processed_section = Section(
                    link=section.link,
                    image_file_id=section.image_file_id,
                    text="",  # Initialize with empty string
                )

                # Try to get image summary
                try:
                    file_store = get_default_file_store()

                    file_record = file_store.read_file_record(
                        file_id=section.image_file_id
                    )
                    if not file_record:
                        logger.warning(
                            f"Image file {section.image_file_id} not found in FileStore"
                        )

                        processed_section.text = "[Image could not be processed]"
                    else:
                        # Get the image data
                        image_data_io = file_store.read_file(
                            file_id=section.image_file_id
                        )
                        image_data = image_data_io.read()
                        summary = summarize_image_with_error_handling(
                            llm=llm,
                            image_data=image_data,
                            context_name=file_record.display_name or "Image",
                        )

                        if summary:
                            processed_section.text = summary
                        else:
                            processed_section.text = "[Image could not be summarized]"
                except Exception as e:
                    logger.error(f"Error processing image section: {e}")
                    processed_section.text = "[Error processing image]"

                processed_sections.append(processed_section)

            # For TextSection, create a base Section with text and link
            elif isinstance(section, TextSection):
                processed_section = Section(
                    text=section.text or "",  # Ensure text is always a string, not None
                    link=section.link,
                    image_file_id=None,
                )
                processed_sections.append(processed_section)

        # Create IndexingDocument with original sections and processed_sections
        indexed_document = IndexingDocument(
            **document.model_dump(), processed_sections=processed_sections
        )
        indexed_documents.append(indexed_document)

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
    doc_summary = llm_response_to_string(
        llm.invoke(summary_prompt, max_tokens=MAX_CONTEXT_TOKENS)
    )

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
        doc_info = llm_response_to_string(
            llm.invoke(
                DOCUMENT_SUMMARY_PROMPT.format(document=doc_content),
                max_tokens=MAX_CONTEXT_TOKENS,
            )
        )

    from onyx.llm.prompt_cache.processor import process_with_prompt_cache

    context_prompt1 = CONTEXTUAL_RAG_PROMPT1.format(document=doc_info)

    def assign_context(chunk: DocAwareChunk) -> None:
        context_prompt2 = CONTEXTUAL_RAG_PROMPT2.format(chunk=chunk.content)
        try:
            # Apply prompt caching: cache the document context (prompt1), chunk content is the suffix
            # For string inputs with continuation=True, the result will be a concatenated string
            processed_prompt, _ = process_with_prompt_cache(
                llm_config=llm.config,
                cacheable_prefix=context_prompt1,
                suffix=context_prompt2,
                continuation=True,  # Append chunk to the document context
            )

            chunk.chunk_context = llm_response_to_string(
                llm.invoke(
                    processed_prompt,
                    max_tokens=MAX_CONTEXT_TOKENS,
                )
            )

        except LLMRateLimitError as e:
            # Erroring during chunker is undesirable, so we log the error and continue
            # TODO: for v2, add robust retry logic
            logger.exception(f"Rate limit adding chunk summary: {e}", exc_info=e)
            chunk.chunk_context = ""
        except Exception as e:
            logger.exception(f"Error adding chunk summary: {e}", exc_info=e)
            chunk.chunk_context = ""

    run_functions_tuples_in_parallel(
        [(assign_context, (chunk,)) for chunk in chunks_by_doc]
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


@log_function_time(debug_only=True)
def index_doc_batch(
    *,
    document_batch: list[Document],
    chunker: Chunker,
    embedder: IndexingEmbedder,
    document_index: DocumentIndex,
    request_id: str | None,
    tenant_id: str,
    adapter: IndexingBatchAdapter,
    enable_contextual_rag: bool = False,
    llm: LLM | None = None,
    ignore_time_skip: bool = False,
    filter_fnc: Callable[[list[Document]], list[Document]] = filter_documents,
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
        f"Starting index_doc_batch: connector_id={connector_id}, "
        f"credential_id={credential_id}, tenant_id={tenant_id}, "
        f"num_docs={len(document_batch)}"
    )

    filtered_documents = filter_fnc(document_batch)
    context = adapter.prepare(filtered_documents, ignore_time_skip)
    if not context:
        return IndexingPipelineResult(
            new_docs=0,
            total_docs=len(filtered_documents),
            total_chunks=0,
            failures=[],
        )

    # Convert documents to IndexingDocument objects with processed section
    # logger.debug("Processing image sections")
    context.indexable_docs = process_image_sections(context.updatable_docs)

    doc_descriptors = [
        {
            "doc_id": doc.id,
            "doc_length": doc.get_total_char_length(),
        }
        for doc in context.indexable_docs
    ]
    logger.debug(f"Starting indexing process for documents: {doc_descriptors}")

    logger.debug("Starting chunking")
    # NOTE: no special handling for failures here, since the chunker is not
    # a common source of failure for the indexing pipeline
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
        chunks = add_contextual_summaries(
            chunks=chunks,
            llm=llm,
            tokenizer=llm_tokenizer,
            chunk_token_limit=chunker.chunk_token_limit * 2,
        )

    logger.debug("Starting embedding")
    chunks_with_embeddings, embedding_failures = (
        embed_chunks_with_failure_handling(
            chunks=chunks,
            embedder=embedder,
            tenant_id=tenant_id,
            request_id=request_id,
        )
        if chunks
        else ([], [])
    )

    chunk_content_scores = [1.0] * len(chunks_with_embeddings)

    updatable_ids = [doc.id for doc in context.updatable_docs]
    updatable_chunk_data = [
        UpdatableChunkData(
            chunk_id=chunk.chunk_id,
            document_id=chunk.source_document.id,
            boost_score=score,
        )
        for chunk, score in zip(chunks_with_embeddings, chunk_content_scores)
    ]

    # Acquires a lock on the documents so that no other process can modify them
    # NOTE: don't need to acquire till here, since this is when the actual race condition
    # with Vespa can occur.
    with adapter.lock_context(context.updatable_docs):
        # we're concerned about race conditions where multiple simultaneous indexings might result
        # in one set of metadata overwriting another one in vespa.
        # we still write data here for the immediate and most likely correct sync, but
        # to resolve this, an update of the last modified field at the end of this loop
        # always triggers a final metadata sync via the celery queue
        result = adapter.build_metadata_aware_chunks(
            chunks_with_embeddings=chunks_with_embeddings,
            chunk_content_scores=chunk_content_scores,
            tenant_id=tenant_id,
            context=context,
        )

        short_descriptor_list = [chunk.to_short_descriptor() for chunk in result.chunks]
        short_descriptor_log = str(short_descriptor_list)[:1024]
        logger.debug(f"Indexing the following chunks: {short_descriptor_log}")

        # A document will not be spread across different batches, so all the
        # documents with chunks in this set, are fully represented by the chunks
        # in this set
        (
            insertion_records,
            vector_db_write_failures,
        ) = write_chunks_to_vector_db_with_backoff(
            document_index=document_index,
            chunks=result.chunks,
            index_batch_params=IndexBatchParams(
                doc_id_to_previous_chunk_cnt=result.doc_id_to_previous_chunk_cnt,
                doc_id_to_new_chunk_cnt=result.doc_id_to_new_chunk_cnt,
                tenant_id=tenant_id,
                large_chunks_enabled=chunker.enable_large_chunks,
            ),
        )

        all_returned_doc_ids = (
            {record.document_id for record in insertion_records}
            .union(
                {
                    record.failed_document.document_id
                    for record in vector_db_write_failures
                    if record.failed_document
                }
            )
            .union(
                {
                    record.failed_document.document_id
                    for record in embedding_failures
                    if record.failed_document
                }
            )
        )
        if all_returned_doc_ids != set(updatable_ids):
            raise RuntimeError(
                f"Some documents were not successfully indexed. "
                f"Updatable IDs: {updatable_ids}, "
                f"Returned IDs: {all_returned_doc_ids}. "
                "This should never happen."
            )

        adapter.post_index(
            context=context,
            updatable_chunk_data=updatable_chunk_data,
            filtered_documents=filtered_documents,
            result=result,
        )

    return IndexingPipelineResult(
        new_docs=len([r for r in insertion_records if not r.already_existed]),
        total_docs=len(filtered_documents),
        total_chunks=len(chunks_with_embeddings),
        failures=vector_db_write_failures + embedding_failures,
    )


def run_indexing_pipeline(
    *,
    document_batch: list[Document],
    request_id: str | None,
    embedder: IndexingEmbedder,
    document_index: DocumentIndex,
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
        document_index=document_index,
        document_batch=document_batch,
        request_id=request_id,
        tenant_id=tenant_id,
        adapter=adapter,
        enable_contextual_rag=enable_contextual_rag,
        llm=llm,
        ignore_time_skip=ignore_time_skip,
    )
