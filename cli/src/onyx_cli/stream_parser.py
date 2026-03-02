"""NDJSON stream parser for Onyx chat streaming responses.

Each line in the stream is one of:
  - A Packet: {"placement": {...}, "obj": {"type": "...", ...}}
  - A CreateChatSessionID: {"chat_session_id": "uuid"}
  - A MessageResponseIDInfo: {"user_message_id": N, "reserved_assistant_message_id": N}
  - A StreamingError: {"error": "...", ...}
"""

from __future__ import annotations

import json
from typing import Any

from onyx_cli.models import (
    CitationEvent,
    DeepResearchPlanDeltaEvent,
    ErrorEvent,
    IntermediateReportDeltaEvent,
    MessageDeltaEvent,
    MessageIdEvent,
    MessageStartEvent,
    Placement,
    ReasoningDeltaEvent,
    ReasoningDoneEvent,
    ReasoningStartEvent,
    ResearchAgentStartEvent,
    SearchDoc,
    SearchDocumentsEvent,
    SearchQueriesEvent,
    SearchStartEvent,
    SessionCreatedEvent,
    StopEvent,
    StreamEvent,
    StreamEventType,
    ToolStartEvent,
    UnknownEvent,
)


def parse_stream_line(line: str) -> StreamEvent | None:
    """Parse a single NDJSON line into a typed StreamEvent.

    Returns None for empty lines or unparseable content.
    """
    line = line.strip()
    if not line:
        return None

    try:
        data: dict[str, Any] = json.loads(line)
    except json.JSONDecodeError:
        return None

    # Case 1: CreateChatSessionID
    if "chat_session_id" in data and "placement" not in data:
        return SessionCreatedEvent(chat_session_id=data["chat_session_id"])

    # Case 2: MessageResponseIDInfo
    if "reserved_assistant_message_id" in data:
        return MessageIdEvent(
            user_message_id=data.get("user_message_id"),
            reserved_assistant_message_id=data["reserved_assistant_message_id"],
        )

    # Case 3: StreamingError (top-level error without placement)
    if "error" in data and "placement" not in data:
        return ErrorEvent(
            error=data["error"],
            stack_trace=data.get("stack_trace"),
            is_retryable=data.get("is_retryable", True),
        )

    # Case 4: Packet with placement + obj
    if "placement" in data and "obj" in data:
        placement = Placement(**data["placement"])
        obj = data["obj"]
        obj_type = obj.get("type", "")
        return _parse_packet_obj(obj_type, obj, placement)

    # Fallback
    return UnknownEvent(raw_data=data)


def _parse_packet_obj(obj_type: str, obj: dict[str, Any], placement: Placement) -> StreamEvent:
    """Dispatch on obj.type to create the appropriate StreamEvent."""

    match obj_type:
        # Control
        case "stop":
            return StopEvent(placement=placement, stop_reason=obj.get("stop_reason"))

        case "error":
            return ErrorEvent(
                placement=placement,
                error=str(obj.get("exception", "Unknown error")),
            )

        # Answer
        case "message_start":
            docs = None
            if raw_docs := obj.get("final_documents"):
                docs = [SearchDoc(**d) if isinstance(d, dict) else d for d in raw_docs]
            return MessageStartEvent(placement=placement, documents=docs)

        case "message_delta":
            return MessageDeltaEvent(placement=placement, content=obj.get("content", ""))

        # Search
        case "search_tool_start":
            return SearchStartEvent(
                placement=placement,
                is_internet_search=obj.get("is_internet_search", False),
            )

        case "search_tool_queries_delta":
            return SearchQueriesEvent(placement=placement, queries=obj.get("queries", []))

        case "search_tool_documents_delta":
            raw_docs = obj.get("documents", [])
            docs = [SearchDoc(**d) if isinstance(d, dict) else d for d in raw_docs]
            return SearchDocumentsEvent(placement=placement, documents=docs)

        # Reasoning
        case "reasoning_start":
            return ReasoningStartEvent(placement=placement)

        case "reasoning_delta":
            return ReasoningDeltaEvent(placement=placement, reasoning=obj.get("reasoning", ""))

        case "reasoning_done":
            return ReasoningDoneEvent(placement=placement)

        # Citations
        case "citation_info":
            return CitationEvent(
                placement=placement,
                citation_number=obj.get("citation_number", 0),
                document_id=obj.get("document_id", ""),
            )

        # Tool starts (show minimal info in TUI)
        case "open_url_start" | "image_generation_start" | "python_tool_start" | "file_reader_start":
            return ToolStartEvent(
                event_type=StreamEventType(obj_type),
                placement=placement,
                tool_name=obj_type.replace("_start", "").replace("_", " ").title(),
            )

        case "custom_tool_start":
            return ToolStartEvent(
                event_type=StreamEventType.CUSTOM_TOOL_START,
                placement=placement,
                tool_name=obj.get("tool_name", "Custom Tool"),
            )

        # Deep research
        case "deep_research_plan_start":
            return StreamEvent(event_type=StreamEventType.DEEP_RESEARCH_PLAN_START, placement=placement)

        case "deep_research_plan_delta":
            return DeepResearchPlanDeltaEvent(placement=placement, content=obj.get("content", ""))

        case "research_agent_start":
            return ResearchAgentStartEvent(placement=placement, research_task=obj.get("research_task", ""))

        case "intermediate_report_start":
            return StreamEvent(event_type=StreamEventType.INTERMEDIATE_REPORT_START, placement=placement)

        case "intermediate_report_delta":
            return IntermediateReportDeltaEvent(placement=placement, content=obj.get("content", ""))

        # Everything else (section_end, heartbeats, memory, etc.)
        case _:
            return UnknownEvent(event_type=StreamEventType.UNKNOWN, placement=placement, raw_data=obj)
