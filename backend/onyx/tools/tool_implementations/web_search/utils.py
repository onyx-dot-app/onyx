from onyx.configs.constants import DocumentSource
from onyx.context.search.models import InferenceChunk
from onyx.context.search.models import InferenceSection
from onyx.context.search.models import SearchDoc
from onyx.tools.tool_implementations.open_url.models import WebContent
from onyx.tools.tool_implementations.open_url.snippet_matcher import (
    find_snippet_in_content,
)
from onyx.tools.tool_implementations.web_search.models import WEB_SEARCH_PREFIX
from onyx.tools.tool_implementations.web_search.models import WebSearchResult


TRUNCATED_CONTENT_SUFFIX = " [...truncated]"
TRUNCATED_CONTENT_PREFIX = "[...truncated] "

MAX_CHARS_PER_URL = 15000


def filter_web_search_results_with_no_title_or_snippet(
    results: list[WebSearchResult],
) -> list[WebSearchResult]:
    """Filter out results that have neither a title nor a snippet.

    Some providers can return entries that only include a URL. Downstream uses
    titles/snippets for display and prompting, so we drop those empty entries
    centrally (rather than duplicating the check in each client).
    """
    filtered: list[WebSearchResult] = []
    for result in results:
        if result.title.strip() or result.snippet.strip():
            filtered.append(result)
    return filtered


def truncate_search_result_content(
    content: str, max_chars: int = MAX_CHARS_PER_URL
) -> str:
    """Truncate search result content to a maximum number of characters"""
    if len(content) <= max_chars:
        return content
    return content[:max_chars] + TRUNCATED_CONTENT_SUFFIX


def _truncate_content_around_snippet(
    content: str, snippet: str, max_chars: int = MAX_CHARS_PER_URL
) -> str:
    """
    Truncates content around snippet with max_chars

    Assumes snippet exists
    """
    result = find_snippet_in_content(content, snippet)

    if not result.snippet_located:
        return ""

    start_idx = result.start_idx
    end_idx = result.end_idx

    new_start, new_end = _expand_range_centered(
        start_idx, end_idx + 1, len(content), max_chars
    )

    truncated_content = content[new_start:new_end]

    # Add the AFFIX to the start and end of truncated content
    if new_start > 0:
        truncated_content = TRUNCATED_CONTENT_PREFIX + truncated_content

    if new_end < len(content):
        truncated_content = truncated_content + TRUNCATED_CONTENT_SUFFIX

    return truncated_content


def _expand_range_centered(
    start_idx: int, end_idx: int, N: int, target_size: int
) -> tuple[int, int]:
    """
    Expands a range [start_idx, end_idx) to be centered within a list of size N

    Args:
        start_idx: Starting index (inclusive)
        end_idx: Ending index (exclusive)
        N: Size of the list
        target_size: Target size of the range

    Returns:
        Tuple of (new start index, new end index)
    """
    current_size = end_idx - start_idx

    if current_size >= target_size:
        return start_idx, end_idx

    padding_needed = target_size - current_size
    padding_top = padding_needed // 2
    padding_bottom = padding_needed - padding_top

    # Try expand symmetrically
    new_start = start_idx - padding_top
    new_end = end_idx + padding_bottom

    # Handle overflow
    if new_start < 0:
        overflow = -new_start
        new_start = 0
        new_end = min(N, new_end + overflow)

    if new_end > N:
        overflow = new_end - N
        new_end = N
        new_start = max(0, new_start - overflow)

    return new_start, new_end


def inference_section_from_internet_page_scrape(
    result: WebContent,
    snippet: str,
    rank: int = 0,
) -> InferenceSection:
    # truncate the content around snippet if snippet exists
    truncated_content = ""
    if snippet:
        truncated_content = _truncate_content_around_snippet(
            result.full_content, snippet
        )

    # Fallback if no snippet exists or we failed to find it
    if not truncated_content:
        truncated_content = truncate_search_result_content(result.full_content)

    # Calculate score using reciprocal rank to preserve ordering
    score = 1.0 / (rank + 1)

    inference_chunk = InferenceChunk(
        chunk_id=0,
        blurb=result.title,
        content=truncated_content,
        source_links={0: result.link},
        section_continuation=False,
        document_id=WEB_SEARCH_PREFIX + result.link,
        source_type=DocumentSource.WEB,
        semantic_identifier=result.title,
        title=result.title,
        boost=1,
        score=score,
        hidden=False,
        metadata={},
        match_highlights=[truncated_content],
        doc_summary="",
        chunk_context="",
        updated_at=result.published_date,
        image_file_id=None,
    )
    return InferenceSection(
        center_chunk=inference_chunk,
        chunks=[inference_chunk],
        combined_content=truncated_content,
    )


def inference_section_from_internet_search_result(
    result: WebSearchResult,
    rank: int = 0,
) -> InferenceSection:
    # Calculate score using reciprocal rank to preserve ordering
    score = 1.0 / (rank + 1)

    chunk = InferenceChunk(
        chunk_id=0,
        blurb=result.snippet,
        content=result.snippet,
        source_links={0: result.link},
        section_continuation=False,
        document_id=WEB_SEARCH_PREFIX + result.link,
        source_type=DocumentSource.WEB,
        semantic_identifier=result.title,
        title=result.title,
        boost=1,
        score=score,
        hidden=False,
        metadata={},
        match_highlights=[result.snippet],
        doc_summary="",
        chunk_context="",
        updated_at=result.published_date,
        image_file_id=None,
    )

    return InferenceSection(
        center_chunk=chunk,
        chunks=[chunk],
        combined_content=result.snippet,
    )


def extract_url_snippet_map(documents: list[SearchDoc]) -> dict[str, str]:
    """
    Given a list of SearchDocs, this will extract the url -> summary map.
    """
    url_snippet_map: dict[str, str] = {}
    for document in documents:
        if document.source_type == DocumentSource.WEB and document.link:
            url_snippet_map[document.link] = document.blurb
    return url_snippet_map
