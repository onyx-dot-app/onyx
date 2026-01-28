"""Build Mode packet types for streaming agent responses.

This module defines CUSTOM Onyx packet types that extend ACP (Agent Client Protocol).
ACP events are passed through directly from the agent - this module only contains
Onyx-specific extensions like artifacts and file operations.

All packets use SSE (Server-Sent Events) format with `event: message` and include
a `type` field to distinguish packet types.

ACP events (passed through directly from acp.schema):
- agent_message_chunk: Text/image content from agent
- agent_thought_chunk: Agent's internal reasoning
- tool_call_start: Tool invocation started
- tool_call_progress: Tool execution progress/result
- agent_plan_update: Agent's execution plan
- current_mode_update: Agent mode change
- prompt_response: Agent finished processing
- error: An error occurred

Custom Onyx packets (defined here):
- error: Onyx-specific errors (e.g., session not found)

Based on:
- Agent Client Protocol (ACP): https://agentclientprotocol.com
"""

from datetime import datetime
from datetime import timezone
from typing import Any
from typing import Literal

from pydantic import BaseModel
from pydantic import Field


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
    code: int | None = None
    details: dict[str, Any] | None = None


# =============================================================================
# Union Type for Custom Onyx Packets
# =============================================================================

BuildPacket = ErrorPacket
