from collections.abc import Iterator
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from onyx.configs.constants import MessageType
from onyx.context.search.models import SearchDoc
from onyx.file_store.models import InMemoryChatFile
from onyx.server.query_and_chat.models import MessageResponseIDInfo
from onyx.server.query_and_chat.streaming_models import CitationInfo
from onyx.server.query_and_chat.streaming_models import GeneratedImage
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.tools.models import SearchToolUsage
from onyx.tools.models import ToolCallKickoff
from onyx.tools.tool_implementations.custom.base_tool_types import ToolResultType


class StreamingError(BaseModel):
    error: str
    stack_trace: str | None = None
    error_code: str | None = (
        None  # e.g., "RATE_LIMIT", "AUTH_ERROR", "TOOL_CALL_FAILED"
    )
    is_retryable: bool = True  # Hint to frontend if retry might help
    details: dict | None = None  # Additional context (tool name, model name, etc.)


class CustomToolResponse(BaseModel):
    response: ToolResultType
    tool_name: str


class ProjectSearchConfig(BaseModel):
    """Configuration for search tool availability in project context."""

    search_usage: SearchToolUsage
    disable_forced_tool: bool


class CreateChatSessionID(BaseModel):
    chat_session_id: UUID


AnswerStreamPart = Packet | MessageResponseIDInfo | StreamingError | CreateChatSessionID

AnswerStream = Iterator[AnswerStreamPart]


class ToolCallResponse(BaseModel):
    """Tool call with full details for non-streaming response."""

    tool_name: str
    tool_arguments: dict[str, Any]
    tool_result: str
    search_docs: list[SearchDoc] | None = None
    generated_images: list[GeneratedImage] | None = None
    # Reasoning that led to the tool call
    pre_reasoning: str | None = None


class ChatBasicResponse(BaseModel):
    # This is built piece by piece, any of these can be None as the flow could break
    answer: str
    answer_citationless: str

    top_documents: list[SearchDoc]

    error_msg: str | None
    message_id: int
    citation_info: list[CitationInfo]


class ChatFullResponse(BaseModel):
    """Complete non-streaming response with all available data.
    NOTE: This model is used for the core flow of the Onyx application, any changes to it should be reviewed and approved by an
    experienced team member. It is very important to 1. avoid bloat and 2. that this remains backwards compatible across versions.
    """

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


class ToolCallSimple(BaseModel):
    """Tool call for ChatMessageSimple representation (mirrors OpenAI format).

    Used when an ASSISTANT message contains one or more tool calls.
    Each tool call has an ID, name, arguments, and token count for tracking.
    """

    tool_call_id: str
    tool_name: str
    tool_arguments: dict[str, Any]
    token_count: int = 0


class ChatMessageSimple(BaseModel):
    message: str
    token_count: int
    message_type: MessageType
    # Only for USER type messages
    image_files: list[ChatLoadedFile] | None = None
    # Only for TOOL_CALL_RESPONSE type messages
    tool_call_id: str | None = None
    # For ASSISTANT messages with tool calls (OpenAI parallel tool calling format)
    tool_calls: list[ToolCallSimple] | None = None
    # The last message for which this is true
    # AND is true for all previous messages
    # (counting from the start of the history)
    # represents the end of the cacheable prefix
    # used for prompt caching
    should_cache: bool = False
    # When this message represents an injected text file, this is the file's ID.
    # Used to detect which file messages survive context-window truncation.
    file_id: str | None = None


class ProjectFileMetadata(BaseModel):
    """Metadata for a project file to enable citation support."""

    file_id: str
    filename: str
    file_content: str


class FileToolMetadata(BaseModel):
    """Lightweight metadata for exposing files to the FileReaderTool.

    Used when files cannot be loaded directly into context (project too large
    or persona-attached user_files without direct-load path). The LLM receives
    a listing of these so it knows which files it can read via ``read_file``.
    """

    file_id: str
    filename: str
    approx_char_count: int


class ChatHistoryResult(BaseModel):
    """Result of converting chat history to simple format.

    Bundles the simple messages with metadata for every text file that was
    injected into the history. After context-window truncation drops older
    messages, callers compare surviving ``file_id`` tags against this map
    to discover "forgotten" files whose metadata should be provided to the
    FileReaderTool.
    """

    simple_messages: list[ChatMessageSimple]
    all_injected_file_metadata: dict[str, FileToolMetadata]


class ExtractedProjectFiles(BaseModel):
    project_file_texts: list[str]
    project_image_files: list[ChatLoadedFile]
    project_as_filter: bool
    total_token_count: int
    # Metadata for project files to enable citations
    project_file_metadata: list[ProjectFileMetadata]
    # None if not a project
    project_uncapped_token_count: int | None
    # Lightweight metadata for files exposed via FileReaderTool
    # (populated when files don't fit in context and vector DB is disabled)
    file_metadata_for_tool: list[FileToolMetadata] = []


class LlmStepResult(BaseModel):
    reasoning: str | None
    answer: str | None
    tool_calls: list[ToolCallKickoff] | None
    # Raw LLM text before any display-oriented filtering/sanitization.
    # Used for fallback tool-call extraction when providers emit calls as text.
    raw_answer: str | None = None
