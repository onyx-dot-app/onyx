from onyx.configs.constants import DocumentSource
from onyx.context.search.models import InferenceChunk
from onyx.context.search.models import InferenceSection
from onyx.tools.tool_implementations.open_url.models import WebContent
from onyx.tools.tool_implementations.web_search.models import WEB_SEARCH_PREFIX
from onyx.tools.tool_implementations.web_search.models import WebSearchResult


def truncate_search_result_content(content: str, max_chars: int = 20000) -> str:
    """Truncate search result content to a maximum number of characters"""
    if len(content) <= max_chars:
        return content
    return content[:max_chars] + " [...truncated]"


def inference_section_from_internet_page_scrape(
    result: WebContent,
    rank: int = 0,
) -> InferenceSection:
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
        recency_bias=1.0,
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
        recency_bias=1.0,
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
