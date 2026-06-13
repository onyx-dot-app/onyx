"""Incremental parser for the Onyx chat NDJSON stream.

Vendored from backend/tests/integration/common_utils/managers/chat.py
(analyze_response) and backend/onyx/server/query_and_chat/streaming_models.py,
restructured to process one line at a time so milestone latencies can be
recorded the moment a packet arrives.

MUST stay stdlib-only: this module runs inside Locust under gevent
monkey-patching, where importing onyx.* (grpc, psycopg, etc.) breaks.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from dataclasses import field

# Packet type strings (subset of StreamingType in
# backend/onyx/server/query_and_chat/streaming_models.py — keep in sync).
MESSAGE_START = "message_start"
MESSAGE_DELTA = "message_delta"
SEARCH_TOOL_START = "search_tool_start"
SEARCH_TOOL_DOCUMENTS_DELTA = "search_tool_documents_delta"
DEEP_RESEARCH_PLAN_START = "deep_research_plan_start"
RESEARCH_AGENT_START = "research_agent_start"
STOP = "stop"
ERROR = "error"
CHAT_HEARTBEAT = "chat_heartbeat"

# Milestone names — these become Locust pseudo-request names.
FIRST_PACKET = "first_packet"
FIRST_SEARCH_DOC = "first_search_doc"
FIRST_ANSWER_TOKEN = "first_answer_token"
FIRST_DR_PLAN = "first_dr_plan"
FIRST_RESEARCH_AGENT = "first_research_agent"


@dataclass
class StreamSummary:
    packets: int = 0
    heartbeats: int = 0
    answer_chars: int = 0
    search_doc_count: int = 0
    saw_message_start: bool = False
    saw_stop: bool = False
    error: str | None = None
    milestones_hit: set[str] = field(default_factory=set)
    # Assistant message id reserved by the backend for this turn (top-level
    # stream field, not inside `obj`). Multi-turn scenarios chain the next
    # turn's parent_message_id from it.
    reserved_assistant_message_id: int | None = None


class ChatStreamAnalyzer:
    """Feed NDJSON lines one at a time; returns milestone names newly hit.

    The caller owns the clock — call feed() immediately after each line is
    received and timestamp any returned milestones.
    """

    def __init__(self) -> None:
        self.summary = StreamSummary()

    def feed(self, line: str) -> list[str]:
        if not line:
            return []

        hit: list[str] = []
        self.summary.packets += 1
        self._mark(FIRST_PACKET, hit)

        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            self.summary.error = f"unparseable stream line: {line[:200]}"
            return hit

        if not isinstance(data, dict):
            return hit

        # Reserved id rides at the top level of an early packet, alongside
        # (not inside) obj — capture it before the obj dispatch below.
        reserved_id = data.get("reserved_assistant_message_id")
        if isinstance(reserved_id, int):
            self.summary.reserved_assistant_message_id = reserved_id

        if data.get("error"):
            self.summary.error = str(data["error"])
            return hit

        obj = data.get("obj")
        if not isinstance(obj, dict):
            return hit

        packet_type = obj.get("type")
        if packet_type == ERROR or obj.get("error"):
            self.summary.error = str(obj.get("error") or "streaming error packet")
        elif packet_type == CHAT_HEARTBEAT:
            self.summary.heartbeats += 1
        elif packet_type == MESSAGE_START:
            self.summary.saw_message_start = True
            content = obj.get("content") or ""
            self.summary.answer_chars += len(content)
            if content:
                self._mark(FIRST_ANSWER_TOKEN, hit)
        elif packet_type == MESSAGE_DELTA:
            content = obj.get("content") or ""
            self.summary.answer_chars += len(content)
            if content:
                self._mark(FIRST_ANSWER_TOKEN, hit)
        elif packet_type == SEARCH_TOOL_DOCUMENTS_DELTA:
            docs = obj.get("documents") or []
            self.summary.search_doc_count += len(docs)
            if docs:
                self._mark(FIRST_SEARCH_DOC, hit)
        elif packet_type == DEEP_RESEARCH_PLAN_START:
            self._mark(FIRST_DR_PLAN, hit)
        elif packet_type == RESEARCH_AGENT_START:
            self._mark(FIRST_RESEARCH_AGENT, hit)
        elif packet_type == STOP:
            self.summary.saw_stop = True

        return hit

    def _mark(self, milestone: str, hit: list[str]) -> None:
        if milestone not in self.summary.milestones_hit:
            self.summary.milestones_hit.add(milestone)
            hit.append(milestone)

    def completed_ok(self) -> bool:
        # saw_stop is required: a stream cut mid-answer (proxy timeout, OOM)
        # is a failure even if answer content already arrived.
        return (
            self.summary.error is None
            and self.summary.saw_message_start
            and self.summary.answer_chars > 0
            and self.summary.saw_stop
        )

    def failure_reason(self) -> str:
        if self.summary.error:
            return self.summary.error
        if not self.summary.saw_message_start or not self.summary.answer_chars:
            return (
                "stream ended without answer content "
                f"(packets={self.summary.packets}, saw_stop={self.summary.saw_stop})"
            )
        if not self.summary.saw_stop:
            return (
                "stream truncated: answer content arrived but no stop packet "
                f"(packets={self.summary.packets}, "
                f"answer_chars={self.summary.answer_chars})"
            )
        return "unknown failure"
