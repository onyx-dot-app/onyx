import json
import re

from onyx.configs.chat_configs import SECONDARY_LLM_FLOW_TIMEOUT_S
from onyx.context.search.models import (
    ContextExpansionType,
    InferenceChunk,
    InferenceSection,
)
from onyx.llm.interfaces import LLM
from onyx.llm.models import ReasoningEffort, UserMessage
from onyx.prompts.search_prompts import (
    DOCUMENT_CONTEXT_SELECTION_PROMPT,
    DOCUMENT_SELECTION_PROMPT,
    TRY_TO_FILL_TO_MAX_INSTRUCTIONS,
)
from onyx.tools.tool_implementations.search.constants import MAX_CHUNKS_FOR_RELEVANCE
from onyx.tracing.flows import LLMFlow
from onyx.tracing.llm_utils import llm_generation_span, record_llm_response
from onyx.utils.logger import setup_logger
from onyx.utils.timing import log_function_time

logger = setup_logger()


def select_chunks_for_relevance(
    section: InferenceSection,
    max_chunks: int = MAX_CHUNKS_FOR_RELEVANCE,
) -> list[InferenceChunk]:
    """Select a subset of chunks from a section based on center chunk position.

    Logic:
    - Always include the center chunk
    - If there are chunks directly next to it by index, grab the preceding and following
    - Otherwise grab 2 in the direction that does exist (2 before or 2 after)
    - If there are not enough in either direction, just grab what's available
    - If there are no other chunks, just use the central chunk

    Args:
        section: InferenceSection with center_chunk and chunks
        max_chunks: Maximum number of chunks to select (default: MAX_CHUNKS_FOR_RELEVANCE)

    Returns:
        List of selected InferenceChunks ordered by position
    """
    if max_chunks <= 0:
        return []

    center_chunk = section.center_chunk
    all_chunks = section.chunks

    # Find the index of the center chunk in the chunks list
    try:
        center_index = next(
            i
            for i, chunk in enumerate(all_chunks)
            if chunk.chunk_id == center_chunk.chunk_id
        )
    except StopIteration:
        # If center chunk not found in chunks list, just return center chunk
        return [center_chunk]

    if max_chunks == 1:
        return [center_chunk]

    # Calculate how many chunks to take before and after
    chunks_needed = max_chunks - 1  # minus 1 for center chunk

    # Determine available chunks before and after center
    chunks_before_available = center_index
    chunks_after_available = len(all_chunks) - center_index - 1

    # Start with balanced distribution (1 before, 1 after for max_chunks=3)
    chunks_before = min(chunks_needed // 2, chunks_before_available)
    chunks_after = min(chunks_needed // 2, chunks_after_available)

    # Allocate remaining chunks to whichever direction has availability
    remaining = chunks_needed - chunks_before - chunks_after
    if remaining > 0:
        # Try to add more chunks before center if available
        if chunks_before_available > chunks_before:
            additional_before = min(remaining, chunks_before_available - chunks_before)
            chunks_before += additional_before
            remaining -= additional_before
        # Try to add more chunks after center if available
        if remaining > 0 and chunks_after_available > chunks_after:
            additional_after = min(remaining, chunks_after_available - chunks_after)
            chunks_after += additional_after

    # Select the chunks
    start_index = center_index - chunks_before
    end_index = center_index + chunks_after + 1  # +1 to include center and chunks after

    return all_chunks[start_index:end_index]


@log_function_time(print_only=True)
def classify_section_relevance(
    document_title: str,
    section_text: str,
    user_query: str,
    llm: LLM,
    section_above_text: str | None,
    section_below_text: str | None,
) -> ContextExpansionType:
    """Use LLM to classify section relevance and determine context expansion type.

    Args:
        section_text: The text content of the section to classify
        user_query: The user's search query
        llm: LLM instance to use for classification
        section_above_text: Text content from chunks above the section
        section_below_text: Text content from chunks below the section

    Returns:
        ContextExpansionType indicating how the section should be expanded
    """
    # Build the prompt
    prompt_text = DOCUMENT_CONTEXT_SELECTION_PROMPT.format(
        document_title=document_title,
        main_section=section_text,
        section_above=section_above_text if section_above_text else "N/A",
        section_below=section_below_text if section_below_text else "N/A",
        user_query=user_query,
    )

    # Default to MAIN_SECTION_ONLY
    default_classification = ContextExpansionType.MAIN_SECTION_ONLY

    # Call LLM for classification with Braintrust tracing
    try:
        prompt_msg = UserMessage(content=prompt_text)
        with llm_generation_span(
            llm=llm,
            flow=LLMFlow.CLASSIFY_SECTION_RELEVANCE,
            input_messages=[prompt_msg],
        ) as span_generation:
            response = llm.invoke(
                prompt=prompt_msg,
                reasoning_effort=ReasoningEffort.OFF,
                timeout_override=SECONDARY_LLM_FLOW_TIMEOUT_S,
            )
            record_llm_response(span_generation, response)
            llm_response = response.choice.message.content

        if not llm_response:
            logger.warning(
                "LLM returned empty response for context selection, defaulting to MAIN_SECTION_ONLY"
            )
            classification = default_classification
        else:
            # Parse the response to extract the situation number (0-3)
            numbers = re.findall(r"\b[0-3]\b", llm_response)
            if numbers:
                situation = int(numbers[-1])
                # Map situation number to ContextExpansionType
                situation_to_type = {
                    0: ContextExpansionType.NOT_RELEVANT,
                    1: ContextExpansionType.MAIN_SECTION_ONLY,
                    2: ContextExpansionType.INCLUDE_ADJACENT_SECTIONS,
                    3: ContextExpansionType.FULL_DOCUMENT,
                }
                classification = situation_to_type.get(
                    situation, default_classification
                )
            else:
                logger.warning(
                    "Could not parse situation number from LLM response: %s",
                    llm_response,
                )
                classification = default_classification

    except Exception as e:
        logger.error("Error calling LLM for context selection: %s", e)
        classification = default_classification

    # To save some effort down the line, if there is nothing surrounding, don't allow a classification of adjacent or whole doc
    if (
        not section_above_text
        and not section_below_text
        and classification != ContextExpansionType.NOT_RELEVANT
    ):
        classification = ContextExpansionType.MAIN_SECTION_ONLY

    return classification


def _format_section_for_llm(
    idx: int,
    section: InferenceSection,
    max_chunks_per_section: int | None,
) -> dict[str, str | int | list[str]]:
    """Build the JSON-serializable description of one section for the LLM prompt.

    Key insertion order defines the order of the keys in the prompt.
    """
    chunk = section.center_chunk

    # Combine primary and secondary owners for authors
    authors: list[str] | None = None
    if chunk.primary_owners or chunk.secondary_owners:
        authors = []
        if chunk.primary_owners:
            authors.extend(chunk.primary_owners)
        if chunk.secondary_owners:
            authors.extend(chunk.secondary_owners)

    # Select only the most relevant chunks from the section to avoid flooding
    # the LLM with too much content from documents with many matching sections
    if max_chunks_per_section is not None:
        selected_chunks = select_chunks_for_relevance(section, max_chunks_per_section)
        selected_content = " ".join(
            selected_chunk.content for selected_chunk in selected_chunks
        )
    else:
        selected_content = section.combined_content

    section_dict: dict[str, str | int | list[str]] = {
        "section_id": idx,
        "title": chunk.semantic_identifier,
    }

    # Only include updated_at if available
    if chunk.updated_at:
        section_dict["updated_at"] = chunk.updated_at.isoformat()

    # Only include authors if not None
    if authors is not None:
        section_dict["authors"] = authors

    section_dict["source_type"] = str(chunk.source_type)
    section_dict["metadata"] = json.dumps(chunk.metadata)
    section_dict["content"] = selected_content

    return section_dict


def _parse_id_list(list_content: str) -> tuple[list[str], set[str]]:
    """Parse a comma-separated list of section IDs, each optionally marked by "!"."""
    section_ids: list[str] = []
    sections_with_exclamation: set[str] = set()

    for part in [part.strip() for part in list_content.split(",")]:
        # Check if this part has an exclamation mark
        has_exclamation = "!" in part
        # Extract the number (digits only)
        numbers = re.findall(r"\d+", part)
        if numbers:
            section_id = numbers[0]
            section_ids.append(section_id)
            if has_exclamation:
                sections_with_exclamation.add(section_id)

    return section_ids, sections_with_exclamation


def _parse_section_ids(llm_response: str) -> tuple[list[str], set[str]]:
    """Extract the selected section IDs and the ones marked with "!" from a response.

    Handles bracketed lists like "[1, 2, 3]", unbracketed lists like "1, 2, 3" and,
    as a last resort, every number in the response.
    """
    # First try to find a bracketed list
    bracket_match = re.search(r"\[([^\]]+)\]", llm_response)
    if bracket_match:
        return _parse_id_list(bracket_match.group(1))

    # Try to find an unbracketed comma-separated list
    # Look for patterns like "1, 2, 3" or "1, 2!, 3"
    comma_match = re.search(r"\b\d+!?\b(?:\s*,\s*\b\d+!?\b)*", llm_response)
    if comma_match:
        return _parse_id_list(comma_match.group(0))

    # Fallback: try to extract all numbers from the response
    # Also check for "!" after numbers
    section_ids: list[str] = []
    sections_with_exclamation: set[str] = set()
    for match in re.finditer(r"\b(\d+)(!)?\b", llm_response):
        section_id = match.group(1)
        section_ids.append(section_id)
        if match.group(2) == "!":
            sections_with_exclamation.add(section_id)

    return section_ids, sections_with_exclamation


def _collect_selected_sections(
    section_ids: list[str],
    sections_with_exclamation: set[str],
    section_map: dict[str, InferenceSection],
    num_sections: int,
    max_sections: int,
) -> tuple[list[InferenceSection], list[str]]:
    """Resolve parsed section IDs to sections, up to max_sections.

    Out-of-range and unparsable IDs are skipped and don't count toward max_sections.
    Also returns the document IDs of the sections marked with "!".
    """
    selected_sections: list[InferenceSection] = []
    document_ids_with_exclamation: list[str] = []

    for section_id_str in section_ids:
        # Convert to int
        try:
            section_id_int = int(section_id_str)
        except ValueError:
            logger.warning("Could not convert section ID to int: %s", section_id_str)
            continue

        # Check if in valid range
        if section_id_int < 0 or section_id_int >= num_sections:
            logger.warning(
                "Section ID %s is out of range [0, %s], skipping",
                section_id_int,
                num_sections - 1,
            )
            continue

        # Convert back to string for section_map lookup
        section_id = str(section_id_int)
        if section_id in section_map:
            section = section_map[section_id]
            selected_sections.append(section)

            # If this section has an exclamation mark, collect its document_id
            if section_id_str in sections_with_exclamation:
                document_id = section.center_chunk.document_id
                if document_id not in document_ids_with_exclamation:
                    document_ids_with_exclamation.append(document_id)

        # Stop if we've reached max_sections valid selections
        if len(selected_sections) >= max_sections:
            break

    return selected_sections, document_ids_with_exclamation


@log_function_time(print_only=True)
def select_sections_for_expansion(
    sections: list[InferenceSection],
    user_query: str,
    llm: LLM,
    max_sections: int = 10,
    max_chunks_per_section: int | None = MAX_CHUNKS_FOR_RELEVANCE,
    try_to_fill_to_max: bool = False,
) -> tuple[list[InferenceSection], list[str] | None]:
    """Use LLM to select the most relevant document sections for expansion.

    Args:
        sections: List of InferenceSection objects to select from
        user_query: The user's search query
        llm: LLM instance to use for selection
        max_sections: Maximum number of sections to select (default: 10)
        max_chunks_per_section: Maximum chunks to consider per section (default: MAX_CHUNKS_FOR_RELEVANCE)

    Returns:
        A tuple of:
        - Filtered list of InferenceSection objects selected by the LLM
        - List of document IDs for sections marked with "!" by the LLM, or None if none.
          Note: The "!" marker support exists in parsing but is not currently used because
          the prompt does not instruct the LLM to use it.
    """
    if not sections:
        return [], None

    # Create a mapping of section ID to section
    section_map: dict[str, InferenceSection] = {}
    sections_dict: list[dict[str, str | int | list[str]]] = []

    for idx, section in enumerate(sections):
        # Create a unique ID for each section
        section_map[f"{idx}"] = section
        sections_dict.append(
            _format_section_for_llm(idx, section, max_chunks_per_section)
        )

    # Build the prompt
    extra_instructions = TRY_TO_FILL_TO_MAX_INSTRUCTIONS if try_to_fill_to_max else ""
    prompt_text = UserMessage(
        content=DOCUMENT_SELECTION_PROMPT.format(
            max_sections=max_sections,
            extra_instructions=extra_instructions,
            formatted_doc_sections=json.dumps(sections_dict, indent=2),
            user_query=user_query,
        )
    )

    # Call LLM for selection with Braintrust tracing
    try:
        with llm_generation_span(
            llm=llm,
            flow=LLMFlow.SELECT_SECTIONS_FOR_EXPANSION,
            input_messages=[prompt_text],
        ) as span_generation:
            response = llm.invoke(
                prompt=[prompt_text],
                reasoning_effort=ReasoningEffort.OFF,
                timeout_override=SECONDARY_LLM_FLOW_TIMEOUT_S,
            )
            record_llm_response(span_generation, response)
            llm_response = response.choice.message.content

        if not llm_response:
            logger.warning(
                "LLM returned empty response for document selection, returning first max_sections"
            )
            return sections[:max_sections], None

        # Parse the response to extract section IDs and the "!" markers
        section_ids, sections_with_exclamation = _parse_section_ids(llm_response)

        if not section_ids:
            logger.warning(
                "Could not parse section IDs from LLM response: %s", llm_response
            )
            return sections[:max_sections], None

        # Filter sections based on LLM selection
        selected_sections, document_ids_with_exclamation = _collect_selected_sections(
            section_ids=section_ids,
            sections_with_exclamation=sections_with_exclamation,
            section_map=section_map,
            num_sections=len(sections),
            max_sections=max_sections,
        )

        if not selected_sections:
            logger.warning(
                "No valid sections selected from LLM response, returning first max_sections"
            )
            return sections[:max_sections], None

        # Collect all selected document IDs
        selected_document_ids = [
            section.center_chunk.document_id for section in selected_sections
        ]

        logger.debug(
            "LLM selected %s valid sections from %s total candidates. Selected document IDs: %s. Document IDs with exclamation: %s",
            len(selected_sections),
            len(sections),
            selected_document_ids,
            document_ids_with_exclamation if document_ids_with_exclamation else [],
        )

        # Return document_ids if any sections had exclamation marks, otherwise None
        return selected_sections, (
            document_ids_with_exclamation if document_ids_with_exclamation else None
        )

    except Exception as e:
        logger.error("Error calling LLM for document selection: %s", e)
        return sections[:max_sections], None
