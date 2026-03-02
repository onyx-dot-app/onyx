"""Standalone Pydantic models for the Onyx CLI.

These mirror backend types but are fully self-contained with no backend imports.
Only fields the CLI actually needs are included.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel


# ── Persona / Assistant ──────────────────────────────────────────────


class PersonaSummary(BaseModel):
    id: int
    name: str
    description: str
    is_default_persona: bool = False


# ── Chat Sessions ────────────────────────────────────────────────────


class ChatSessionSummary(BaseModel):
    id: UUID
    name: str | None = None
    persona_id: int | None = None
    time_created: datetime


class ChatSessionDetails(BaseModel):
    id: UUID
    name: str | None = None
    persona_id: int | None = None
    time_created: str
    time_updated: str


class ChatMessageDetail(BaseModel):
    message_id: int
    parent_message: int | None = None
    latest_child_message: int | None = None
    message: str
    message_type: str  # "user", "assistant", "system"
    time_sent: datetime
    error: str | None = None


class ChatSessionDetailResponse(BaseModel):
    chat_session_id: UUID
    description: str | None = None
    persona_id: int | None = None
    persona_name: str | None = None
    messages: list[ChatMessageDetail] = []


# ── File Upload ──────────────────────────────────────────────────────


class ChatFileType(str, Enum):
    IMAGE = "image"
    DOC = "document"
    PLAIN_TEXT = "plain_text"
    CSV = "csv"


class FileDescriptorPayload(BaseModel):
    """File descriptor to include in a send-message request."""

    id: str
    type: ChatFileType
    name: str | None = None


class UserFileSnapshot(BaseModel):
    id: UUID
    name: str
    file_id: str
    chat_file_type: ChatFileType


class CategorizedFilesSnapshot(BaseModel):
    user_files: list[UserFileSnapshot] = []


# ── Streaming Events ─────────────────────────────────────────────────


class Placement(BaseModel):
    turn_index: int
    tab_index: int = 0
    sub_turn_index: int | None = None


class StreamEventType(str, Enum):
    # Session lifecycle
    SESSION_CREATED = "session_created"
    MESSAGE_ID_INFO = "message_id_info"

    # Control
    STOP = "stop"
    ERROR = "error"

    # Answer
    MESSAGE_START = "message_start"
    MESSAGE_DELTA = "message_delta"

    # Search
    SEARCH_START = "search_tool_start"
    SEARCH_QUERIES = "search_tool_queries_delta"
    SEARCH_DOCUMENTS = "search_tool_documents_delta"

    # Reasoning
    REASONING_START = "reasoning_start"
    REASONING_DELTA = "reasoning_delta"
    REASONING_DONE = "reasoning_done"

    # Citations
    CITATION_INFO = "citation_info"

    # Tools (we show minimal info for these)
    OPEN_URL_START = "open_url_start"
    IMAGE_GENERATION_START = "image_generation_start"
    PYTHON_TOOL_START = "python_tool_start"
    CUSTOM_TOOL_START = "custom_tool_start"
    FILE_READER_START = "file_reader_start"

    # Deep research
    DEEP_RESEARCH_PLAN_START = "deep_research_plan_start"
    DEEP_RESEARCH_PLAN_DELTA = "deep_research_plan_delta"
    RESEARCH_AGENT_START = "research_agent_start"
    INTERMEDIATE_REPORT_START = "intermediate_report_start"
    INTERMEDIATE_REPORT_DELTA = "intermediate_report_delta"

    # Catch-all for packets we don't specifically handle
    UNKNOWN = "unknown"


class SearchDoc(BaseModel):
    document_id: str
    semantic_identifier: str = ""
    link: str | None = None
    source_type: str = ""


class StreamEvent(BaseModel):
    """Base class for all stream events."""

    event_type: StreamEventType
    placement: Placement | None = None


class SessionCreatedEvent(StreamEvent):
    event_type: StreamEventType = StreamEventType.SESSION_CREATED
    chat_session_id: UUID


class MessageIdEvent(StreamEvent):
    event_type: StreamEventType = StreamEventType.MESSAGE_ID_INFO
    user_message_id: int | None = None
    reserved_assistant_message_id: int


class StopEvent(StreamEvent):
    event_type: StreamEventType = StreamEventType.STOP
    stop_reason: str | None = None


class ErrorEvent(StreamEvent):
    event_type: StreamEventType = StreamEventType.ERROR
    error: str
    stack_trace: str | None = None
    is_retryable: bool = True


class MessageStartEvent(StreamEvent):
    event_type: StreamEventType = StreamEventType.MESSAGE_START
    documents: list[SearchDoc] | None = None


class MessageDeltaEvent(StreamEvent):
    event_type: StreamEventType = StreamEventType.MESSAGE_DELTA
    content: str


class SearchStartEvent(StreamEvent):
    event_type: StreamEventType = StreamEventType.SEARCH_START
    is_internet_search: bool = False


class SearchQueriesEvent(StreamEvent):
    event_type: StreamEventType = StreamEventType.SEARCH_QUERIES
    queries: list[str] = []


class SearchDocumentsEvent(StreamEvent):
    event_type: StreamEventType = StreamEventType.SEARCH_DOCUMENTS
    documents: list[SearchDoc] = []


class ReasoningStartEvent(StreamEvent):
    event_type: StreamEventType = StreamEventType.REASONING_START


class ReasoningDeltaEvent(StreamEvent):
    event_type: StreamEventType = StreamEventType.REASONING_DELTA
    reasoning: str


class ReasoningDoneEvent(StreamEvent):
    event_type: StreamEventType = StreamEventType.REASONING_DONE


class CitationEvent(StreamEvent):
    event_type: StreamEventType = StreamEventType.CITATION_INFO
    citation_number: int
    document_id: str


class ToolStartEvent(StreamEvent):
    """Generic tool start event for tools we show minimal info about."""

    tool_name: str = ""


class DeepResearchPlanDeltaEvent(StreamEvent):
    event_type: StreamEventType = StreamEventType.DEEP_RESEARCH_PLAN_DELTA
    content: str


class ResearchAgentStartEvent(StreamEvent):
    event_type: StreamEventType = StreamEventType.RESEARCH_AGENT_START
    research_task: str


class IntermediateReportDeltaEvent(StreamEvent):
    event_type: StreamEventType = StreamEventType.INTERMEDIATE_REPORT_DELTA
    content: str


class UnknownEvent(StreamEvent):
    event_type: StreamEventType = StreamEventType.UNKNOWN
    raw_data: dict[str, Any] = {}


# ── Send Message Request ─────────────────────────────────────────────


class ChatSessionCreationInfo(BaseModel):
    persona_id: int = 0


class SendMessagePayload(BaseModel):
    """Payload for POST /api/chat/send-chat-message."""

    message: str
    chat_session_id: str | None = None
    chat_session_info: ChatSessionCreationInfo | None = None
    parent_message_id: int | None = -1
    file_descriptors: list[dict[str, Any]] = []
    origin: str = "api"
    include_citations: bool = True
    stream: bool = True
