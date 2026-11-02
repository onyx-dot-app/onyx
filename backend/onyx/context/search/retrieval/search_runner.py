from collections.abc import Callable
from uuid import UUID

from sqlalchemy.orm import Session

from onyx.configs.chat_configs import HYBRID_ALPHA, NUM_RETURNED_HITS
from onyx.configs.constants import DocumentSource
from onyx.connectors.event_inbox.sources import load_event_sources
from onyx.context.search.enrichment.registry import enrichment_source_types
from onyx.context.search.enrichment.retrieval import (
    EnrichmentContext,
    get_enrichment_contexts,
)
from onyx.context.search.enums import QueryType
from onyx.context.search.models import (
    ChunkIndexRequest,
    IndexFilters,
    InferenceChunk,
    InferenceSection,
)
from onyx.context.search.utils import get_query_embedding, inference_section_from_chunks
from onyx.db.models import User
from onyx.document_index.interfaces import DocumentIndex, DocumentSectionRequest
from onyx.federated_connectors.federated_retrieval import (
    FederatedRetrievalInfo,
    get_federated_retrieval_functions,
)
from onyx.natural_language_processing.search_nlp_models import EmbeddingModel
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import run_functions_tuples_in_parallel

logger = setup_logger()


def combine_retrieval_results(
    chunk_sets: list[list[InferenceChunk]],
) -> list[InferenceChunk]:
    all_chunks = [chunk for chunk_set in chunk_sets for chunk in chunk_set]

    unique_chunks: dict[tuple[str, int], InferenceChunk] = {}
    for chunk in all_chunks:
        key = (chunk.document_id, chunk.chunk_id)
        if key not in unique_chunks:
            unique_chunks[key] = chunk
            continue

        stored_chunk_score = unique_chunks[key].score or 0
        this_chunk_score = chunk.score or 0
        if stored_chunk_score < this_chunk_score:
            unique_chunks[key] = chunk

    sorted_chunks = sorted(
        unique_chunks.values(), key=lambda x: x.score or 0, reverse=True
    )

    return sorted_chunks


def _embed_and_hybrid_search(
    query_request: ChunkIndexRequest,
    document_index: DocumentIndex,
    db_session: Session | None = None,
    embedding_model: EmbeddingModel | None = None,
) -> list[InferenceChunk]:
    query_embedding = get_query_embedding(
        query_request.query,
        db_session=db_session,
        embedding_model=embedding_model,
    )

    hybrid_alpha = query_request.hybrid_alpha or HYBRID_ALPHA

    query_type = QueryType.KEYWORD if hybrid_alpha <= 0.2 else QueryType.SEMANTIC
    top_chunks = document_index.hybrid_retrieval(
        query=query_request.query,
        query_embedding=query_embedding,
        final_keywords=query_request.query_keywords,
        query_type=query_type,
        filters=query_request.filters,
        num_to_retrieve=query_request.limit or NUM_RETURNED_HITS,
    )

    return top_chunks


def _keyword_search(
    query_request: ChunkIndexRequest,
    document_index: DocumentIndex,
) -> list[InferenceChunk]:
    return document_index.keyword_retrieval(
        query=query_request.query,
        filters=query_request.filters,
        num_to_retrieve=query_request.limit or NUM_RETURNED_HITS,
    )


def _resolve_enrichment_contexts(
    prefetched: list[EnrichmentContext] | None,
    db_session: Session | None,
    user: User | None,
    source_filters: set[DocumentSource] | None,
) -> list[EnrichmentContext]:
    """Prefetched when the caller had a session, resolved here otherwise.

    With neither, the lane does not run. The default lane still withholds
    the source, so nothing leaks; the user simply sees no Zoom-style
    results.
    """
    if prefetched is not None:
        return prefetched
    if db_session is None:
        return []
    return get_enrichment_contexts(
        db_session=db_session,
        user=user,
        source_types=sorted(source_filters, key=lambda s: s.value)
        if source_filters
        else None,
    )


def _retrieve(
    query_request: ChunkIndexRequest,
    document_index: DocumentIndex,
    db_session: Session | None,
    embedding_model: EmbeddingModel | None,
) -> list[InferenceChunk]:
    """One index query. Keyword-only when the caller asked for keyword-only,
    which skips computing an embedding nothing would read."""
    if query_request.hybrid_alpha == 0.0:
        return _keyword_search(query_request, document_index)
    return _embed_and_hybrid_search(
        query_request, document_index, db_session, embedding_model
    )


