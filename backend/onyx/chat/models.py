from collections.abc import Callable
from collections.abc import Iterator
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel
from pydantic import Field

from onyx.configs.constants import DocumentSource
from onyx.configs.constants import MessageType
from onyx.context.search.enums import QueryFlow
from onyx.context.search.enums import RecencyBiasSetting
from onyx.context.search.enums import SearchType
from onyx.context.search.models import SearchDoc
from onyx.file_store.models import FileDescriptor
from onyx.file_store.models import InMemoryChatFile
from onyx.server.query_and_chat.streaming_models import CitationInfo
from onyx.server.query_and_chat.streaming_models import GeneratedImage
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.tools.models import SearchToolUsage
from onyx.tools.models import ToolCallKickoff
from onyx.tools.tool_implementations.custom.base_tool_types import ToolResultType


# First chunk of info for streaming QA
class QADocsResponse(BaseModel):
    top_documents: list[SearchDoc]
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
    FINISHED = "finished"


class StreamType(Enum):
    SUB_QUESTIONS = "sub_questions"
    SUB_ANSWER = "sub_answer"
    MAIN_ANSWER = "main_answer"


class StreamStopInfo(BaseModel):
    stop_reason: StreamStopReason

    stream_type: StreamType = StreamType.MAIN_ANSWER

    def model_dump(self, *args: list, **kwargs: dict[str, Any]) -> dict[str, Any]:  # type: ignore
        data = super().model_dump(mode="json", *args, **kwargs)  # type: ignore
        data["stop_reason"] = self.stop_reason.name
        return data


class UserKnowledgeFilePacket(BaseModel):
    user_files: list[FileDescriptor]


class LLMRelevanceFilterResponse(BaseModel):
    llm_selected_doc_indices: list[int]


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


class MessageResponseIDInfo(BaseModel):
    user_message_id: int | None
    reserved_assistant_message_id: int


class StreamingError(BaseModel):
    error: str
    stack_trace: str | None = None
    error_code: str | None = (
        None  # e.g., "RATE_LIMIT", "AUTH_ERROR", "TOOL_CALL_FAILED"
    )
    is_retryable: bool = True  # Hint to frontend if retry might help
    details: dict | None = None  # Additional context (tool name, model name, etc.)


class OnyxAnswer(BaseModel):
    answer: str | None


class ThreadMessage(BaseModel):
    message: str
    sender: str | None = None
    role: MessageType = MessageType.USER


class FileChatDisplay(BaseModel):
    file_ids: list[str]


class CustomToolResponse(BaseModel):
    response: ToolResultType
    tool_name: str


class ToolConfig(BaseModel):
    id: int


class ProjectSearchConfig(BaseModel):
    """Configuration for search tool availability in project context."""

    search_usage: SearchToolUsage
    disable_forced_tool: bool


class PromptOverrideConfig(BaseModel):
    name: str
    description: str = ""
    system_prompt: str
    task_prompt: str = ""
    datetime_aware: bool = True
    include_citations: bool = True


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
    # Note: prompt_ids removed - prompts are now embedded in personas

    document_set_ids: list[int] = Field(default_factory=list)
    tools: list[ToolConfig] = Field(default_factory=list)
    tool_ids: list[int] = Field(default_factory=list)
    custom_tools_openapi: list[dict[str, Any]] = Field(default_factory=list)


AnswerQuestionPossibleReturn = (
    OnyxAnswerPiece
    | CitationInfo
    | FileChatDisplay
    | CustomToolResponse
    | StreamingError
    | StreamStopInfo
)


class CreateChatSessionID(BaseModel):
    chat_session_id: UUID


AnswerQuestionStreamReturn = Iterator[AnswerQuestionPossibleReturn]


class LLMMetricsContainer(BaseModel):
    prompt_tokens: int
    response_tokens: int


StreamProcessor = Callable[[Iterator[str]], AnswerQuestionStreamReturn]


AnswerStreamPart = (
    Packet
    | StreamStopInfo
    | MessageResponseIDInfo
    | StreamingError
    | UserKnowledgeFilePacket
    | CreateChatSessionID
)

AnswerStream = Iterator[AnswerStreamPart]


class ChatBasicResponse(BaseModel):
    # This is built piece by piece, any of these can be None as the flow could break
    answer: str
    answer_citationless: str

    top_documents: list[SearchDoc]

    error_msg: str | None
    message_id: int
    citation_info: list[CitationInfo]


class ToolCallResponse(BaseModel):
    """Tool call with full details for non-streaming response."""

    tool_name: str
    tool_arguments: dict[str, Any]
    tool_result: str
    search_docs: list[SearchDoc] | None = None
    generated_images: list[GeneratedImage] | None = None
    # Reasoning that led to the tool call
    pre_reasoning: str | None = None


class ChatFullResponse(BaseModel):
    """Complete non-streaming response with all available data."""

    # Core response fields
    answer: str
    answer_citationless: str
    pre_answer_reasoning: str | None = None
    tool_calls: list[ToolCallResponse] = []

    # Documents & citations
    top_documents: list[SearchDoc]
    citation_info: list[CitationInfo]

    # Metadata
    message_id: int
    chat_session_id: UUID | None = None
    error_msg: str | None = None


class ChatLoadedFile(InMemoryChatFile):
    content_text: str | None
    token_count: int


class ChatMessageSimple(BaseModel):
    message: str
    token_count: int
    message_type: MessageType
    # Only for USER type messages
    image_files: list[ChatLoadedFile] | None = None
    # Only for TOOL_CALL_RESPONSE type messages
    tool_call_id: str | None = None
    # The last message for which this is true
    # AND is true for all previous messages
    # (counting from the start of the history)
    # represents the end of the cacheable prefix
    # used for prompt caching
    should_cache: bool = False


class ProjectFileMetadata(BaseModel):
    """Metadata for a project file to enable citation support."""

    file_id: str
    filename: str
    file_content: str


class ExtractedProjectFiles(BaseModel):
    project_file_texts: list[str]
    project_image_files: list[ChatLoadedFile]
    project_as_filter: bool
    total_token_count: int
    # Metadata for project files to enable citations
    project_file_metadata: list[ProjectFileMetadata]
    # None if not a project
    project_uncapped_token_count: int | None


class LlmStepResult(BaseModel):
    reasoning: str | None
    answer: str | None
    tool_calls: list[ToolCallKickoff] | None
