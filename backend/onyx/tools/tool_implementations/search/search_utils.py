from collections import defaultdict
from collections.abc import Callable
from typing import TypeVar

from onyx.context.search.models import ContextExpansionType
from onyx.context.search.models import IndexFilters
from onyx.context.search.models import InferenceChunk
from onyx.context.search.models import InferenceSection
from onyx.context.search.utils import inference_section_from_chunks
from onyx.document_index.interfaces import DocumentIndex
from onyx.document_index.interfaces import VespaChunkRequest
from onyx.document_index.vespa.shared_utils.utils import (
    replace_invalid_doc_id_characters,
)
from onyx.llm.interfaces import LLM
from onyx.prompts.prompt_utils import clean_up_source
from onyx.secondary_llm_flows.document_filter import classify_section_relevance
from onyx.tools.tool_implementations.search.constants import (
    FULL_DOC_NUM_CHUNKS_AROUND,
)
from onyx.tools.tool_implementations.search.constants import RRF_K_VALUE
from onyx.utils.logger import setup_logger

logger = setup_logger()


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


def _retrieve_adjacent_chunks(
    section: InferenceSection,
    document_index: DocumentIndex,
    num_chunks_above: int,
    num_chunks_below: int,
) -> tuple[list[InferenceChunk], list[InferenceChunk]]:
    """Retrieve adjacent chunks above and below a section.

    Args:
        section: The InferenceSection to get adjacent chunks for
        document_index: The document index to query
        num_chunks_above: Number of chunks to retrieve above the section
        num_chunks_below: Number of chunks to retrieve below the section

    Returns:
        Tuple of (chunks_above, chunks_below)
    """
    # Get the document_id and chunk range from the section
    document_id = section.center_chunk.document_id

    # The document fetching already enforced permissions
    # the expansion does not need to do this unless it's for performance reasons
    filters = IndexFilters(access_control_list=None)

    # Find the min and max chunk_id in the section
    chunk_ids = [chunk.chunk_id for chunk in section.chunks]
    min_chunk_id = min(chunk_ids)
    max_chunk_id = max(chunk_ids)

    chunks_above: list[InferenceChunk] = []
    chunks_below: list[InferenceChunk] = []

    # Retrieve chunks above (if any)
    if num_chunks_above > 0 and min_chunk_id > 0:
        above_min = max(0, min_chunk_id - num_chunks_above)
        above_max = min_chunk_id - 1

        above_request = VespaChunkRequest(
            document_id=replace_invalid_doc_id_characters(document_id),
            min_chunk_ind=above_min,
            max_chunk_ind=above_max,
        )

        try:
            chunks_above = document_index.id_based_retrieval(
                chunk_requests=[above_request],
                filters=filters,
                batch_retrieval=True,
            )
            # Sort by chunk_id to ensure correct order
            chunks_above.sort(key=lambda c: c.chunk_id)
        except Exception as e:
            logger.warning(f"Failed to retrieve chunks above section: {e}")

    # Retrieve chunks below (if any)
    if num_chunks_below > 0:
        below_min = max_chunk_id + 1
        below_max = max_chunk_id + num_chunks_below

        below_request = VespaChunkRequest(
            document_id=replace_invalid_doc_id_characters(document_id),
            min_chunk_ind=below_min,
            max_chunk_ind=below_max,
        )

        try:
            chunks_below = document_index.id_based_retrieval(
                chunk_requests=[below_request],
                filters=filters,
                batch_retrieval=True,
            )
            # Sort by chunk_id to ensure correct order
            chunks_below.sort(key=lambda c: c.chunk_id)
        except Exception as e:
            logger.warning(f"Failed to retrieve chunks below section: {e}")

    return chunks_above, chunks_below


