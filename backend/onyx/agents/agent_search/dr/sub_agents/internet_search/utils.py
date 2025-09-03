from onyx.agents.agent_search.dr.sub_agents.internet_search.models import (
    InternetContent,
)
from onyx.agents.agent_search.dr.sub_agents.internet_search.models import (
    InternetSearchResult,
)
from onyx.configs.constants import DocumentSource
from onyx.context.search.models import InferenceChunk
from onyx.context.search.models import InferenceSection


def truncate_search_result_content(content: str, max_chars: int = 10000) -> str:
    """Truncate search result content to a maximum number of characters"""
    if len(content) <= max_chars:
        return content
    return content[:max_chars] + "..."


def dummy_inference_section_from_internet_content(
    result: InternetContent,
) -> InferenceSection:
    truncated_content = truncate_search_result_content(result.full_content)
    return InferenceSection(
        center_chunk=InferenceChunk(
            chunk_id=0,
            blurb=result.title,
            content=truncated_content,
            source_links={0: result.link},
            section_continuation=False,
            document_id="INTERNET_SEARCH_DOC_" + result.link,
            source_type=DocumentSource.WEB,
            semantic_identifier=result.link,
            title=result.title,
            boost=1,
            recency_bias=1.0,
            score=1.0,
            hidden=False,
            metadata={},
            match_highlights=[],
            doc_summary=truncated_content,
            chunk_context=truncated_content,
            updated_at=result.published_date,
            image_file_id=None,
        ),
        chunks=[],
        combined_content=truncated_content,
    )


def dummy_inference_section_from_internet_search_result(
    result: InternetSearchResult,
) -> InferenceSection:
    return InferenceSection(
        center_chunk=InferenceChunk(
            chunk_id=0,
            blurb=result.title,
            content="",
            source_links={0: result.link},
            section_continuation=False,
            document_id="INTERNET_SEARCH_DOC_" + result.link,
            source_type=DocumentSource.WEB,
            semantic_identifier=result.link,
            title=result.title,
            boost=1,
            recency_bias=1.0,
            score=1.0,
            hidden=False,
            metadata={},
            match_highlights=[],
            doc_summary="",
            chunk_context="",
            updated_at=result.published_date,
            image_file_id=None,
        ),
        chunks=[],
        combined_content="",
    )
