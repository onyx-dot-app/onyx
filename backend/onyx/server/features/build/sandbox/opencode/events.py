"""Typed event models for OpenCode streaming in Craft."""

from dataclasses import dataclass
from datetime import datetime
from datetime import timezone
from typing import Any
from typing import Literal

from pydantic import BaseModel
from pydantic import Field


def utc_now_iso() -> str:
    """Return current UTC time in ISO format."""
    return datetime.now(tz=timezone.utc).isoformat()


def timestamp_ms_to_iso(timestamp_ms: int | float | None) -> str:
    """Convert millisecond epoch timestamp to UTC ISO string."""
    if timestamp_ms is None:
        return utc_now_iso()
    try:
        return datetime.fromtimestamp(
            float(timestamp_ms) / 1000.0, tz=timezone.utc
        ).isoformat()
    except (TypeError, ValueError, OSError):
        return utc_now_iso()


class OpenCodeTextContent(BaseModel):
    """Text content block used by streamed text/reasoning packets."""

    type: Literal["text"] = "text"
    text: str


class OpenCodeAgentMessageChunk(BaseModel):
    """Assistant text chunk event."""

    type: Literal["agent_message_chunk"] = "agent_message_chunk"
    opencode_session_id: str | None = None
    content: OpenCodeTextContent
    timestamp: str = Field(default_factory=utc_now_iso)


class OpenCodeAgentThoughtChunk(BaseModel):
    """Assistant reasoning/thought chunk event."""

    type: Literal["agent_thought_chunk"] = "agent_thought_chunk"
    opencode_session_id: str | None = None
    content: OpenCodeTextContent
    timestamp: str = Field(default_factory=utc_now_iso)


class OpenCodeToolCallBase(BaseModel):
    """Shared fields for synthesized tool call packets."""

    opencode_session_id: str | None = None
    tool_call_id: str
    tool_name: str
    kind: str | None = None
    title: str | None = None
    content: list[dict[str, Any]] | None = None
    locations: list[str] | None = None
    raw_input: dict[str, Any] | None = None
    raw_output: dict[str, Any] | None = None
    status: str | None = None
    timestamp: str = Field(default_factory=utc_now_iso)


class OpenCodeToolCallStart(OpenCodeToolCallBase):
    """Tool call start event."""

    type: Literal["tool_call_start"] = "tool_call_start"


class OpenCodeToolCallProgress(OpenCodeToolCallBase):
    """Tool call update event."""

    type: Literal["tool_call_progress"] = "tool_call_progress"


class OpenCodePromptResponse(BaseModel):
    """Turn completion event."""

    type: Literal["prompt_response"] = "prompt_response"
    opencode_session_id: str | None = None
    stop_reason: str | None = None
    timestamp: str = Field(default_factory=utc_now_iso)


class OpenCodeError(BaseModel):
    """Error event from OpenCode client/server interaction."""

    type: Literal["error"] = "error"
    opencode_session_id: str | None = None
    code: int | str | None = None
    message: str
    data: dict[str, Any] | None = None
    timestamp: str = Field(default_factory=utc_now_iso)


class OpenCodeSessionEstablished(BaseModel):
    """Internal event emitted when a session ID is discovered/created."""

    type: Literal["opencode_session_established"] = "opencode_session_established"
    opencode_session_id: str
    timestamp: str = Field(default_factory=utc_now_iso)


@dataclass(frozen=True)
class OpenCodeSSEKeepalive:
    """Marker used by SessionManager to emit SSE keepalive comments."""


OpenCodeEvent = (
    OpenCodeAgentMessageChunk
    | OpenCodeAgentThoughtChunk
    | OpenCodeToolCallStart
    | OpenCodeToolCallProgress
    | OpenCodePromptResponse
    | OpenCodeError
    | OpenCodeSessionEstablished
    | OpenCodeSSEKeepalive
)
