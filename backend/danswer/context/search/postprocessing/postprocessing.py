from collections.abc import Callable
from collections.abc import Iterator
from typing import cast

import numpy

from danswer.chat.models import SectionRelevancePiece
from danswer.configs.app_configs import BLURB_SIZE
from danswer.configs.constants import RETURN_SEPARATOR
from danswer.configs.model_configs import CROSS_ENCODER_RANGE_MAX
from danswer.configs.model_configs import CROSS_ENCODER_RANGE_MIN
from danswer.context.search.enums import LLMEvaluationType
from danswer.context.search.models import ChunkMetric
from danswer.context.search.models import InferenceChunk
from danswer.context.search.models import InferenceChunkUncleaned
from danswer.context.search.models import InferenceSection
from danswer.context.search.models import MAX_METRICS_CONTENT
from danswer.context.search.models import RerankMetricsContainer
from danswer.context.search.models import SearchQuery
from danswer.document_index.document_index_utils import (
    translate_boost_count_to_multiplier,
)
from danswer.llm.interfaces import LLM
from danswer.natural_language_processing.search_nlp_models import RerankingModel
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
    logger.debug(f"Top links from {search_flow} search: {', '.join(top_links)}")


def cleanup_chunks(chunks: list[InferenceChunkUncleaned]) -> list[InferenceChunk]:
    def _remove_title(chunk: InferenceChunkUncleaned) -> str:
        if not chunk.title or not chunk.content:
            return chunk.content

        if chunk.content.startswith(chunk.title):
            return chunk.content[len(chunk.title) :].lstrip()

        # BLURB SIZE is by token instead of char but each token is at least 1 char
        # If this prefix matches the content, it's assumed the title was prepended
        if chunk.content.startswith(chunk.title[:BLURB_SIZE]):
            return (
                chunk.content.split(RETURN_SEPARATOR, 1)[-1]
                if RETURN_SEPARATOR in chunk.content
                else chunk.content
            )

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
    query: SearchQuery,
    chunks: list[InferenceChunk],
    model_min: int = CROSS_ENCODER_RANGE_MIN,
    model_max: int = CROSS_ENCODER_RANGE_MAX,
    rerank_metrics_callback: Callable[[RerankMetricsContainer], None] | None = None,
) -> tuple[list[InferenceChunk], list[int]]:
    """Reranks chunks based on cross-encoder models. Additionally provides the original indices
    of the chunks in their new sorted order.

    Note: this updates the chunks in place, it updates the chunk scores which came from retrieval
    """
    rerank_settings = query.rerank_settings

    if not rerank_settings or not rerank_settings.rerank_model_name:
        # Should never reach this part of the flow without reranking settings
        raise RuntimeError("Reranking flow should not be running")

    chunks_to_rerank = chunks[: rerank_settings.num_rerank]

    cross_encoder = RerankingModel(
        model_name=rerank_settings.rerank_model_name,
        provider_type=rerank_settings.rerank_provider_type,
        api_key=rerank_settings.rerank_api_key,
        api_url=rerank_settings.rerank_api_url,
    )

    passages = [
        f"{chunk.semantic_identifier or chunk.title or ''}\n{chunk.content}"
        for chunk in chunks_to_rerank
    ]
    sim_scores_floats = cross_encoder.predict(query=query.query, passages=passages)

    # Old logic to handle multiple cross-encoders preserved but not used
    sim_scores = [numpy.array(sim_scores_floats)]

    raw_sim_scores = cast(numpy.ndarray, sum(sim_scores) / len(sim_scores))

    cross_models_min = numpy.min(sim_scores)

    shifted_sim_scores = sum(
        [enc_n_scores - cross_models_min for enc_n_scores in sim_scores]
    ) / len(sim_scores)

    boosts = [
        translate_boost_count_to_multiplier(chunk.boost) for chunk in chunks_to_rerank
    ]
    recency_multiplier = [chunk.recency_bias for chunk in chunks_to_rerank]
    boosted_sim_scores = shifted_sim_scores * boosts * recency_multiplier
    normalized_b_s_scores = (boosted_sim_scores + cross_models_min - model_min) / (
        model_max - model_min
    )
    orig_indices = [i for i in range(len(normalized_b_s_scores))]
    scored_results = list(
        zip(normalized_b_s_scores, raw_sim_scores, chunks_to_rerank, orig_indices)
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

    if not query.rerank_settings:
        # Should never reach this part of the flow without reranking settings
        raise RuntimeError("Reranking settings not found")

    ranked_chunks, _ = semantic_reranking(
        query=query,
        chunks=chunks_to_rerank,
        rerank_metrics_callback=rerank_metrics_callback,
    )
    lower_chunks = chunks_to_rerank[query.rerank_settings.num_rerank :]

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
    metadata_list = [section.center_chunk.metadata for section in sections_to_filter]
    titles = [
        section.center_chunk.semantic_identifier for section in sections_to_filter
    ]

    llm_chunk_selection = llm_batch_eval_sections(
        query=query.query,
        section_contents=contents,
        llm=llm,
        titles=titles,
        metadata_list=metadata_list,
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
) -> Iterator[list[InferenceSection] | list[SectionRelevancePiece]]:
    post_processing_tasks: list[FunctionCall] = []

    if not retrieved_sections:
        # Avoids trying to rerank an empty list which throws an error
        yield cast(list[InferenceSection], [])
        yield cast(list[SectionRelevancePiece], [])
        return

    rerank_task_id = None
    sections_yielded = False
    if (
        search_query.rerank_settings
        and search_query.rerank_settings.rerank_model_name
        and search_query.rerank_settings.num_rerank > 0
    ):
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
    if search_query.evaluation_type in [
        LLMEvaluationType.BASIC,
        LLMEvaluationType.UNSPECIFIED,
    ]:
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
        SectionRelevancePiece(
            document_id=section.center_chunk.document_id,
            chunk_id=section.center_chunk.chunk_id,
            relevant=section.center_chunk.unique_id in llm_selected_section_ids,
            content="",
        )
        for section in (reranked_sections or retrieved_sections)
    ]
