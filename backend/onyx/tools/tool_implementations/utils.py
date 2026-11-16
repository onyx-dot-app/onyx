import json

from onyx.context.search.models import InferenceSection
from onyx.context.search.utils import sandbox_filename_for_document
from onyx.tools.models import (
    CodeModeResultKind,
    CodeModeResultSpec,
    SearchResult,
    SearchResults,
)
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


SEARCH_RESULTS_CODE_MODE_RESULT = CodeModeResultSpec(
    kind=CodeModeResultKind.JSON_OBJECT, model=SearchResults, cites=True
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
    results: list[SearchResult] = []
    for section in top_sections:
        chunk = section.center_chunk
        link = (
            next(iter(chunk.source_links.values()), None)
            if include_link and chunk.source_links
            else None
        )
        filename = (
            sandbox_filename_for_document(chunk.semantic_identifier, chunk.file_id)
            if chunk.file_id is not None
            else None
        )
        results.append(
            SearchResult(
                document=document_id_to_citation_id[chunk.document_id],
                title=chunk.semantic_identifier,
                updated_at=chunk.updated_at.isoformat() if chunk.updated_at else None,
                authors=[*(chunk.primary_owners or []), *(chunk.secondary_owners or [])]
                or None,
                source_type=chunk.source_type.value if include_source_type else None,
                url=link or None,
                document_identifier=chunk.document_id if include_document_id else None,
                file_name=filename,
                content=FILE_ASSOCIATED_GUIDANCE.format(
                    filename=filename, content=chunk.content
                )
                if filename is not None
                else section.combined_content,
                metadata=json.dumps(chunk.metadata, ensure_ascii=False)
                if chunk.metadata
                else None,
            )
        )
    return (
        SearchResults(results=results, note=note or None).model_dump_json(),
        citation_mapping,
    )
