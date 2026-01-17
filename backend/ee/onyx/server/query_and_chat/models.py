from collections.abc import Sequence
from datetime import datetime

from pydantic import BaseModel
from pydantic import Field

from onyx.context.search.models import BaseFilters
from onyx.context.search.models import InferenceSection
from onyx.context.search.models import SearchDoc
from onyx.server.manage.models import StandardAnswer


class StandardAnswerRequest(BaseModel):
    message: str
    slack_bot_categories: list[str]


class StandardAnswerResponse(BaseModel):
    standard_answers: list[StandardAnswer] = Field(default_factory=list)


class SearchFlowClassificationRequest(BaseModel):
    user_query: str


class SearchFlowClassificationResponse(BaseModel):
    is_search_flow: bool


class SendSearchQueryRequest(BaseModel):
    search_query: str
    filters: BaseFilters | None = None
    num_docs_fed_to_llm_selection: int | None = None
    run_query_expansion: bool = False

    include_content: bool = False
    stream: bool = False


class SearchDocWithContent(SearchDoc):
    # Allows None because this is determined by a flag but the object used in code
    # of the search path uses this type
    content: str | None

    @classmethod
    def from_inference_sections(
        cls,
        sections: Sequence[InferenceSection],
        include_content: bool = False,
        is_internet: bool = False,
    ) -> list["SearchDocWithContent"]:
        """Convert InferenceSections to SearchDocWithContent objects.

        Args:
            sections: Sequence of InferenceSection objects
            include_content: If True, populate content field with combined_content
            is_internet: Whether these are internet search results

        Returns:
            List of SearchDocWithContent with optional content
        """
        if not sections:
            return []

        return [
            cls(
                document_id=(chunk := section.center_chunk).document_id,
                chunk_ind=chunk.chunk_id,
                semantic_identifier=chunk.semantic_identifier or "Unknown",
                link=chunk.source_links[0] if chunk.source_links else None,
                blurb=chunk.blurb,
                source_type=chunk.source_type,
                boost=chunk.boost,
                hidden=chunk.hidden,
                metadata=chunk.metadata,
                score=chunk.score,
                match_highlights=chunk.match_highlights,
                updated_at=chunk.updated_at,
                primary_owners=chunk.primary_owners,
                secondary_owners=chunk.secondary_owners,
                is_internet=is_internet,
                content=section.combined_content if include_content else None,
            )
            for section in sections
        ]


class SearchFullResponse(BaseModel):
    all_executed_queries: list[str]
    search_docs: list[SearchDocWithContent]
    # Reasoning tokens output by the LLM for the document selection
    doc_selection_reasoning: str | None = None
    # This a list of document ids that are in the search_docs list
    llm_selected_doc_ids: list[str] | None = None
    # Error message if the search failed partway through
    error: str | None = None


class SearchQueryResponse(BaseModel):
    query: str
    query_expansions: list[str] | None
    created_at: datetime


class SearchHistoryResponse(BaseModel):
    search_queries: list[SearchQueryResponse]
