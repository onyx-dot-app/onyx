"""Measure chat stream milestones without importing backend dependencies.

Keep this module stdlib-only: Locust runs it under gevent monkey-patching.
"""

import json
from dataclasses import dataclass, field
from typing import Literal, TypedDict, cast

FIRST_PACKET = "first_packet"
FIRST_SEARCH_DOC = "first_search_doc"
FIRST_ANSWER_TOKEN = "first_answer_token"
FIRST_DR_PLAN = "first_dr_plan"
FIRST_RESEARCH_AGENT = "first_research_agent"


class _Identity(TypedDict):
    response_id: int
    message_id: str
    tool_call_id: str | None
    part_id: str
    parent_run_id: str | None


class _Document(TypedDict):
    document_id: str


class _Metadata(TypedDict, total=False):
    type: str
    search_docs: list[_Document]
    displayed_docs: list[_Document] | None


class _Item(TypedDict, total=False):
    kind: Literal["text", "reasoning", "tool"]
    text: str
    purpose: Literal["answer", "plan", "report", "commentary"]
    name: str
    metadata: _Metadata | None


class _Delta(TypedDict, total=False):
    kind: Literal["text", "tool_arguments", "tool_output"]
    text: str
    metadata: _Metadata | None


class _Body(TypedDict, total=False):
    type: Literal["item_update", "item_delta", "run_update", "stop", "chat_heartbeat"]
    item: _Item
    delta: _Delta
    status: Literal["running", "complete", "limit", "cancelled", "error"]


class _Packet(TypedDict, total=False):
    identity: _Identity | None
    obj: _Body
    error: str | None
    reserved_assistant_message_id: int


@dataclass
class StreamSummary:
    packets: int = 0
    heartbeats: int = 0
    answer_chars: int = 0
    search_doc_count: int = 0
    saw_stop: bool = False
    error: str | None = None
    milestones_hit: set[str] = field(default_factory=set)
    reserved_assistant_message_id: int | None = None


class ChatStreamAnalyzer:
    """Track current items and return newly reached milestones for the caller's clock."""

    def __init__(self) -> None:
        self.summary = StreamSummary()
        self._items: dict[tuple[int, str, str | None, str], _Item] = {}
        self._root_items: set[tuple[int, str, str | None, str]] = set()

    def feed(self, line: str) -> list[str]:
        if not line:
            return []
        hit: list[str] = []
        self.summary.packets += 1
        self._mark(FIRST_PACKET, hit)
        try:
            # json.loads is untyped; these are the fields consumed from the server protocol.
            data = cast(_Packet, json.loads(line))
        except json.JSONDecodeError:
            self.summary.error = "unparseable stream line"
            return hit
        if not isinstance(data, dict):
            self.summary.error = "stream packet must be a JSON object"
            return hit
        reserved_id = data.get("reserved_assistant_message_id")
        if reserved_id is not None:
            self.summary.reserved_assistant_message_id = reserved_id
        if error := data.get("error"):
            self.summary.error = error
            return hit
        obj = data.get("obj")
        if obj is None:
            return hit
        packet_type = obj["type"]
        if packet_type == "chat_heartbeat":
            self.summary.heartbeats += 1
        elif packet_type == "stop":
            self.summary.saw_stop = True
        elif packet_type in {"item_update", "item_delta"}:
            identity = data.get("identity")
            if identity is None:
                self.summary.error = "content packet has no identity"
                return hit
            key = (
                identity["response_id"],
                identity["message_id"],
                identity.get("tool_call_id"),
                identity["part_id"],
            )
            if identity.get("parent_run_id") is None:
                self._root_items.add(key)
            if packet_type == "item_update":
                self._items[key] = obj["item"]
            else:
                item = self._items.get(key)
                if item is None:
                    self.summary.error = "delta has no initial item"
                    return hit
                delta = obj["delta"]
                if delta["kind"] == "text":
                    item["text"] = item.get("text", "") + delta["text"]
                elif (
                    delta["kind"] == "tool_output" and delta.get("metadata") is not None
                ):
                    item["metadata"] = delta["metadata"]
            self._update_summary(hit)
        elif packet_type == "run_update":
            identity = data.get("identity")
            if (
                identity
                and identity.get("parent_run_id") is None
                and obj.get("status") in {"error", "cancelled"}
            ):
                self.summary.error = f"run {obj['status']}"
        return hit

    def _update_summary(self, hit: list[str]) -> None:
        self.summary.answer_chars = 0
        self.summary.search_doc_count = 0
        for key, item in self._items.items():
            if item["kind"] == "text":
                if item.get("purpose") == "plan":
                    self._mark(FIRST_DR_PLAN, hit)
                if item.get("purpose") == "answer" and key in self._root_items:
                    self.summary.answer_chars += len(item.get("text", ""))
            elif item["kind"] == "tool":
                if item.get("name") == "research_agent":
                    self._mark(FIRST_RESEARCH_AGENT, hit)
                metadata = item.get("metadata")
                if metadata and metadata.get("type") == "search_result":
                    displayed = metadata.get("displayed_docs")
                    docs = (
                        displayed
                        if displayed is not None
                        else metadata.get("search_docs", [])
                    )
                    self.summary.search_doc_count += len(docs)
        if self.summary.answer_chars:
            self._mark(FIRST_ANSWER_TOKEN, hit)
        if self.summary.search_doc_count:
            self._mark(FIRST_SEARCH_DOC, hit)

    def _mark(self, milestone: str, hit: list[str]) -> None:
        if milestone not in self.summary.milestones_hit:
            self.summary.milestones_hit.add(milestone)
            hit.append(milestone)

    def completed_ok(self) -> bool:
        # A connection cut after partial text is still a failed request.
        return (
            self.summary.error is None
            and self.summary.answer_chars > 0
            and self.summary.saw_stop
        )

    def failure_reason(self) -> str:
        if self.summary.error:
            return self.summary.error
        if not self.summary.answer_chars:
            return f"stream ended without answer content (packets={self.summary.packets}, saw_stop={self.summary.saw_stop})"
        if not self.summary.saw_stop:
            return f"stream truncated: answer content arrived but no stop packet (packets={self.summary.packets}, answer_chars={self.summary.answer_chars})"
        return "unknown failure"
