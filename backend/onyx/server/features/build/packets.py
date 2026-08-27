"""Build Mode packet types for streaming agent responses.

Custom Onyx packet types layered on top of the sandbox-event schema
(:mod:`sandbox.event_schema`). Sandbox events pass through directly from
the agent; this module only contains Onyx-specific extensions like
artifacts and file operations.

All packets use SSE (Server-Sent Events) format with `event: message` and
include a `type` field to distinguish packet types.

Sandbox events (re-emitted from :mod:`sandbox.event_schema`):
- agent_message_chunk: Text/image content from agent
- agent_thought_chunk: Agent's internal reasoning
- tool_call_start: Tool invocation started
- tool_call_progress: Tool execution progress/result
- agent_plan_update: Agent's execution plan
- current_mode_update: Agent mode change
- prompt_response: Agent finished processing
- error: An error occurred

The custom Onyx packet classes below are the authoritative list; the
``BuildPacket`` union at the bottom names them all.
"""

from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from onyx.db.enums import ArtifactType

# =============================================================================
# Base Packet Type
# =============================================================================


class BasePacket(BaseModel):
    """Base packet with common fields for all custom Onyx packet types."""

    type: str
    timestamp: str = Field(
        default_factory=lambda: datetime.now(tz=timezone.utc).isoformat()
    )


# =============================================================================
# Custom Onyx Packets
# =============================================================================


class ErrorPacket(BasePacket):
    """An Onyx-specific error occurred (e.g., session not found, sandbox not running)."""

    type: Literal["error"] = "error"
    message: str


class ApprovalRequestedPacket(BasePacket):
    """A new approval awaits the user's decision.

    Carries only ids; the FE refetches card contents via the /live endpoint
    so Postgres stays the single source of truth.
    """

    type: Literal["approval_requested"] = "approval_requested"
    approval_id: UUID
    session_id: UUID


class SubagentStartedPacket(BasePacket):
    """A child opencode session was created for a parent task tool call."""

    type: Literal["subagent_started"] = "subagent_started"
    subagent_session_id: str
    parent_session_id: str


class ConnectAppRequestPacket(BasePacket):
    """The agent's ``connect_app`` tool is asking the user to connect an org app.

    The FE renders the connect card from this packet (resolving the app from the
    registry by ``external_app_id``) and POSTs the decision to
    ``/build/apps/connect/{request_id}/decision`` to answer the agent's tool call.
    """

    type: Literal["connect_app_request"] = "connect_app_request"
    request_id: str
    external_app_id: int
    reason: str | None = None


class ArtifactPacket(BasePacket):
    """An artifact row was produced, changed, or deleted at turn end.

    Carries the full row, unlike the ids-only approval packet, so a consumer
    can render a card with no round trip. The version is pinned at announce
    time and the index refetch at turn end is the completeness guarantee.
    """

    type: Literal["artifact"] = "artifact"
    artifact_id: UUID
    session_id: UUID
    path: str
    name: str
    artifact_type: ArtifactType
    version: int
    turn_index: int | None
    size_bytes: int | None
    deleted: bool


class ContextUsagePacket(BasePacket):
    type: Literal["context_usage"] = "context_usage"
    used_tokens: int
    cost: float | None = None


class CompactionPacket(BasePacket):
    type: Literal["compaction"] = "compaction"
    summary: str | None = None


# =============================================================================
# Union Type for Custom Onyx Packets
# =============================================================================

BuildPacket = (
    ErrorPacket
    | ApprovalRequestedPacket
    | SubagentStartedPacket
    | ConnectAppRequestPacket
    | ArtifactPacket
    | ContextUsagePacket
    | CompactionPacket
)
