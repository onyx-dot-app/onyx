from collections.abc import Callable
from collections.abc import Iterator
from datetime import datetime
from enum import Enum
from typing import Any
from typing import TYPE_CHECKING

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import model_validator

from onyx.configs.constants import DocumentSource
from onyx.configs.constants import MessageType
from onyx.context.search.enums import QueryFlow
from onyx.context.search.enums import RecencyBiasSetting
from onyx.context.search.enums import SearchType
from onyx.context.search.models import RetrievalDocs
from onyx.llm.override_models import PromptOverride
from onyx.tools.models import ToolCallFinalResult
from onyx.tools.models import ToolCallKickoff
from onyx.tools.models import ToolResponse
from onyx.tools.tool_implementations.custom.base_tool_types import ToolResultType

if TYPE_CHECKING:
    from onyx.db.models import Prompt


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
    match_highlights: list[str] | None


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


class OnyxAnswerPiece(BaseModel):
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


class OnyxContext(BaseModel):
    content: str
    document_id: str
    semantic_identifier: str
    blurb: str


class OnyxContexts(BaseModel):
    contexts: list[OnyxContext]


class OnyxAnswer(BaseModel):
    answer: str | None


class ThreadMessage(BaseModel):
    message: str
    sender: str | None = None
    role: MessageType = MessageType.USER


class ChatOnyxBotResponse(BaseModel):
    answer: str | None = None
    citations: list[CitationInfo] | None = None
    docs: QADocsResponse | None = None
    llm_selected_doc_indices: list[int] | None = None
    error_msg: str | None = None
    chat_message_id: int | None = None
    answer_valid: bool = True  # Reflexion result, default True if Reflexion not run


class FileChatDisplay(BaseModel):
    file_ids: list[str]


class CustomToolResponse(BaseModel):
    response: ToolResultType
    tool_name: str


class ToolConfig(BaseModel):
    id: int


class PromptOverrideConfig(BaseModel):
    name: str
    description: str = ""
    system_prompt: str
    task_prompt: str = ""
    include_citations: bool = True
    datetime_aware: bool = True


class PersonaOverrideConfig(BaseModel):
    name: str
    description: str
    search_type: SearchType = SearchType.SEMANTIC
    num_chunks: float | None = None
    llm_relevance_filter: bool = False
    llm_filter_extraction: bool = False
    recency_bias: RecencyBiasSetting = RecencyBiasSetting.AUTO
    llm_model_provider_override: str | None = None
    llm_model_version_override: str | None = None

    prompts: list[PromptOverrideConfig] = Field(default_factory=list)
    prompt_ids: list[int] = Field(default_factory=list)

    document_set_ids: list[int] = Field(default_factory=list)
    tools: list[ToolConfig] = Field(default_factory=list)
    tool_ids: list[int] = Field(default_factory=list)
    custom_tools_openapi: list[dict[str, Any]] = Field(default_factory=list)


AnswerQuestionPossibleReturn = (
    OnyxAnswerPiece
    | CitationInfo
    | OnyxContexts
    | FileChatDisplay
    | CustomToolResponse
    | StreamingError
    | StreamStopInfo
)


AnswerQuestionStreamReturn = Iterator[AnswerQuestionPossibleReturn]


class LLMMetricsContainer(BaseModel):
    prompt_tokens: int
    response_tokens: int


StreamProcessor = Callable[[Iterator[str]], AnswerQuestionStreamReturn]


class DocumentPruningConfig(BaseModel):
    max_chunks: int | None = None
    max_window_percentage: float | None = None
    max_tokens: int | None = None
    # different pruning behavior is expected when the
    # user manually selects documents they want to chat with
    # e.g. we don't want to truncate each document to be no more
    # than one chunk long
    is_manually_selected_docs: bool = False
    # If user specifies to include additional context Chunks for each match, then different pruning
    # is used. As many Sections as possible are included, and the last Section is truncated
    # If this is false, all of the Sections are truncated if they are longer than the expected Chunk size.
    # Sections are often expected to be longer than the maximum Chunk size but Chunks should not be.
    use_sections: bool = True
    # If using tools, then we need to consider the tool length
    tool_num_tokens: int = 0
    # If using a tool message to represent the docs, then we have to JSON serialize
    # the document content, which adds to the token count.
    using_tool_message: bool = False


class ContextualPruningConfig(DocumentPruningConfig):
    num_chunk_multiple: int

    @classmethod
    def from_doc_pruning_config(
        cls, num_chunk_multiple: int, doc_pruning_config: DocumentPruningConfig
    ) -> "ContextualPruningConfig":
        return cls(num_chunk_multiple=num_chunk_multiple, **doc_pruning_config.dict())


class CitationConfig(BaseModel):
    all_docs_useful: bool = False


class QuotesConfig(BaseModel):
    pass


class AnswerStyleConfig(BaseModel):
    citation_config: CitationConfig | None = None
    quotes_config: QuotesConfig | None = None
    document_pruning_config: DocumentPruningConfig = Field(
        default_factory=DocumentPruningConfig
    )
    # forces the LLM to return a structured response, see
    # https://platform.openai.com/docs/guides/structured-outputs/introduction
    # right now, only used by the simple chat API
    structured_response_format: dict | None = None

    @model_validator(mode="after")
    def check_quotes_and_citation(self) -> "AnswerStyleConfig":
        if self.citation_config is None and self.quotes_config is None:
            raise ValueError(
                "One of `citation_config` or `quotes_config` must be provided"
            )

        if self.citation_config is not None and self.quotes_config is not None:
            raise ValueError(
                "Only one of `citation_config` or `quotes_config` must be provided"
            )

        return self


class PromptConfig(BaseModel):
    """Final representation of the Prompt configuration passed
    into the `Answer` object."""

    system_prompt: str
    task_prompt: str
    datetime_aware: bool
    include_citations: bool

    @classmethod
    def from_model(
        cls, model: "Prompt", prompt_override: PromptOverride | None = None
    ) -> "PromptConfig":
        override_system_prompt = (
            prompt_override.system_prompt if prompt_override else None
        )
        override_task_prompt = prompt_override.task_prompt if prompt_override else None

        return cls(
            system_prompt=override_system_prompt or model.system_prompt,
            task_prompt=override_task_prompt or model.task_prompt,
            datetime_aware=model.datetime_aware,
            include_citations=model.include_citations,
        )

    model_config = ConfigDict(frozen=True)


ResponsePart = (
    OnyxAnswerPiece
    | CitationInfo
    | ToolCallKickoff
    | ToolResponse
    | ToolCallFinalResult
    | StreamStopInfo
)
