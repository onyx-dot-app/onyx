import numpy as np

from onyx.agents.agent_search.shared_graph_utils.models import AnswerGenerationDocuments
from onyx.agents.agent_search.shared_graph_utils.models import RetrievalFitScoreMetrics
from onyx.agents.agent_search.shared_graph_utils.models import RetrievalFitStats
from onyx.agents.agent_search.shared_graph_utils.operators import (
    dedup_inference_section_list,
)
from onyx.chat.models import SectionRelevancePiece
from onyx.context.search.models import InferenceSection
from onyx.utils.logger import setup_logger

logger = setup_logger()


def unique_chunk_id(doc: InferenceSection) -> str:
    return f"{doc.center_chunk.document_id}_{doc.center_chunk.chunk_id}"


def calculate_rank_shift(list1: list, list2: list, top_n: int = 20) -> float:
    shift = 0
    for rank_first, doc_id in enumerate(list1[:top_n], 1):
        try:
            rank_second = list2.index(doc_id) + 1
        except ValueError:
            rank_second = len(list2)  # Document not found in second list

        shift += np.abs(rank_first - rank_second) / np.log(1 + rank_first * rank_second)

    return shift / top_n


def get_fit_scores(
    pre_reranked_results: list[InferenceSection],
    post_reranked_results: list[InferenceSection] | list[SectionRelevancePiece],
) -> RetrievalFitStats | None:
    """
    Calculate retrieval metrics for search purposes
    """

    if len(pre_reranked_results) == 0 or len(post_reranked_results) == 0:
        return None

    ranked_sections = {
        "initial": pre_reranked_results,
        "reranked": post_reranked_results,
    }

    fit_eval: RetrievalFitStats = RetrievalFitStats(
        fit_score_lift=0,
        rerank_effect=0,
        fit_scores={
            "initial": RetrievalFitScoreMetrics(scores={}, chunk_ids=[]),
            "reranked": RetrievalFitScoreMetrics(scores={}, chunk_ids=[]),
        },
    )

    for rank_type, docs in ranked_sections.items():
        logger.debug(f"rank_type: {rank_type}")

        for i in [1, 5, 10]:
            fit_eval.fit_scores[rank_type].scores[str(i)] = (
                sum(
                    [
                        float(doc.center_chunk.score)
                        for doc in docs[:i]
                        if isinstance(doc, InferenceSection)
                        and doc.center_chunk.score is not None
                    ]
                )
                / i
            )

        fit_eval.fit_scores[rank_type].scores["fit_score"] = (
            1
            / 3
            * (
                fit_eval.fit_scores[rank_type].scores["1"]
                + fit_eval.fit_scores[rank_type].scores["5"]
                + fit_eval.fit_scores[rank_type].scores["10"]
            )
        )

        fit_eval.fit_scores[rank_type].scores["fit_score"] = fit_eval.fit_scores[
            rank_type
        ].scores["1"]

        fit_eval.fit_scores[rank_type].chunk_ids = [
            unique_chunk_id(doc) for doc in docs if isinstance(doc, InferenceSection)
        ]

    fit_eval.fit_score_lift = (
        fit_eval.fit_scores["reranked"].scores["fit_score"]
        / fit_eval.fit_scores["initial"].scores["fit_score"]
    )

    fit_eval.rerank_effect = calculate_rank_shift(
        fit_eval.fit_scores["initial"].chunk_ids,
        fit_eval.fit_scores["reranked"].chunk_ids,
    )

    return fit_eval


def get_answer_generation_documents(
    relevant_docs: list[InferenceSection],
    context_documents: list[InferenceSection],
    original_question_docs: list[InferenceSection],
    max_docs: int,
) -> AnswerGenerationDocuments:
    """
    Create a deduplicated list of documents to stream, prioritizing relevant docs.

    Args:
        relevant_docs: Primary documents to include
        context_documents: Additional context documents to append
        original_question_docs: Original question documents to append
        max_docs: Maximum number of documents to return

    Returns:
        List of deduplicated documents, limited to max_docs
    """
    # get relevant_doc ids
    relevant_doc_ids = [doc.center_chunk.document_id for doc in relevant_docs]

    # Start with relevant docs or fallback to original question docs
    streaming_documents = relevant_docs.copy()

    # Use a set for O(1) lookups of document IDs
    seen_doc_ids = {doc.center_chunk.document_id for doc in streaming_documents}

    # Combine additional documents to check in one iteration
    additional_docs = context_documents + original_question_docs
    for doc_idx, doc in enumerate(additional_docs):
        doc_id = doc.center_chunk.document_id
        if doc_id not in seen_doc_ids:
            streaming_documents.append(doc)
            seen_doc_ids.add(doc_id)

    streaming_documents = dedup_inference_section_list(streaming_documents)

    relevant_streaming_docs = [
        doc
        for doc in streaming_documents
        if doc.center_chunk.document_id in relevant_doc_ids
    ]
    relevant_streaming_docs = dedup_sort_inference_section_list(relevant_streaming_docs)

    additional_streaming_docs = [
        doc
        for doc in streaming_documents
        if doc.center_chunk.document_id not in relevant_doc_ids
    ]
    additional_streaming_docs = dedup_sort_inference_section_list(
        additional_streaming_docs
    )

    for doc in additional_streaming_docs:
        if doc.center_chunk.score:
            doc.center_chunk.score += -2.0
        else:
            doc.center_chunk.score = -2.0

    sorted_streaming_documents = relevant_streaming_docs + additional_streaming_docs

    return AnswerGenerationDocuments(
        streaming_documents=sorted_streaming_documents[:max_docs],
        context_documents=relevant_streaming_docs[:max_docs],
    )


def dedup_sort_inference_section_list(
    sections: list[InferenceSection],
) -> list[InferenceSection]:
    """Deduplicates InferenceSections by document_id and sorts by score.

    Args:
        sections: List of InferenceSections to deduplicate and sort

    Returns:
        Deduplicated list of InferenceSections sorted by score in descending order
    """
    # dedupe/merge with existing framework
    sections = dedup_inference_section_list(sections)

    # Use dict to deduplicate by document_id, keeping highest scored version
    unique_sections: dict[str, InferenceSection] = {}
    for section in sections:
        doc_id = section.center_chunk.document_id
        if doc_id not in unique_sections:
            unique_sections[doc_id] = section
            continue

        # Keep version with higher score
        existing_score = unique_sections[doc_id].center_chunk.score or 0
        new_score = section.center_chunk.score or 0
        if new_score > existing_score:
            unique_sections[doc_id] = section

    # Sort by score in descending order, handling None scores
    sorted_sections = sorted(
        unique_sections.values(), key=lambda x: x.center_chunk.score or 0, reverse=True
    )

    return sorted_sections
