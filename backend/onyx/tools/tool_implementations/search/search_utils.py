from collections import defaultdict
from collections.abc import Callable
from typing import TypeVar

from onyx.chat.models import LlmDoc
from onyx.context.search.models import InferenceSection
from onyx.prompts.prompt_utils import clean_up_source


RRF_K_VALUE = 50

T = TypeVar("T")


def weighted_reciprocal_rank_fusion(
    ranked_results: list[list[T]],
    weights: list[float],
    id_extractor: Callable[[T], str],
    k: int = RRF_K_VALUE,
) -> list[T]:
    """
    Merge multiple ranked result lists using weighted Reciprocal Rank Fusion (RRF).

    RRF combines rankings from different sources by computing a score for each item
    based on its rank positions across all lists. The weighted version allows different
    importance to be assigned to different result sources.

    Formula: RRF_score(item) = sum over all rankers of: weight / (k + rank(item))

    Args:
        ranked_results: List of ranked result lists, where each inner list contains
                       items ranked from best to worst (index 0 is rank 1)
        weights: List of weights corresponding to each result list. Higher weights
                give more importance to that ranking source.
        id_extractor: Function to extract a unique identifier from each item.
                     Items with the same ID across different lists are treated as
                     the same item and their scores are accumulated.
        k: Constant to prevent overemphasis on top-ranked items (default: RRF_K_VALUE).
           Typical values are 50-60. Lower values give more weight to top results.

    Returns:
        List of items sorted by their weighted RRF score in descending order.
        Each unique item appears only once, even if it was in multiple input lists.

    Example:
        >>> results1 = [doc_a, doc_b, doc_c]  # Semantic search results
        >>> results2 = [doc_c, doc_a, doc_d]  # Keyword search results
        >>> weights = [1.2, 1.0]  # Semantic query weighted higher
        >>> merged = weighted_reciprocal_rank_fusion(
        ...     [results1, results2],
        ...     weights,
        ...     lambda doc: doc.document_id
        ... )
        # doc_a and doc_c will have higher scores (appeared in both lists)
    """
    if len(ranked_results) != len(weights):
        raise ValueError(
            f"Number of ranked results ({len(ranked_results)}) must match "
            f"number of weights ({len(weights)})"
        )

    # Track RRF scores for each unique item (identified by ID)
    rrf_scores: dict[str, float] = defaultdict(float)
    # Track the actual item object for each ID (use first occurrence)
    id_to_item: dict[str, T] = {}
    # Track which result list each item first appeared in (for tiebreaking)
    id_to_source_index: dict[str, int] = {}
    # Track the position within the source list (for tiebreaking)
    id_to_source_rank: dict[str, int] = {}

    # Compute weighted RRF scores
    for source_idx, (result_list, weight) in enumerate(zip(ranked_results, weights)):
        for rank, item in enumerate(result_list, start=1):
            item_id = id_extractor(item)

            # Add weighted RRF score: weight / (k + rank)
            rrf_scores[item_id] += weight / (k + rank)

            # Store the item object and source info (if not already stored)
            if item_id not in id_to_item:
                id_to_item[item_id] = item
                id_to_source_index[item_id] = source_idx
                id_to_source_rank[item_id] = rank

    # Sort items by:
    # 1. RRF score (descending - higher is better)
    # 2. Source index modulo (for round-robin across queries)
    # 3. Rank within source (ascending - lower rank is better)
    sorted_ids = sorted(
        rrf_scores.keys(),
        key=lambda id: (
            -rrf_scores[
                id
            ],  # Primary: higher RRF score first (negative for descending)
            id_to_source_rank[id],  # Secondary: lower rank within source first
            id_to_source_index[id],  # Tertiary: round-robin by cycling through sources
        ),
    )
    return [id_to_item[item_id] for item_id in sorted_ids]


def llm_doc_to_dict(llm_doc: LlmDoc, doc_num: int) -> dict:
    doc_dict = {
        "document_number": doc_num + 1,
        "title": llm_doc.semantic_identifier,
        "content": llm_doc.content,
        "source": clean_up_source(llm_doc.source_type),
        "metadata": llm_doc.metadata,
    }
    if llm_doc.updated_at:
        doc_dict["updated_at"] = llm_doc.updated_at.strftime("%B %d, %Y %H:%M")
    return doc_dict


def section_to_dict(section: InferenceSection, section_num: int) -> dict:
    doc_dict = {
        "document_number": section_num + 1,
        "title": section.center_chunk.semantic_identifier,
        "content": section.combined_content,
        "source": clean_up_source(section.center_chunk.source_type),
        "metadata": section.center_chunk.metadata,
    }
    if section.center_chunk.updated_at:
        doc_dict["updated_at"] = section.center_chunk.updated_at.strftime(
            "%B %d, %Y %H:%M"
        )
    return doc_dict
