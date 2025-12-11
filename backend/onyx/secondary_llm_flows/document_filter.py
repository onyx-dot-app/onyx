import json
import re

from onyx.context.search.models import ContextExpansionType
from onyx.context.search.models import InferenceChunk
from onyx.context.search.models import InferenceSection
from onyx.llm.interfaces import LLM
from onyx.prompts.search_prompts import DOCUMENT_CONTEXT_SELECTION_PROMPT
from onyx.prompts.search_prompts import DOCUMENT_SELECTION_PROMPT
from onyx.tools.tool_implementations.search.constants import (
    MAX_CHUNKS_FOR_RELEVANCE,
)
from onyx.utils.logger import setup_logger

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

    # Call LLM for classification
    try:
        response = llm.invoke(prompt=prompt_text)
        llm_response = response.choice.message.content

        if not llm_response:
            logger.warning(
                "LLM returned empty response for context selection, defaulting to MAIN_SECTION_ONLY"
            )
            classification = default_classification
        else:
            # Parse the response to extract the situation number (1-4)
            numbers = re.findall(r"\b[1-4]\b", llm_response)
            if numbers:
                situation = int(numbers[-1])
                # Map situation number to ContextExpansionType
                situation_to_type = {
                    1: ContextExpansionType.NOT_RELEVANT,
                    2: ContextExpansionType.MAIN_SECTION_ONLY,
                    3: ContextExpansionType.INCLUDE_ADJACENT_SECTIONS,
                    4: ContextExpansionType.FULL_DOCUMENT,
                }
                classification = situation_to_type.get(
                    situation, default_classification
                )
            else:
                logger.warning(
                    f"Could not parse situation number from LLM response: {llm_response}"
                )
                classification = default_classification

    except Exception as e:
        logger.error(f"Error calling LLM for context selection: {e}")
        classification = default_classification

    # To save some effort down the line, if there is nothing surrounding, don't allow a classification of adjacent or whole doc
    if (
        not section_above_text
        and not section_below_text
        and classification != ContextExpansionType.NOT_RELEVANT
    ):
        classification = ContextExpansionType.MAIN_SECTION_ONLY

    return classification