def merge_overlapping_sections(
    sections: list[InferenceSection],
) -> list[InferenceSection]:
    """Merge sections from the same document that have adjacent or overlapping chunks.

    Sections are merged if they come from the same document and their chunk ranges
    are adjacent (chunk_ids differ by 1) or overlapping (share chunk_ids).
    The merged sections maintain the position of the first section in the original list.

    Args:
        sections: List of InferenceSection objects to merge

    Returns:
        List of merged InferenceSection objects
    """
    if not sections:
        return []

    # Create a mapping from section to its original index for ordering
    section_to_original_index: dict[tuple[str, int], int] = {}
    for idx, section in enumerate(sections):
        section_id = (section.center_chunk.document_id, section.center_chunk.chunk_id)
        section_to_original_index[section_id] = idx

    # Group sections by document_id
    doc_sections: dict[str, list[InferenceSection]] = defaultdict(list)
    for section in sections:
        doc_sections[section.center_chunk.document_id].append(section)

    # Track which sections have been merged into a result section
    merged_sections: dict[tuple[str, int], InferenceSection] = {}

    # Process each document's sections
    for doc_id, doc_section_list in doc_sections.items():
        if not doc_section_list:
            continue

        # Sort sections by their minimum chunk_id
        doc_section_list.sort(key=lambda s: min(c.chunk_id for c in s.chunks))

        # Track merged groups - start with first section
        current_merged_chunks = set(doc_section_list[0].chunks)
        sections_in_current_group = [doc_section_list[0]]

        for i in range(1, len(doc_section_list)):
            current_section = doc_section_list[i]
            current_section_chunks = set(current_section.chunks)

            # Get chunk_id ranges
            merged_chunk_ids = {c.chunk_id for c in current_merged_chunks}
            current_chunk_ids = {c.chunk_id for c in current_section_chunks}

            # Check if adjacent or overlapping
            min_merged = min(merged_chunk_ids)
            max_merged = max(merged_chunk_ids)
            min_current = min(current_chunk_ids)
            max_current = max(current_chunk_ids)

            is_adjacent = (min_current == max_merged + 1) or (
                min_merged == max_current + 1
            )
            is_overlapping = bool(merged_chunk_ids & current_chunk_ids)

            if is_adjacent or is_overlapping:
                # Merge into current group
                current_merged_chunks.update(current_section_chunks)
                sections_in_current_group.append(current_section)
            else:
                # Finalize current group and start new one
                # Find the section that appeared first in the original list
                first_section = min(
                    sections_in_current_group,
                    key=lambda s: section_to_original_index.get(
                        (s.center_chunk.document_id, s.center_chunk.chunk_id),
                        float("inf"),
                    ),
                )

                # Create merged section with all chunks
                all_chunks = sorted(current_merged_chunks, key=lambda c: c.chunk_id)
                merged_section = inference_section_from_chunks(
                    center_chunk=first_section.center_chunk,
                    chunks=all_chunks,
                )

                if merged_section:
                    # Store the merged section for all sections in this group
                    for section in sections_in_current_group:
                        section_id = (
                            section.center_chunk.document_id,
                            section.center_chunk.chunk_id,
                        )
                        merged_sections[section_id] = merged_section

                # Start new group
                current_merged_chunks = current_section_chunks
                sections_in_current_group = [current_section]

        # Finalize the last group
        if sections_in_current_group:
            first_section = min(
                sections_in_current_group,
                key=lambda s: section_to_original_index.get(
                    (s.center_chunk.document_id, s.center_chunk.chunk_id),
                    float("inf"),
                ),
            )

            all_chunks = sorted(current_merged_chunks, key=lambda c: c.chunk_id)
            merged_section = inference_section_from_chunks(
                center_chunk=first_section.center_chunk,
                chunks=all_chunks,
            )

            if merged_section:
                for section in sections_in_current_group:
                    section_id = (
                        section.center_chunk.document_id,
                        section.center_chunk.chunk_id,
                    )
                    merged_sections[section_id] = merged_section

    # Build result list maintaining original order
    seen_section_ids: set[tuple[str, int]] = set()
    result: list[InferenceSection] = []

    for section in sections:
        section_id = (section.center_chunk.document_id, section.center_chunk.chunk_id)
        merged_section = merged_sections.get(section_id, section)

        # Use merged section's center_chunk as identifier
        merged_section_id = (
            merged_section.center_chunk.document_id,
            merged_section.center_chunk.chunk_id,
        )

        if merged_section_id not in seen_section_ids:
            seen_section_ids.add(merged_section_id)
            result.append(merged_section)

    return result


