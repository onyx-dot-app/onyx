import inspect
import json
from typing import NotRequired, TypedDict

from onyx.context.search.models import InferenceSection
from onyx.context.search.utils import sandbox_filename_for_document
from onyx.tools.models import CodeModeResultKind, CodeModeResultSpec
from onyx.utils.logger import setup_logger

logger = setup_logger()


def truncation_marker(omitted: int) -> str:
    """The marker that `truncate_output(keep_tail=True)` puts between head and tail."""
    return f"\n... [output truncated, {omitted} characters omitted] ...\n"


def truncate_output(
    output: str,
    max_length: int,
    label: str = "output",
    *,
    keep_tail: bool = False,
) -> str:
    """Truncate to ``max_length`` and note how many chars were elided.

    With ``keep_tail`` the first and last halves are kept and the marker sits between
    them; otherwise the marker is a footer. ``label`` is only used in the debug log.
    """
    if len(output) <= max_length:
        return output
    omitted = len(output) - max_length
    if keep_tail:
        head_length = max_length // 2
        tail_length = max_length - head_length
        truncated = (
            output[:head_length]
            + truncation_marker(omitted)
            + (output[-tail_length:] if tail_length else "")
        )
    else:
        truncated = (
            output[:max_length]
            + f"\n... [output truncated, {omitted} characters omitted]"
        )
    logger.debug("Truncated %s: %s", label, truncated)
    return truncated


FILE_ASSOCIATED_GUIDANCE = (
    "Only a short excerpt from this document is shown below. The complete "
    'file is available in the sandbox as "{filename}" — prefer the Python '
    "code interpreter to read, parse, or analyze it\n\n"
    "Excerpt: {content}"
)


# Search-like tool results as the model and code mode programs read them
# (convert_inference_sections_to_llm_string). The code mode stubs declare these
# classes from their source.
class SearchResult(TypedDict):
    document: int
    """Citation number. Cite it in the answer as [n]."""
    title: str
    content: str
    url: NotRequired[str]
    updated_at: NotRequired[str]
    authors: NotRequired[list[str]]
    source_type: NotRequired[str]
    file_name: NotRequired[str]
    document_identifier: NotRequired[str]
    metadata: NotRequired[str]
    """JSON-encoded metadata of the document."""


class SearchResults(TypedDict):
    results: list[SearchResult]
    note: NotRequired[str]
    message: NotRequired[str]


SEARCH_RESULTS_CODE_MODE_RESULT = CodeModeResultSpec(
    kind=CodeModeResultKind.JSON_OBJECT,
    annotation=SearchResults.__name__,
    declaration="\n\n\n".join(
        inspect.getsource(typed_dict).strip()
        for typed_dict in (SearchResult, SearchResults)
    ),
    cites=True,
)


def convert_inference_sections_to_llm_string(
    top_sections: list[InferenceSection],
    citation_start: int = 1,
    limit: int | None = None,
    include_source_type: bool = True,
    include_link: bool = False,
    include_document_id: bool = False,
    note: str | None = None,
) -> tuple[str, dict[int, str]]:
    """Convert InferenceSection objects to a JSON string for LLM.

    Returns a JSON string with document results and a citation mapping.
    """
    # Apply limit if specified
    if limit is not None:
        top_sections = top_sections[:limit]

    # Group sections by document_id to assign same citation_id to sections from same document
    document_id_to_citation_id: dict[str, int] = {}
    citation_mapping: dict[int, str] = {}
    current_citation_id = citation_start

    # First pass: assign citation_ids to unique document_ids
    for section in top_sections:
        document_id = section.center_chunk.document_id
        if document_id not in document_id_to_citation_id:
            document_id_to_citation_id[document_id] = current_citation_id
            citation_mapping[current_citation_id] = document_id
            current_citation_id += 1

    # Second pass: build results with citation_ids assigned per document
    results = []

    for section in top_sections:
        chunk = section.center_chunk
        document_id = chunk.document_id
        citation_id = document_id_to_citation_id[document_id]

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

        # Build result dictionary in desired order, only including non-None/empty fields
        result = {
            "document": citation_id,
            "title": chunk.semantic_identifier,
        }
        if updated_at_str is not None:
            result["updated_at"] = updated_at_str
        if authors is not None:
            result["authors"] = authors
        if include_source_type:
            result["source_type"] = chunk.source_type.value
        if include_link:
            # Get the first link from the center chunk's source_links dict
            link = None
            if chunk.source_links:
                # source_links is dict[int, str], get the first value
                link = next(iter(chunk.source_links.values()), None)
            if link:
                result["url"] = link
        if include_document_id:
            result["document_identifier"] = chunk.document_id
        if chunk.file_id is not None:
            filename = sandbox_filename_for_document(
                chunk.semantic_identifier, chunk.file_id
            )
            result["file_name"] = filename

            result["content"] = FILE_ASSOCIATED_GUIDANCE.format(
                filename=filename, content=chunk.content
            )
        else:
            result["content"] = section.combined_content
        if chunk.metadata:
            result["metadata"] = json.dumps(chunk.metadata, ensure_ascii=False)
        results.append(result)

    payload: dict[str, object] = {}
    payload["results"] = results
    if note:
        payload["note"] = note

    return (
        json.dumps(payload, separators=(",", ":"), ensure_ascii=False),
        citation_mapping,
    )