def select_sections_for_expansion(
    sections: list[InferenceSection],
    user_query: str,
    llm: LLM,
    # This is also what's in the prompt, just an oppinionated hyperparameter
    max_sections: int = 10,
    max_chunks_per_section: int | None = MAX_CHUNKS_FOR_RELEVANCE,
) -> tuple[list[InferenceSection], list[str] | None]:
    """Use LLM to select the most relevant document sections for expansion.

    Args:
        sections: List of InferenceSection objects to select from
        user_query: The user's search query
        llm: LLM instance to use for selection
        max_sections: Maximum number of sections to select (default: 10)
        max_chunks_per_section: Maximum chunks to consider per section (default: MAX_CHUNKS_FOR_RELEVANCE)

    Returns:
        Filtered list of InferenceSection objects selected by the LLM
    """
    if not sections:
        return [], None

    # Create a mapping of section ID to section
    section_map: dict[str, InferenceSection] = {}
    sections_dict: list[dict[str, str | int | list[str]]] = []

    for idx, section in enumerate(sections):
        # Create a unique ID for each section
        section_id = f"{idx}"
        section_map[section_id] = section

        # Format the section for the LLM
        chunk = section.center_chunk

        # Combine primary and secondary owners for authors
        authors = None
        if chunk.primary_owners or chunk.secondary_owners:
            authors = []
            if chunk.primary_owners:
                authors.extend(chunk.primary_owners)
            if chunk.secondary_owners:
                authors.extend(chunk.secondary_owners)

        # Format updated_at as ISO string if available
        updated_at_str = None
        if chunk.updated_at:
            updated_at_str = chunk.updated_at.isoformat()

        # Convert metadata to JSON string
        metadata_str = json.dumps(chunk.metadata)

        # Select only the most relevant chunks from the section to avoid flooding
        # the LLM with too much content from documents with many matching sections
        if max_chunks_per_section is not None:
            selected_chunks = select_chunks_for_relevance(
                section, max_chunks_per_section
            )
            selected_content = " ".join(chunk.content for chunk in selected_chunks)
        else:
            selected_content = section.combined_content

        section_dict: dict[str, str | int | list[str]] = {
            "section_id": idx,
            "title": chunk.semantic_identifier,
        }

        # Only include updated_at if not None
        if updated_at_str is not None:
            section_dict["updated_at"] = updated_at_str

        # Only include authors if not None
        if authors is not None:
            section_dict["authors"] = authors

        section_dict["source_type"] = str(chunk.source_type)
        section_dict["metadata"] = metadata_str
        section_dict["content"] = selected_content

        sections_dict.append(section_dict)

    # Build the prompt
    prompt_text = DOCUMENT_SELECTION_PROMPT.format(
        max_sections=max_sections,
        formatted_doc_sections=json.dumps(sections_dict, indent=2),
        user_query=user_query,
    )

    # Call LLM for selection
    try:
        response = llm.invoke(prompt=prompt_text)
        llm_response = response.choice.message.content

        if not llm_response:
            logger.warning(
                "LLM returned empty response for document selection, returning first max_sections"
            )
            return sections[:max_sections], None

        # Parse the response to extract section IDs
        # Look for patterns like [1, 2, 3] or [1,2,3] with flexible whitespace/newlines
        # Also handle unbracketed comma-separated lists like "1, 2, 3"
        # Track which sections have "!" marker (e.g., "1, 2!, 3" or "[1, 2!, 3]")
        section_ids = []
        sections_with_exclamation = set()  # Track section IDs that have "!" marker

        # First try to find a bracketed list
        bracket_pattern = r"\[([^\]]+)\]"
        bracket_match = re.search(bracket_pattern, llm_response)

        if bracket_match:
            # Extract the content between brackets
            list_content = bracket_match.group(1)
            # Split by comma, preserving the parts
            parts = [part.strip() for part in list_content.split(",")]
            for part in parts:
                # Check if this part has an exclamation mark
                has_exclamation = "!" in part
                # Extract the number (digits only)
                numbers = re.findall(r"\d+", part)
                if numbers:
                    section_id = numbers[0]
                    section_ids.append(section_id)
                    if has_exclamation:
                        sections_with_exclamation.add(section_id)
        else:
            # Try to find an unbracketed comma-separated list
            # Look for patterns like "1, 2, 3" or "1, 2!, 3"
            # This regex finds sequences of digits optionally followed by "!" and separated by commas
            comma_list_pattern = r"\b\d+!?\b(?:\s*,\s*\b\d+!?\b)*"
            comma_match = re.search(comma_list_pattern, llm_response)

            if comma_match:
                # Extract the matched comma-separated list
                list_content = comma_match.group(0)
                parts = [part.strip() for part in list_content.split(",")]
                for part in parts:
                    # Check if this part has an exclamation mark
                    has_exclamation = "!" in part
                    # Extract the number (digits only)
                    numbers = re.findall(r"\d+", part)
                    if numbers:
                        section_id = numbers[0]
                        section_ids.append(section_id)
                        if has_exclamation:
                            sections_with_exclamation.add(section_id)
            else:
                # Fallback: try to extract all numbers from the response
                # Also check for "!" after numbers
                number_pattern = r"\b(\d+)(!)?\b"
                matches = re.finditer(number_pattern, llm_response)
                for match in matches:
                    section_id = match.group(1)
                    has_exclamation = match.group(2) == "!"
                    section_ids.append(section_id)
                    if has_exclamation:
                        sections_with_exclamation.add(section_id)

        if not section_ids:
            logger.warning(
                f"Could not parse section IDs from LLM response: {llm_response}"
            )
            return sections[:max_sections], None

        # Filter sections based on LLM selection
        # Skip out-of-range IDs and don't count them toward max_sections
        selected_sections = []
        document_ids_with_exclamation = []  # Collect document_ids for sections with "!"
        num_sections = len(sections)

        for section_id_str in section_ids:
            # Convert to int
            try:
                section_id_int = int(section_id_str)
            except ValueError:
                logger.warning(f"Could not convert section ID to int: {section_id_str}")
                continue

            # Check if in valid range
            if section_id_int < 0 or section_id_int >= num_sections:
                logger.warning(
                    f"Section ID {section_id_int} is out of range [0, {num_sections-1}], skipping"
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
            f"LLM selected {len(selected_sections)} valid sections from {len(sections)} total candidates. "
            f"Selected document IDs: {selected_document_ids}. "
            f"Document IDs with exclamation: {document_ids_with_exclamation if document_ids_with_exclamation else []}"
        )

        # Return document_ids if any sections had exclamation marks, otherwise None
        return selected_sections, (
            document_ids_with_exclamation if document_ids_with_exclamation else None
        )

    except Exception as e:
        logger.error(f"Error calling LLM for document selection: {e}")
        return sections[:max_sections], None