def expand_section_with_context(
    section: InferenceSection,
    user_query: str,
    llm: LLM,
    document_index: DocumentIndex,
    expand_override: bool = False,
) -> InferenceSection | None:
    """Use LLM to classify section relevance and return expanded section with appropriate context.

    This function combines classification and expansion into a single operation:
    1. Retrieves chunks needed for classification (2 chunks for prompt)
    2. Uses LLM to classify relevance (situations 1-4) unless expand_override is True
    3. For FULL_DOCUMENT, fetches additional chunks (5 total above/below)
    4. Returns the expanded section or None if not relevant

    Args:
        section: The InferenceSection to classify and expand
        search_query: The user's search query
        llm: LLM instance to use for classification
        document_index: Document index for retrieving adjacent chunks
        expand_override: If True, skip LLM classification and use FULL_DOCUMENT expansion

    Returns:
        Expanded InferenceSection with appropriate context, or None if NOT_RELEVANT
    """
    chunks_above_for_prompt: list[InferenceChunk] = []
    chunks_below_for_prompt: list[InferenceChunk] = []

    # If expand_override is True, skip LLM classification and use FULL_DOCUMENT
    if expand_override:
        classification = ContextExpansionType.FULL_DOCUMENT
        # These are not used, but need to be defined to avoid type errors
    else:
        # Retrieve 2 chunks above and below for the LLM classification prompt
        chunks_above_for_prompt, chunks_below_for_prompt = _retrieve_adjacent_chunks(
            section=section,
            document_index=document_index,
            num_chunks_above=2,
            num_chunks_below=2,
        )

        # Format the section content for the prompt
        section_above_text = (
            " ".join([c.content for c in chunks_above_for_prompt])
            if chunks_above_for_prompt
            else None
        )
        section_below_text = (
            " ".join([c.content for c in chunks_below_for_prompt])
            if chunks_below_for_prompt
            else None
        )

        # Classify section relevance using LLM
        classification = classify_section_relevance(
            document_title=section.center_chunk.semantic_identifier,
            section_text=section.combined_content,
            user_query=user_query,
            llm=llm,
            section_above_text=section_above_text,
            section_below_text=section_below_text,
        )

    # Now build the expanded section based on classification
    if classification == ContextExpansionType.NOT_RELEVANT:
        # Filter out this section
        logger.debug(
            f"LLM classified section as NOT_RELEVANT: {section.center_chunk.semantic_identifier}"
        )
        return None

    elif classification == ContextExpansionType.MAIN_SECTION_ONLY:
        # Return original section unchanged
        logger.debug(
            f"LLM classified section as MAIN_SECTION_ONLY: {section.center_chunk.semantic_identifier}"
        )
        return section

    elif classification == ContextExpansionType.INCLUDE_ADJACENT_SECTIONS:
        # Use the 2 chunks we already retrieved for the prompt
        logger.debug(
            f"LLM classified section as INCLUDE_ADJACENT_SECTIONS: {section.center_chunk.semantic_identifier}"
        )

        all_chunks = chunks_above_for_prompt + section.chunks + chunks_below_for_prompt
        if not all_chunks:
            return section

        # Create new InferenceSection with expanded chunks
        expanded_section = inference_section_from_chunks(
            center_chunk=section.center_chunk,
            chunks=all_chunks,
        )

        return expanded_section if expanded_section else section

    elif classification == ContextExpansionType.FULL_DOCUMENT:
        # Fetch 5 chunks above and below (optimal single retrieval)
        if expand_override:
            logger.debug(
                f"Section marked for FULL_DOCUMENT expansion (override): {section.center_chunk.semantic_identifier}"
            )
        else:
            logger.debug(
                f"LLM classified section as FULL_DOCUMENT: {section.center_chunk.semantic_identifier}"
            )

        chunks_above_full, chunks_below_full = _retrieve_adjacent_chunks(
            section=section,
            document_index=document_index,
            num_chunks_above=FULL_DOC_NUM_CHUNKS_AROUND,
            num_chunks_below=FULL_DOC_NUM_CHUNKS_AROUND,
        )

        # Combine all chunks: 5 above + section + 5 below
        all_chunks = chunks_above_full + section.chunks + chunks_below_full

        if not all_chunks:
            logger.warning(
                f"No chunks found for full document context expansion: {section.center_chunk.semantic_identifier}"
            )
            return section

        # Create new InferenceSection with full context
        expanded_section = inference_section_from_chunks(
            center_chunk=section.center_chunk,
            chunks=all_chunks,
        )

        return expanded_section if expanded_section else section

    else:
        # Unknown classification - default to returning original section
        logger.warning(
            f"Unknown context classification {classification}, returning original section"
        )
        return section
