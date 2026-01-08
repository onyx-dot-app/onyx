import re

from onyx.chat.citation_processor import CitationMapping
from onyx.chat.citation_processor import DynamicCitationProcessor
from onyx.context.search.models import SearchDocsResponse
from onyx.tools.built_in_tools import CITEABLE_TOOLS_NAMES
from onyx.tools.models import ToolResponse


def update_citation_processor_from_tool_response(
    tool_response: ToolResponse,
    citation_processor: DynamicCitationProcessor,
) -> None:
    """Update citation processor if this was a citeable tool with a SearchDocsResponse.

    Checks if the tool call is citeable and if the response contains a SearchDocsResponse,
    then creates a mapping from citation numbers to SearchDoc objects and updates the
    citation processor.

    Args:
        tool_response: The response from the tool execution (must have tool_call set)
        citation_processor: The DynamicCitationProcessor to update
    """
    # Early return if tool_call is not set
    if tool_response.tool_call is None:
        return

    # Update citation processor if this was a search tool
    if tool_response.tool_call.tool_name in CITEABLE_TOOLS_NAMES:
        # Check if the rich_response is a SearchDocsResponse
        if isinstance(tool_response.rich_response, SearchDocsResponse):
            search_response = tool_response.rich_response

            # Create mapping from citation number to SearchDoc
            citation_to_doc: CitationMapping = {}
            for (
                citation_num,
                doc_id,
            ) in search_response.citation_mapping.items():
                # Find the SearchDoc with this doc_id
                matching_doc = next(
                    (
                        doc
                        for doc in search_response.search_docs
                        if doc.document_id == doc_id
                    ),
                    None,
                )
                if matching_doc:
                    citation_to_doc[citation_num] = matching_doc

            # Update the citation processor
            citation_processor.update_citation_mapping(citation_to_doc)


def collapse_citations(
    answer_text: str,
    existing_citation_mapping: CitationMapping,
    new_citation_mapping: CitationMapping,
) -> tuple[str, CitationMapping]:
    """Collapse the citations in the text to use the smallest possible numbers.

    This function takes citations in the text (like [25], [30], etc.) and replaces them
    with the smallest possible numbers. It starts numbering from the next available
    integer after the existing citation mapping. If a citation refers to a document
    that already exists in the existing citation mapping (matched by document_id),
    it uses the existing citation number instead of assigning a new one.

    Args:
        answer_text: The text containing citations to collapse (e.g., "See [25] and [30]")
        existing_citation_mapping: Citations already processed/displayed. These mappings
            are preserved unchanged in the output.
        new_citation_mapping: Citations from the current text that need to be collapsed.
            The keys are the citation numbers as they appear in answer_text.

    Returns:
        A tuple of (updated_text, combined_mapping) where:
        - updated_text: The text with citations replaced with collapsed numbers
        - combined_mapping: All values from existing_citation_mapping plus the new
          mappings with their (possibly renumbered) keys
    """
    # Build a reverse lookup: document_id -> existing citation number
    doc_id_to_existing_citation: dict[str, int] = {
        doc.document_id: citation_num
        for citation_num, doc in existing_citation_mapping.items()
    }

    # Determine the next available citation number
    if existing_citation_mapping:
        next_citation_num = max(existing_citation_mapping.keys()) + 1
    else:
        next_citation_num = 1

    # Build the mapping from old citation numbers (in new_citation_mapping) to new numbers
    old_to_new: dict[int, int] = {}
    additional_mappings: CitationMapping = {}

    for old_num, search_doc in new_citation_mapping.items():
        doc_id = search_doc.document_id

        # Check if this document already exists in existing citations
        if doc_id in doc_id_to_existing_citation:
            # Use the existing citation number
            old_to_new[old_num] = doc_id_to_existing_citation[doc_id]
        else:
            # Check if we've already assigned a new number to this document
            # (handles case where same doc appears with different old numbers)
            existing_new_num = None
            for mapped_old, mapped_new in old_to_new.items():
                if (
                    mapped_old in new_citation_mapping
                    and new_citation_mapping[mapped_old].document_id == doc_id
                ):
                    existing_new_num = mapped_new
                    break

            if existing_new_num is not None:
                old_to_new[old_num] = existing_new_num
            else:
                # Assign the next available number
                old_to_new[old_num] = next_citation_num
                additional_mappings[next_citation_num] = search_doc
                next_citation_num += 1

    # Pattern to match citations like [25], [1, 2, 3], [[25]], etc.
    # Also matches unicode bracket variants: 【】, ［］
    citation_pattern = re.compile(
        r"([\[【［]{2}\d+[\]】］]{2})|([\[【［]\d+(?:, ?\d+)*[\]】］])"
    )

    def replace_citation(match: re.Match) -> str:
        """Replace citation numbers in a match with their new collapsed values."""
        citation_str = match.group()

        # Determine bracket style
        if (
            citation_str.startswith("[[")
            or citation_str.startswith("【【")
            or citation_str.startswith("［［")
        ):
            open_bracket = citation_str[:2]
            close_bracket = citation_str[-2:]
            content = citation_str[2:-2]
        else:
            open_bracket = citation_str[0]
            close_bracket = citation_str[-1]
            content = citation_str[1:-1]

        # Parse and replace citation numbers
        new_nums = []
        for num_str in content.split(","):
            num_str = num_str.strip()
            if not num_str:
                continue
            try:
                num = int(num_str)
                # Only replace if we have a mapping for this number
                if num in old_to_new:
                    new_nums.append(str(old_to_new[num]))
                else:
                    # Keep original if not in our mapping
                    new_nums.append(num_str)
            except ValueError:
                new_nums.append(num_str)

        # Reconstruct the citation with original bracket style
        new_content = ", ".join(new_nums)
        return f"{open_bracket}{new_content}{close_bracket}"

    # Replace all citations in the text
    updated_text = citation_pattern.sub(replace_citation, answer_text)

    # Build the combined mapping
    combined_mapping: CitationMapping = dict(existing_citation_mapping)
    combined_mapping.update(additional_mappings)

    return updated_text, combined_mapping
