from collections.abc import Callable
from collections.abc import Generator
from typing import cast

import numpy

from danswer.configs.model_configs import CROSS_ENCODER_RANGE_MAX
from danswer.configs.model_configs import CROSS_ENCODER_RANGE_MIN
from danswer.document_index.document_index_utils import (
    translate_boost_count_to_multiplier,
)
from danswer.search.models import ChunkMetric
from danswer.search.models import InferenceChunk
from danswer.search.models import MAX_METRICS_CONTENT
from danswer.search.models import RerankMetricsContainer
from danswer.search.models import SearchQuery
from danswer.search.models import SearchType
from danswer.search.search_nlp_models import CrossEncoderEnsembleModel
from danswer.secondary_llm_flows.chunk_usefulness import llm_batch_eval_chunks
from danswer.utils.logger import setup_logger
from danswer.utils.threadpool_concurrency import FunctionCall
from danswer.utils.threadpool_concurrency import run_functions_in_parallel
from danswer.utils.timing import log_function_time


logger = setup_logger()


def _log_top_chunk_links(search_flow: str, chunks: list[InferenceChunk]) -> None:
    top_links = [
        c.source_links[0] if c.source_links is not None else "No Link" for c in chunks
    ]
    logger.info(f"Top links from {search_flow} search: {', '.join(top_links)}")


def should_rerank(query: SearchQuery) -> bool:
    # Don't re-rank for keyword search
    return query.search_type != SearchType.KEYWORD and not query.skip_rerank


def should_apply_llm_based_relevance_filter(query: SearchQuery) -> bool:
    return not query.skip_llm_chunk_filter


@log_function_time(print_only=True)
def semantic_reranking(
    query: str,
    chunks: list[InferenceChunk],
    model_min: int = CROSS_ENCODER_RANGE_MIN,
    model_max: int = CROSS_ENCODER_RANGE_MAX,
    rerank_metrics_callback: Callable[[RerankMetricsContainer], None] | None = None,
) -> tuple[list[InferenceChunk], list[int]]:
    """Reranks chunks based on cross-encoder models. Additionally provides the original indices
    of the chunks in their new sorted order.

    Note: this updates the chunks in place, it updates the chunk scores which came from retrieval
    """
    cross_encoders = CrossEncoderEnsembleModel()
    passages = [chunk.content for chunk in chunks]
    sim_scores_floats = cross_encoders.predict(query=query, passages=passages)

    sim_scores = [numpy.array(scores) for scores in sim_scores_floats]

    raw_sim_scores = cast(numpy.ndarray, sum(sim_scores) / len(sim_scores))

    cross_models_min = numpy.min(sim_scores)

    shifted_sim_scores = sum(
        [enc_n_scores - cross_models_min for enc_n_scores in sim_scores]
    ) / len(sim_scores)

    boosts = [translate_boost_count_to_multiplier(chunk.boost) for chunk in chunks]
    recency_multiplier = [chunk.recency_bias for chunk in chunks]
    boosted_sim_scores = shifted_sim_scores * boosts * recency_multiplier
    normalized_b_s_scores = (boosted_sim_scores + cross_models_min - model_min) / (
        model_max - model_min
    )
    orig_indices = [i for i in range(len(normalized_b_s_scores))]
    scored_results = list(
        zip(normalized_b_s_scores, raw_sim_scores, chunks, orig_indices)
    )
    scored_results.sort(key=lambda x: x[0], reverse=True)
    ranked_sim_scores, ranked_raw_scores, ranked_chunks, ranked_indices = zip(
        *scored_results
    )

    logger.debug(
        f"Reranked (Boosted + Time Weighted) similarity scores: {ranked_sim_scores}"
    )

    # Assign new chunk scores based on reranking
    for ind, chunk in enumerate(ranked_chunks):
        chunk.score = ranked_sim_scores[ind]

    if rerank_metrics_callback is not None:
        chunk_metrics = [
            ChunkMetric(
                document_id=chunk.document_id,
                chunk_content_start=chunk.content[:MAX_METRICS_CONTENT],
                first_link=chunk.source_links[0] if chunk.source_links else None,
                score=chunk.score if chunk.score is not None else 0,
            )
            for chunk in ranked_chunks
        ]

        rerank_metrics_callback(
            RerankMetricsContainer(
                metrics=chunk_metrics, raw_similarity_scores=ranked_raw_scores  # type: ignore
            )
        )

    return list(ranked_chunks), list(ranked_indices)


