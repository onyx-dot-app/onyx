import string
from collections.abc import Callable

import nltk  # type:ignore
from nltk.corpus import stopwords  # type:ignore
from nltk.stem import WordNetLemmatizer  # type:ignore
from nltk.tokenize import word_tokenize  # type:ignore
from sqlalchemy.orm import Session

from danswer.db.embedding_model import get_current_db_embedding_model
from danswer.document_index.interfaces import DocumentIndex
from danswer.document_index.interfaces import VespaChunkRequest
from danswer.document_index.vespa.shared_utils.utils import (
    replace_invalid_doc_id_characters,
)
from danswer.natural_language_processing.search_nlp_models import EmbeddingModel
from danswer.search.models import ChunkMetric
from danswer.search.models import IndexFilters
from danswer.search.models import InferenceChunk
from danswer.search.models import InferenceChunkUncleaned
from danswer.search.models import InferenceSection
from danswer.search.models import MAX_METRICS_CONTENT
from danswer.search.models import RetrievalMetricsContainer
from danswer.search.models import SearchQuery
from danswer.search.postprocessing.postprocessing import cleanup_chunks
from danswer.search.search_settings import get_multilingual_expansion
from danswer.search.utils import inference_section_from_chunks
from danswer.secondary_llm_flows.query_expansion import multilingual_query_expansion
from danswer.utils.logger import setup_logger
from danswer.utils.threadpool_concurrency import run_functions_tuples_in_parallel
from danswer.utils.timing import log_function_time
from shared_configs.configs import MODEL_SERVER_HOST
from shared_configs.configs import MODEL_SERVER_PORT
from shared_configs.enums import EmbedTextType


logger = setup_logger()


def download_nltk_data() -> None:
    resources = {
        "stopwords": "corpora/stopwords",
        "wordnet": "corpora/wordnet",
        "punkt": "tokenizers/punkt",
    }

    for resource_name, resource_path in resources.items():
        try:
            nltk.data.find(resource_path)
            logger.info(f"{resource_name} is already downloaded.")
        except LookupError:
            try:
                logger.info(f"Downloading {resource_name}...")
                nltk.download(resource_name, quiet=True)
                logger.info(f"{resource_name} downloaded successfully.")
            except Exception as e:
                logger.error(f"Failed to download {resource_name}. Error: {e}")


def lemmatize_text(keywords: list[str]) -> list[str]:
    try:
        query = " ".join(keywords)
        lemmatizer = WordNetLemmatizer()
        word_tokens = word_tokenize(query)
        lemmatized_words = [lemmatizer.lemmatize(word) for word in word_tokens]
        combined_keywords = list(set(keywords + lemmatized_words))
        return combined_keywords
    except Exception:
        return keywords


def remove_stop_words_and_punctuation(keywords: list[str]) -> list[str]:
    try:
        # Re-tokenize using the NLTK tokenizer for better matching
        query = " ".join(keywords)
        stop_words = set(stopwords.words("english"))
        word_tokens = word_tokenize(query)
        text_trimmed = [
            word
            for word in word_tokens
            if (word.casefold() not in stop_words and word not in string.punctuation)
        ]
        return text_trimmed or word_tokens
    except Exception:
        return keywords


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


@log_function_time(print_only=True)
def doc_index_retrieval(
    query: SearchQuery,
    document_index: DocumentIndex,
    db_session: Session,
) -> list[InferenceChunk]:
    """
    This function performs the search to retrieve the chunks,
    extracts chunks from the large chunks, persists the scores
    from the large chunks to the referenced chunks,
    dedupes the chunks, and cleans the chunks.
    """
    db_embedding_model = get_current_db_embedding_model(db_session)

    model = EmbeddingModel(
        model_name=db_embedding_model.model_name,
        query_prefix=db_embedding_model.query_prefix,
        passage_prefix=db_embedding_model.passage_prefix,
        normalize=db_embedding_model.normalize,
        api_key=db_embedding_model.api_key,
        provider_type=db_embedding_model.provider_type,
        # The below are globally set, this flow always uses the indexing one
        server_host=MODEL_SERVER_HOST,
        server_port=MODEL_SERVER_PORT,
    )

    query_embedding = model.encode([query.query], text_type=EmbedTextType.QUERY)[0]

    top_chunks = document_index.hybrid_retrieval(
        query=query.query,
        query_embedding=query_embedding,
        final_keywords=query.processed_keywords,
        filters=query.filters,
        hybrid_alpha=query.hybrid_alpha,
        time_decay_multiplier=query.recency_bias_multiplier,
        num_to_retrieve=query.num_hits,
        offset=query.offset,
    )

    retrieval_requests: list[VespaChunkRequest] = []
    normal_chunks: list[InferenceChunkUncleaned] = []
    referenced_chunk_scores: dict[tuple[str, int], float] = {}
    for chunk in top_chunks:
        if chunk.large_chunk_reference_ids:
            retrieval_requests.append(
                VespaChunkRequest(
                    document_id=replace_invalid_doc_id_characters(chunk.document_id),
                    min_chunk_ind=chunk.large_chunk_reference_ids[0],
                    max_chunk_ind=chunk.large_chunk_reference_ids[-1],
                )
            )
            # for each referenced chunk, persist the
            # highest score to the referenced chunk
            for chunk_id in chunk.large_chunk_reference_ids:
                key = (chunk.document_id, chunk_id)
                referenced_chunk_scores[key] = max(
                    referenced_chunk_scores.get(key, 0), chunk.score or 0
                )
        else:
            normal_chunks.append(chunk)

    # If there are no large chunks, just return the normal chunks
    if not retrieval_requests:
        return cleanup_chunks(normal_chunks)

    # Retrieve and return the referenced normal chunks from the large chunks
    retrieved_inference_chunks = document_index.id_based_retrieval(
        chunk_requests=retrieval_requests,
        filters=query.filters,
        batch_retrieval=True,
    )

    # Apply the scores from the large chunks to the chunks referenced
    # by each large chunk
    for chunk in retrieved_inference_chunks:
        if (chunk.document_id, chunk.chunk_id) in referenced_chunk_scores:
            chunk.score = referenced_chunk_scores[(chunk.document_id, chunk.chunk_id)]
            referenced_chunk_scores.pop((chunk.document_id, chunk.chunk_id))
        else:
            logger.error(
                f"Chunk {chunk.document_id} {chunk.chunk_id} not found in referenced chunk scores"
            )

    # Log any chunks that were not found in the retrieved chunks
    for reference in referenced_chunk_scores.keys():
        logger.error(f"Chunk {reference} not found in retrieved chunks")

    unique_chunks: dict[tuple[str, int], InferenceChunkUncleaned] = {
        (chunk.document_id, chunk.chunk_id): chunk for chunk in normal_chunks
    }

    # persist the highest score of each deduped chunk
    for chunk in retrieved_inference_chunks:
        key = (chunk.document_id, chunk.chunk_id)
        # For duplicates, keep the highest score
        if key not in unique_chunks or (chunk.score or 0) > (
            unique_chunks[key].score or 0
        ):
            unique_chunks[key] = chunk

    # Deduplicate the chunks
    deduped_chunks = list(unique_chunks.values())
    deduped_chunks.sort(key=lambda chunk: chunk.score or 0, reverse=True)
    return cleanup_chunks(deduped_chunks)


