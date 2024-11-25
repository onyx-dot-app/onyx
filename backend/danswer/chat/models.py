from collections.abc import Iterator
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel

from danswer.configs.constants import DocumentSource
from danswer.search.enums import QueryFlow
from danswer.search.enums import SearchType
from danswer.search.models import RetrievalDocs
from danswer.search.models import SearchResponse
from danswer.tools.tool_implementations.custom.base_tool_types import ToolResultType


class LlmDoc(BaseModel):
    """This contains the minimal set information for the LLM portion including citations"""

    document_id: str
    content: str
    blurb: str
    semantic_identifier: str
    source_type: DocumentSource
    metadata: dict[str, str | list[str]]
    updated_at: datetime | None
    link: str | None
    source_links: dict[int, str] | None


# First chunk of info for streaming QA
class QADocsResponse(RetrievalDocs):
    rephrased_query: str | None = None
    predicted_flow: QueryFlow | None
    predicted_search: SearchType | None
    applied_source_filters: list[DocumentSource] | None
    applied_time_cutoff: datetime | None
    recency_bias_multiplier: float

    def model_dump(self, *args: list, **kwargs: dict[str, Any]) -> dict[str, Any]:  # type: ignore
        initial_dict = super().model_dump(mode="json", *args, **kwargs)  # type: ignore
        initial_dict["applied_time_cutoff"] = (
            self.applied_time_cutoff.isoformat() if self.applied_time_cutoff else None
        )

        return initial_dict


class StreamStopReason(Enum):
    CONTEXT_LENGTH = "context_length"
    CANCELLED = "cancelled"


class StreamStopInfo(BaseModel):
    stop_reason: StreamStopReason

    def model_dump(self, *args: list, **kwargs: dict[str, Any]) -> dict[str, Any]:  # type: ignore
        data = super().model_dump(mode="json", *args, **kwargs)  # type: ignore
        data["stop_reason"] = self.stop_reason.name
        return data


class LLMRelevanceFilterResponse(BaseModel):
    llm_selected_doc_indices: list[int]


class FinalUsedContextDocsResponse(BaseModel):
    final_context_docs: list[LlmDoc]


class RelevanceAnalysis(BaseModel):
    relevant: bool
    content: str | None = None


class SectionRelevancePiece(RelevanceAnalysis):
    """LLM analysis mapped to an Inference Section"""

    document_id: str
    chunk_id: int  # ID of the center chunk for a given inference section


class DocumentRelevance(BaseModel):
    """Contains all relevance information for a given search"""

    relevance_summaries: dict[str, RelevanceAnalysis]


class DanswerAnswerPiece(BaseModel):
    # A small piece of a complete answer. Used for streaming back answers.
    answer_piece: str | None  # if None, specifies the end of an Answer


# An intermediate representation of citations, later translated into
# a mapping of the citation [n] number to SearchDoc
class CitationInfo(BaseModel):
    citation_num: int
    document_id: str


class AllCitations(BaseModel):
    citations: list[CitationInfo]


# This is a mapping of the citation number to the document index within
# the result search doc set
class MessageSpecificCitations(BaseModel):
    citation_map: dict[int, int]


class MessageResponseIDInfo(BaseModel):
    user_message_id: int | None
    reserved_assistant_message_id: int


class StreamingError(BaseModel):
    error: str
    stack_trace: str | None = None


class DanswerQuote(BaseModel):
    # This is during inference so everything is a string by this point
    quote: str
    document_id: str
    link: str | None
    source_type: str
    semantic_identifier: str
    blurb: str


class DanswerQuotes(BaseModel):
    quotes: list[DanswerQuote]


class DanswerContext(BaseModel):
    content: str
    document_id: str
    semantic_identifier: str
    blurb: str


class DanswerContexts(BaseModel):
    contexts: list[DanswerContext]


class DanswerAnswer(BaseModel):
    answer: str | None


class QAResponse(SearchResponse, DanswerAnswer):
    quotes: list[DanswerQuote] | None
    contexts: list[DanswerContexts] | None
    predicted_flow: QueryFlow
    predicted_search: SearchType
    eval_res_valid: bool | None = None
    llm_selected_doc_indices: list[int] | None = None
    error_msg: str | None = None


class FileChatDisplay(BaseModel):
    file_ids: list[str]


class CustomToolResponse(BaseModel):
    response: ToolResultType
    tool_name: str


AnswerQuestionPossibleReturn = (
    DanswerAnswerPiece
    | DanswerQuotes
    | CitationInfo
    | DanswerContexts
    | FileChatDisplay
    | CustomToolResponse
    | StreamingError
    | StreamStopInfo
)


AnswerQuestionStreamReturn = Iterator[AnswerQuestionPossibleReturn]


class LLMMetricsContainer(BaseModel):
    prompt_tokens: int
    response_tokens: int