def rerank_chunks(
    query: SearchQuery,
    chunks_to_rerank: list[InferenceChunk],
    rerank_metrics_callback: Callable[[RerankMetricsContainer], None] | None = None,
) -> list[InferenceChunk]:
    ranked_chunks, _ = semantic_reranking(
        query=query.query,
        chunks=chunks_to_rerank[: query.num_rerank],
        rerank_metrics_callback=rerank_metrics_callback,
    )
    lower_chunks = chunks_to_rerank[query.num_rerank :]
    # Scores from rerank cannot be meaningfully combined with scores without rerank
    for lower_chunk in lower_chunks:
        lower_chunk.score = None
    ranked_chunks.extend(lower_chunks)
    return ranked_chunks


@log_function_time(print_only=True)
def filter_chunks(
    query: SearchQuery,
    chunks_to_filter: list[InferenceChunk],
) -> list[str]:
    """Filters chunks based on whether the LLM thought they were relevant to the query.

    Returns a list of the unique chunk IDs that were marked as relevant"""
    chunks_to_filter = chunks_to_filter[: query.max_llm_filter_chunks]
    llm_chunk_selection = llm_batch_eval_chunks(
        query=query.query,
        chunk_contents=[chunk.content for chunk in chunks_to_filter],
    )
    return [
        chunk.unique_id
        for ind, chunk in enumerate(chunks_to_filter)
        if llm_chunk_selection[ind]
    ]


def search_postprocessing(
    search_query: SearchQuery,
    retrieved_chunks: list[InferenceChunk],
    rerank_metrics_callback: Callable[[RerankMetricsContainer], None] | None = None,
) -> Generator[list[InferenceChunk] | list[str], None, None]:
    post_processing_tasks: list[FunctionCall] = []

    rerank_task_id = None
    chunks_yielded = False
    if should_rerank(search_query):
        post_processing_tasks.append(
            FunctionCall(
                rerank_chunks,
                (
                    search_query,
                    retrieved_chunks,
                    rerank_metrics_callback,
                ),
            )
        )
        rerank_task_id = post_processing_tasks[-1].result_id
    else:
        final_chunks = retrieved_chunks
        # NOTE: if we don't rerank, we can return the chunks immediately
        # since we know this is the final order
        _log_top_chunk_links(search_query.search_type.value, final_chunks)
        yield final_chunks
        chunks_yielded = True

    llm_filter_task_id = None
    if should_apply_llm_based_relevance_filter(search_query):
        post_processing_tasks.append(
            FunctionCall(
                filter_chunks,
                (search_query, retrieved_chunks[: search_query.max_llm_filter_chunks]),
            )
        )
        llm_filter_task_id = post_processing_tasks[-1].result_id

    post_processing_results = (
        run_functions_in_parallel(post_processing_tasks)
        if post_processing_tasks
        else {}
    )
    reranked_chunks = cast(
        list[InferenceChunk] | None,
        post_processing_results.get(str(rerank_task_id)) if rerank_task_id else None,
    )
    if reranked_chunks:
        if chunks_yielded:
            logger.error(
                "Trying to yield re-ranked chunks, but chunks were already yielded. This should never happen."
            )
        else:
            _log_top_chunk_links(search_query.search_type.value, reranked_chunks)
            yield reranked_chunks

    llm_chunk_selection = cast(
        list[str] | None,
        post_processing_results.get(str(llm_filter_task_id))
        if llm_filter_task_id
        else None,
    )
    if llm_chunk_selection is not None:
        yield [
            chunk.unique_id
            for chunk in reranked_chunks or retrieved_chunks
            if chunk.unique_id in llm_chunk_selection
        ]
    else:
        yield cast(list[str], [])
