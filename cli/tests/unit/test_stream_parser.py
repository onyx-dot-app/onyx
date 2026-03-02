"""Tests for the NDJSON stream parser."""

import json

import pytest

from onyx_cli.models import (
    CitationEvent,
    DeepResearchPlanDeltaEvent,
    ErrorEvent,
    IntermediateReportDeltaEvent,
    MessageDeltaEvent,
    MessageIdEvent,
    MessageStartEvent,
    ReasoningDeltaEvent,
    ReasoningDoneEvent,
    ReasoningStartEvent,
    ResearchAgentStartEvent,
    SearchDocumentsEvent,
    SearchQueriesEvent,
    SearchStartEvent,
    SessionCreatedEvent,
    StopEvent,
    StreamEventType,
    ToolStartEvent,
    UnknownEvent,
)
from onyx_cli.stream_parser import parse_stream_line


class TestParseStreamLine:
    """Tests for parse_stream_line function."""

    def test_empty_line_returns_none(self) -> None:
        assert parse_stream_line("") is None
        assert parse_stream_line("  ") is None
        assert parse_stream_line("\n") is None

    def test_invalid_json_returns_none(self) -> None:
        assert parse_stream_line("not json") is None
        assert parse_stream_line("{broken") is None

    # ── Session Lifecycle ────────────────────────────────────────────

    def test_session_created(self) -> None:
        line = json.dumps({"chat_session_id": "550e8400-e29b-41d4-a716-446655440000"})
        event = parse_stream_line(line)
        assert isinstance(event, SessionCreatedEvent)
        assert str(event.chat_session_id) == "550e8400-e29b-41d4-a716-446655440000"

    def test_message_id_info(self) -> None:
        line = json.dumps({"user_message_id": 1, "reserved_assistant_message_id": 2})
        event = parse_stream_line(line)
        assert isinstance(event, MessageIdEvent)
        assert event.user_message_id == 1
        assert event.reserved_assistant_message_id == 2

    def test_message_id_info_null_user_id(self) -> None:
        line = json.dumps({"user_message_id": None, "reserved_assistant_message_id": 5})
        event = parse_stream_line(line)
        assert isinstance(event, MessageIdEvent)
        assert event.user_message_id is None
        assert event.reserved_assistant_message_id == 5

    # ── Top-level Error ──────────────────────────────────────────────

    def test_top_level_error(self) -> None:
        line = json.dumps({"error": "Rate limit exceeded", "stack_trace": "...", "is_retryable": True})
        event = parse_stream_line(line)
        assert isinstance(event, ErrorEvent)
        assert event.error == "Rate limit exceeded"
        assert event.stack_trace == "..."
        assert event.is_retryable is True

    def test_top_level_error_minimal(self) -> None:
        line = json.dumps({"error": "Something broke"})
        event = parse_stream_line(line)
        assert isinstance(event, ErrorEvent)
        assert event.error == "Something broke"
        assert event.is_retryable is True  # default

    # ── Packet: Control ──────────────────────────────────────────────

    def _make_packet(self, obj: dict, turn_index: int = 0, tab_index: int = 0) -> str:
        return json.dumps({
            "placement": {"turn_index": turn_index, "tab_index": tab_index},
            "obj": obj,
        })

    def test_stop_packet(self) -> None:
        line = self._make_packet({"type": "stop", "stop_reason": "completed"})
        event = parse_stream_line(line)
        assert isinstance(event, StopEvent)
        assert event.stop_reason == "completed"
        assert event.placement is not None
        assert event.placement.turn_index == 0

    def test_stop_packet_no_reason(self) -> None:
        line = self._make_packet({"type": "stop"})
        event = parse_stream_line(line)
        assert isinstance(event, StopEvent)
        assert event.stop_reason is None

    # ── Packet: Answer ───────────────────────────────────────────────

    def test_message_start(self) -> None:
        line = self._make_packet({"type": "message_start"})
        event = parse_stream_line(line)
        assert isinstance(event, MessageStartEvent)
        assert event.documents is None

    def test_message_start_with_documents(self) -> None:
        line = self._make_packet({
            "type": "message_start",
            "final_documents": [
                {"document_id": "doc1", "semantic_identifier": "Doc 1"},
            ],
        })
        event = parse_stream_line(line)
        assert isinstance(event, MessageStartEvent)
        assert event.documents is not None
        assert len(event.documents) == 1
        assert event.documents[0].document_id == "doc1"

    def test_message_delta(self) -> None:
        line = self._make_packet({"type": "message_delta", "content": "Hello"})
        event = parse_stream_line(line)
        assert isinstance(event, MessageDeltaEvent)
        assert event.content == "Hello"

    def test_message_delta_empty(self) -> None:
        line = self._make_packet({"type": "message_delta", "content": ""})
        event = parse_stream_line(line)
        assert isinstance(event, MessageDeltaEvent)
        assert event.content == ""

    # ── Packet: Search ───────────────────────────────────────────────

    def test_search_tool_start(self) -> None:
        line = self._make_packet({"type": "search_tool_start", "is_internet_search": True})
        event = parse_stream_line(line)
        assert isinstance(event, SearchStartEvent)
        assert event.is_internet_search is True

    def test_search_tool_queries(self) -> None:
        line = self._make_packet({
            "type": "search_tool_queries_delta",
            "queries": ["query 1", "query 2"],
        })
        event = parse_stream_line(line)
        assert isinstance(event, SearchQueriesEvent)
        assert event.queries == ["query 1", "query 2"]

    def test_search_tool_documents(self) -> None:
        line = self._make_packet({
            "type": "search_tool_documents_delta",
            "documents": [
                {"document_id": "d1", "semantic_identifier": "First Doc", "link": "http://example.com"},
                {"document_id": "d2", "semantic_identifier": "Second Doc"},
            ],
        })
        event = parse_stream_line(line)
        assert isinstance(event, SearchDocumentsEvent)
        assert len(event.documents) == 2
        assert event.documents[0].link == "http://example.com"

    # ── Packet: Reasoning ────────────────────────────────────────────

    def test_reasoning_start(self) -> None:
        line = self._make_packet({"type": "reasoning_start"})
        event = parse_stream_line(line)
        assert isinstance(event, ReasoningStartEvent)

    def test_reasoning_delta(self) -> None:
        line = self._make_packet({"type": "reasoning_delta", "reasoning": "Let me think..."})
        event = parse_stream_line(line)
        assert isinstance(event, ReasoningDeltaEvent)
        assert event.reasoning == "Let me think..."

    def test_reasoning_done(self) -> None:
        line = self._make_packet({"type": "reasoning_done"})
        event = parse_stream_line(line)
        assert isinstance(event, ReasoningDoneEvent)

    # ── Packet: Citations ────────────────────────────────────────────

    def test_citation_info(self) -> None:
        line = self._make_packet({
            "type": "citation_info",
            "citation_number": 1,
            "document_id": "doc_abc",
        })
        event = parse_stream_line(line)
        assert isinstance(event, CitationEvent)
        assert event.citation_number == 1
        assert event.document_id == "doc_abc"

    # ── Packet: Tool Starts ──────────────────────────────────────────

    def test_open_url_start(self) -> None:
        line = self._make_packet({"type": "open_url_start"})
        event = parse_stream_line(line)
        assert isinstance(event, ToolStartEvent)
        assert event.event_type == StreamEventType.OPEN_URL_START

    def test_python_tool_start(self) -> None:
        line = self._make_packet({"type": "python_tool_start", "code": "print('hi')"})
        event = parse_stream_line(line)
        assert isinstance(event, ToolStartEvent)
        assert "Python" in event.tool_name

    def test_custom_tool_start(self) -> None:
        line = self._make_packet({"type": "custom_tool_start", "tool_name": "MyTool"})
        event = parse_stream_line(line)
        assert isinstance(event, ToolStartEvent)
        assert event.tool_name == "MyTool"

    # ── Packet: Deep Research ────────────────────────────────────────

    def test_deep_research_plan_delta(self) -> None:
        line = self._make_packet({"type": "deep_research_plan_delta", "content": "Step 1: ..."})
        event = parse_stream_line(line)
        assert isinstance(event, DeepResearchPlanDeltaEvent)
        assert event.content == "Step 1: ..."

    def test_research_agent_start(self) -> None:
        line = self._make_packet({"type": "research_agent_start", "research_task": "Find info about X"})
        event = parse_stream_line(line)
        assert isinstance(event, ResearchAgentStartEvent)
        assert event.research_task == "Find info about X"

    def test_intermediate_report_delta(self) -> None:
        line = self._make_packet({"type": "intermediate_report_delta", "content": "Report text"})
        event = parse_stream_line(line)
        assert isinstance(event, IntermediateReportDeltaEvent)
        assert event.content == "Report text"

    # ── Packet: Unknown ──────────────────────────────────────────────

    def test_unknown_packet_type(self) -> None:
        line = self._make_packet({"type": "section_end"})
        event = parse_stream_line(line)
        assert isinstance(event, UnknownEvent)

    def test_unknown_top_level(self) -> None:
        line = json.dumps({"some_unknown_field": "value"})
        event = parse_stream_line(line)
        assert isinstance(event, UnknownEvent)

    # ── Placement Preservation ───────────────────────────────────────

    def test_placement_preserved(self) -> None:
        line = self._make_packet({"type": "message_delta", "content": "x"}, turn_index=3, tab_index=1)
        event = parse_stream_line(line)
        assert isinstance(event, MessageDeltaEvent)
        assert event.placement is not None
        assert event.placement.turn_index == 3
        assert event.placement.tab_index == 1
