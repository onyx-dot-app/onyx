from collections.abc import Iterator
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from onyx.context.search.models import SearchDoc
from onyx.file_store.models import FileToolMetadata
from onyx.llm.models import Message
from onyx.server.query_and_chat.models import (
    MessageResponseIDInfo,
    MultiModelMessageResponseIDInfo,
)
from onyx.server.query_and_chat.streaming_models import (
    CitationInfo,
    GeneratedImage,
    Packet,
)
from onyx.tools.models import SearchToolUsage
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


class CreateChatSessionID(BaseModel):
    chat_session_id: UUID
    # Echoes the pinned mode so the client can verify the server honored an
    # incognito request. A server that omits it did not.
    incognito: bool = False


AnswerStreamPart = (
    Packet
    | MessageResponseIDInfo
    | MultiModelMessageResponseIDInfo
    | StreamingError
    | CreateChatSessionID
)

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
    # Echoes the pinned mode for newly-created sessions, like the streaming
    # packet does. A server that omits it did not honor an incognito request.
    incognito: bool = False
    error_msg: str | None = None


class SearchParams(BaseModel):
    """Resolved search filter IDs and search-tool usage for a chat turn."""

    project_id_filter: int | None
    persona_id_filter: int | None
    search_usage: SearchToolUsage


class ChatHistoryResult(BaseModel):
    """Result of converting chat history to simple format.

    Bundles the simple messages with metadata for every text file that was
    injected into the history. After context-window truncation drops older
    messages, callers compare surviving ``file_id`` tags against this map
    to discover "forgotten" files whose metadata should be provided to the
    FileReaderTool.
    """

    messages: list[Message]
    all_injected_file_metadata: dict[str, FileToolMetadata]
