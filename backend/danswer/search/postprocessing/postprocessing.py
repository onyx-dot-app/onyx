from collections.abc import Callable
from collections.abc import Iterator
from typing import cast

import numpy

from danswer.configs.constants import MAX_CHUNK_TITLE_LEN
from danswer.configs.constants import RETURN_SEPARATOR
from danswer.configs.model_configs import CROSS_ENCODER_RANGE_MAX
from danswer.configs.model_configs import CROSS_ENCODER_RANGE_MIN
from danswer.document_index.document_index_utils import (
    translate_boost_count_to_multiplier,
)
from danswer.llm.interfaces import LLM
from danswer.natural_language_processing.search_nlp_models import (
    CrossEncoderEnsembleModel,
)
from danswer.search.models import ChunkMetric
from danswer.search.models import InferenceChunk
from danswer.search.models import InferenceChunkUncleaned
from danswer.search.models import InferenceSection
from danswer.search.models import MAX_METRICS_CONTENT
from danswer.search.models import RerankMetricsContainer
from danswer.search.models import SearchQuery
from danswer.search.models import SearchType
from danswer.secondary_llm_flows.chunk_usefulness import llm_batch_eval_sections
from danswer.utils.logger import setup_logger
from danswer.utils.threadpool_concurrency import FunctionCall
from danswer.utils.threadpool_concurrency import run_functions_in_parallel
from danswer.utils.timing import log_function_time


logger = setup_logger()


def _log_top_section_links(search_flow: str, sections: list[InferenceSection]) -> None:
    top_links = [
        section.center_chunk.source_links[0]
        if section.center_chunk.source_links is not None
        else "No Link"
        for section in sections
    ]
    logger.info(f"Top links from {search_flow} search: {', '.join(top_links)}")


def should_rerank(query: SearchQuery) -> bool:
    # Don't re-rank for keyword search
    return query.search_type != SearchType.KEYWORD and not query.skip_rerank


def should_apply_llm_based_relevance_filter(query: SearchQuery) -> bool:
    return not query.skip_llm_chunk_filter


def cleanup_chunks(chunks: list[InferenceChunkUncleaned]) -> list[InferenceChunk]:
    def _remove_title(chunk: InferenceChunkUncleaned) -> str:
        if not chunk.title or not chunk.content:
            return chunk.content

        if chunk.content.startswith(chunk.title):
            return chunk.content[len(chunk.title) :].lstrip()

        if chunk.content.startswith(chunk.title[:MAX_CHUNK_TITLE_LEN]):
            return chunk.content[MAX_CHUNK_TITLE_LEN:].lstrip()

        return chunk.content

    def _remove_metadata_suffix(chunk: InferenceChunkUncleaned) -> str:
        if not chunk.metadata_suffix:
            return chunk.content
        return chunk.content.removesuffix(chunk.metadata_suffix).rstrip(
            RETURN_SEPARATOR
        )

    for chunk in chunks:
        chunk.content = _remove_title(chunk)
        chunk.content = _remove_metadata_suffix(chunk)

    return [chunk.to_inference_chunk() for chunk in chunks]


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


def rerank_sections(
    query: SearchQuery,
    sections_to_rerank: list[InferenceSection],
    rerank_metrics_callback: Callable[[RerankMetricsContainer], None] | None = None,
) -> list[InferenceSection]:
    """Chunks are reranked rather than the containing sections, this is because of speed
    implications, if reranking models have lower latency for long inputs in the future
    we may rerank on the combined context of the section instead

    Making the assumption here that often times we want larger Sections to provide context
    for the LLM to determine if a section is useful but for reranking, we don't need to be
    as stringent. If the Section is relevant, we assume that the chunk rerank score will
    also be high.
    """
    chunks_to_rerank = [section.center_chunk for section in sections_to_rerank]

    ranked_chunks, _ = semantic_reranking(
        query=query.query,
        chunks=chunks_to_rerank[: query.num_rerank],
        rerank_metrics_callback=rerank_metrics_callback,
    )
    lower_chunks = chunks_to_rerank[query.num_rerank :]

    # Scores from rerank cannot be meaningfully combined with scores without rerank
    # However the ordering is still important
    for lower_chunk in lower_chunks:
        lower_chunk.score = None
    ranked_chunks.extend(lower_chunks)

    chunk_id_to_section = {
        section.center_chunk.unique_id: section for section in sections_to_rerank
    }
    ordered_sections = [chunk_id_to_section[chunk.unique_id] for chunk in ranked_chunks]
    return ordered_sections


@log_function_time(print_only=True)
def filter_sections(
    query: SearchQuery,
    sections_to_filter: list[InferenceSection],
    llm: LLM,
    # For cost saving, we may turn this on
    use_chunk: bool = False,
) -> list[InferenceSection]:
    """Filters sections based on whether the LLM thought they were relevant to the query.
    This applies on the section which has more context than the chunk. Hopefully this yields more accurate LLM evaluations.

    Returns a list of the unique chunk IDs that were marked as relevant
    """
    sections_to_filter = sections_to_filter[: query.max_llm_filter_sections]

    contents = [
        section.center_chunk.content if use_chunk else section.combined_content
        for section in sections_to_filter
    ]

    llm_chunk_selection = llm_batch_eval_sections(
        query=query.query,
        section_contents=contents,
        llm=llm,
    )

    return [
        section
        for ind, section in enumerate(sections_to_filter)
        if llm_chunk_selection[ind]
    ]


def search_postprocessing(
    search_query: SearchQuery,
    retrieved_sections: list[InferenceSection],
    llm: LLM,
    rerank_metrics_callback: Callable[[RerankMetricsContainer], None] | None = None,
) -> Iterator[list[InferenceSection] | list[int]]:
    post_processing_tasks: list[FunctionCall] = []

    rerank_task_id = None
    sections_yielded = False
    if should_rerank(search_query):
        post_processing_tasks.append(
            FunctionCall(
                rerank_sections,
                (
                    search_query,
                    retrieved_sections,
                    rerank_metrics_callback,
                ),
            )
        )
        rerank_task_id = post_processing_tasks[-1].result_id
    else:
        # NOTE: if we don't rerank, we can return the chunks immediately
        # since we know this is the final order.
        # This way the user experience isn't delayed by the LLM step
        _log_top_section_links(search_query.search_type.value, retrieved_sections)
        yield retrieved_sections
        sections_yielded = True

    llm_filter_task_id = None
    if should_apply_llm_based_relevance_filter(search_query):
        post_processing_tasks.append(
            FunctionCall(
                filter_sections,
                (
                    search_query,
                    retrieved_sections[: search_query.max_llm_filter_sections],
                    llm,
                ),
            )
        )
        llm_filter_task_id = post_processing_tasks[-1].result_id

    post_processing_results = (
        run_functions_in_parallel(post_processing_tasks)
        if post_processing_tasks
        else {}
    )
    reranked_sections = cast(
        list[InferenceSection] | None,
        post_processing_results.get(str(rerank_task_id)) if rerank_task_id else None,
    )
    if reranked_sections:
        if sections_yielded:
            logger.error(
                "Trying to yield re-ranked sections, but sections were already yielded. This should never happen."
            )
        else:
            _log_top_section_links(search_query.search_type.value, reranked_sections)
            yield reranked_sections

    llm_selected_section_ids = (
        [
            section.center_chunk.unique_id
            for section in post_processing_results.get(str(llm_filter_task_id), [])
        ]
        if llm_filter_task_id
        else []
    )

    yield [
        index
        for index, section in enumerate(reranked_sections or retrieved_sections)
        if section.center_chunk.unique_id in llm_selected_section_ids
    ]