def _simplify_text(text: str) -> str:
    return "".join(
        char for char in text if char not in string.punctuation and not char.isspace()
    ).lower()


def retrieve_chunks(
    query: SearchQuery,
    document_index: DocumentIndex,
    db_session: Session,
    retrieval_metrics_callback: Callable[[RetrievalMetricsContainer], None]
    | None = None,
) -> list[InferenceChunk]:
    """Returns a list of the best chunks from an initial keyword/semantic/ hybrid search."""

    multilingual_expansion = get_multilingual_expansion()
    # Don't do query expansion on complex queries, rephrasings likely would not work well
    if not multilingual_expansion or "\n" in query.query or "\r" in query.query:
        top_chunks = doc_index_retrieval(
            query=query, document_index=document_index, db_session=db_session
        )
    else:
        simplified_queries = set()
        run_queries: list[tuple[Callable, tuple]] = []

        # Currently only uses query expansion on multilingual use cases
        query_rephrases = multilingual_query_expansion(
            query.query, multilingual_expansion
        )
        # Just to be extra sure, add the original query.
        query_rephrases.append(query.query)
        for rephrase in set(query_rephrases):
            # Sometimes the model rephrases the query in the same language with minor changes
            # Avoid doing an extra search with the minor changes as this biases the results
            simplified_rephrase = _simplify_text(rephrase)
            if simplified_rephrase in simplified_queries:
                continue
            simplified_queries.add(simplified_rephrase)

            q_copy = query.copy(update={"query": rephrase}, deep=True)
            run_queries.append(
                (
                    doc_index_retrieval,
                    (q_copy, document_index, db_session),
                )
            )
        parallel_search_results = run_functions_tuples_in_parallel(run_queries)
        top_chunks = combine_retrieval_results(parallel_search_results)

    if not top_chunks:
        logger.warning(
            f"Hybrid ({query.search_type.value.capitalize()}) search returned no results "
            f"with filters: {query.filters}"
        )
        return []

    if retrieval_metrics_callback is not None:
        chunk_metrics = [
            ChunkMetric(
                document_id=chunk.document_id,
                chunk_content_start=chunk.content[:MAX_METRICS_CONTENT],
                first_link=chunk.source_links[0] if chunk.source_links else None,
                score=chunk.score if chunk.score is not None else 0,
            )
            for chunk in top_chunks
        ]
        retrieval_metrics_callback(
            RetrievalMetricsContainer(
                search_type=query.search_type, metrics=chunk_metrics
            )
        )

    return top_chunks


def inference_sections_from_ids(
    doc_identifiers: list[tuple[str, int]],
    document_index: DocumentIndex,
) -> list[InferenceSection]:
    # Currently only fetches whole docs
    doc_ids_set = set(doc_id for doc_id, _ in doc_identifiers)

    chunk_requests: list[VespaChunkRequest] = [
        VespaChunkRequest(document_id=doc_id) for doc_id in doc_ids_set
    ]

    # No need for ACL here because the doc ids were validated beforehand
    filters = IndexFilters(access_control_list=None)

    retrieved_chunks = document_index.id_based_retrieval(
        chunk_requests=chunk_requests,
        filters=filters,
    )

    cleaned_chunks = cleanup_chunks(retrieved_chunks)
    if not cleaned_chunks:
        return []

    # Group chunks by document ID
    chunks_by_doc_id: dict[str, list[InferenceChunk]] = {}
    for chunk in cleaned_chunks:
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