def _search_withheld_source(
    context: EnrichmentContext,
    query_request: ChunkIndexRequest,
    document_index: DocumentIndex,
    db_session: Session | None,
    embedding_model: EmbeddingModel | None,
) -> list[InferenceChunk]:
    """One withheld source's own lane: search it, then clear it.

    The user's access filters are kept as they are. The provider decides on
    top of them, never instead of them.
    """
    scoped = query_request.model_copy(
        update={
            "filters": query_request.filters.model_copy(
                update={
                    "source_type": [context.source],
                    "excluded_source_type": None,
                }
            )
        }
    )
    chunks = _retrieve(scoped, document_index, db_session, embedding_model)
    return context.allowed(chunks)


def search_chunks(
    query_request: ChunkIndexRequest,
    user_id: UUID | None,
    document_index: DocumentIndex,
    db_session: Session | None = None,
    embedding_model: EmbeddingModel | None = None,
    prefetched_federated_retrieval_infos: list[FederatedRetrievalInfo] | None = None,
    user: User | None = None,
    prefetched_enrichment_contexts: list[EnrichmentContext] | None = None,
) -> list[InferenceChunk]:
    source_filters = (
        set(query_request.filters.source_type)
        if query_request.filters.source_type
        else None
    )

    # Read from the registry, never from the contexts below: a withheld
    # source must stay out of the default lane even when its own lane
    # cannot run.
    load_event_sources()
    withheld = enrichment_source_types()
    if withheld:
        query_request = query_request.model_copy(
            update={
                "filters": query_request.filters.model_copy(
                    update={"excluded_source_type": withheld}
                )
            }
        )

    enrichment_contexts = _resolve_enrichment_contexts(
        prefetched_enrichment_contexts,
        db_session=db_session,
        user=user,
        source_filters=source_filters,
    )

    # Federated retrieval — use pre-fetched if available, otherwise query DB
    if prefetched_federated_retrieval_infos is not None:
        federated_retrieval_infos = prefetched_federated_retrieval_infos
    else:
        if db_session is None:
            raise ValueError(
                "Either db_session or prefetched_federated_retrieval_infos must be provided"
            )
        federated_retrieval_infos = get_federated_retrieval_functions(
            db_session=db_session,
            user_id=user_id,
            source_types=list(source_filters) if source_filters else None,
            document_set_names=query_request.filters.document_set,
        )

    federated_sources = {
        federated_retrieval_info.source.to_non_federated_source()
        for federated_retrieval_info in federated_retrieval_infos
    }
    run_queries: list[tuple[Callable, tuple]] = [
        (federated_retrieval_info.retrieval_function, (query_request,))
        for federated_retrieval_info in federated_retrieval_infos
    ]
    run_queries.extend(
        (
            _search_withheld_source,
            (context, query_request, document_index, db_session, embedding_model),
        )
        for context in enrichment_contexts
    )

    # Don't run normal hybrid search if there are no indexed sources to
    # search over
    normal_search_enabled = (source_filters is None) or (
        len(set(source_filters) - federated_sources - set(withheld)) > 0
    )

    if normal_search_enabled:
        run_queries.append(
            (
                _retrieve,
                (query_request, document_index, db_session, embedding_model),
            )
        )

    parallel_search_results = run_functions_tuples_in_parallel(run_queries)
    top_chunks = combine_retrieval_results(parallel_search_results)

    if not top_chunks:
        logger.debug(
            "Search returned no results for query: %s with filters: %s.",
            query_request.query,
            query_request.filters,
        )

    return top_chunks


# TODO: This is unused code.
def inference_sections_from_ids(
    doc_identifiers: list[tuple[str, int]],
    document_index: DocumentIndex,
) -> list[InferenceSection]:
    # Currently only fetches whole docs
    doc_ids_set = {doc_id for doc_id, _ in doc_identifiers}

    chunk_requests: list[DocumentSectionRequest] = [
        DocumentSectionRequest(document_id=doc_id) for doc_id in doc_ids_set
    ]

    # No need for ACL here because the doc ids were validated beforehand
    filters = IndexFilters(access_control_list=None)

    retrieved_chunks = document_index.id_based_retrieval(
        chunk_requests=chunk_requests,
        filters=filters,
    )

    if not retrieved_chunks:
        return []

    # Group chunks by document ID
    chunks_by_doc_id: dict[str, list[InferenceChunk]] = {}
    for chunk in retrieved_chunks:
        chunks_by_doc_id.setdefault(chunk.document_id, []).append(chunk)

    inference_sections = [
        section
        for chunks in chunks_by_doc_id.values()
        if chunks
        and (
            section := inference_section_from_chunks(
                # The scores will always be 0 because the fetching by id gives back
                # no search scores. This is not needed though if the user is explicitly
                # selecting a document.
                center_chunk=chunks[0],
                chunks=chunks,
            )
        )
    ]

    return inference_sections
