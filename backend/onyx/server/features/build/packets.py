"""Build Mode packet types for streaming agent responses.

This module defines the packet types used for streaming build mode agent responses
to the frontend. It includes both ACP (Agent Client Protocol) based packets and
custom Onyx-specific packets.

All packets use SSE (Server-Sent Events) format with `event: message` and include
a `type` field to distinguish packet types.

Based on:
- Agent Client Protocol (ACP): https://agentclientprotocol.com
- OpenCode ACP implementation
- Frontend expectations from v1_api.py mock
"""

from datetime import datetime
from datetime import timezone
from enum import Enum
from typing import Any
from typing import Literal
from uuid import UUID

from acp.schema import AgentMessageChunk
from acp.schema import AgentPlanUpdate
from acp.schema import AgentThoughtChunk
from acp.schema import CurrentModeUpdate
from acp.schema import Error as ACPError
from acp.schema import PromptResponse
from acp.schema import ToolCallProgress
from acp.schema import ToolCallStart
from pydantic import BaseModel
from pydantic import Field


# =============================================================================
# Content Block Types (from ACP)
# =============================================================================


class TextContent(BaseModel):
    """Plain text content block."""

    type: Literal["text"] = "text"
    text: str


class ImageContent(BaseModel):
    """Image content block with base64 data."""

    type: Literal["image"] = "image"
    data: str  # base64-encoded image data
    mime_type: str = Field(alias="mimeType")


class AudioContent(BaseModel):
    """Audio content block with base64 data."""

    type: Literal["audio"] = "audio"
    data: str  # base64-encoded audio data
    mime_type: str = Field(alias="mimeType")


class EmbeddedResourceContent(BaseModel):
    """Embedded resource content (e.g., from @-mentions)."""

    type: Literal["embedded_resource"] = "embedded_resource"
    uri: str
    text: str | None = None
    blob: str | None = None  # base64-encoded blob
    mime_type: str | None = Field(None, alias="mimeType")


class ResourceLinkContent(BaseModel):
    """Reference to a resource the agent can access."""

    type: Literal["resource_link"] = "resource_link"
    uri: str
    name: str
    mime_type: str | None = Field(None, alias="mimeType")
    title: str | None = None
    description: str | None = None
    size: int | None = None  # size in bytes


# Union type for all content blocks
ContentBlock = (
    TextContent
    | ImageContent
    | AudioContent
    | EmbeddedResourceContent
    | ResourceLinkContent
)


# =============================================================================
# Base Packet Types
# =============================================================================


class BasePacket(BaseModel):
    """Base packet with common fields for all packet types."""

    type: str
    timestamp: str = Field(
        default_factory=lambda: datetime.now(tz=timezone.utc).isoformat()
    )


# =============================================================================
# Step/Thinking Packets (from AgentThoughtChunk)
# =============================================================================


class StepStartPacket(BasePacket):
    """Begin a logical step in agent processing."""

    type: Literal["step_start"] = "step_start"
    step_id: str
    step_name: str | None = None


class StepDeltaPacket(BasePacket):
    """Progress within a step (agent's internal reasoning)."""

    type: Literal["step_delta"] = "step_delta"
    step_id: str
    content: str  # Incremental thinking content
    content_block: ContentBlock | None = None  # Optional structured content


class StepEndPacket(BasePacket):
    """Finish a step."""

    type: Literal["step_end"] = "step_end"
    step_id: str
    status: Literal["completed", "failed", "cancelled"] = "completed"


# =============================================================================
# Tool Call Packets (from ToolCallStart and ToolCallProgress)
# =============================================================================


class ToolCallStatus(str, Enum):
    """Status of a tool call."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ToolStartPacket(BasePacket):
    """Agent invoking a tool."""

    type: Literal["tool_start"] = "tool_start"
    tool_call_id: str
    tool_name: str
    tool_input: dict[str, Any] = Field(default_factory=dict)
    title: str | None = None  # Human-readable description


class ToolProgressPacket(BasePacket):
    """Tool execution progress update."""

    type: Literal["tool_progress"] = "tool_progress"
    tool_call_id: str
    tool_name: str
    status: ToolCallStatus
    progress: float | None = None  # 0.0 to 1.0
    message: str | None = None


class ToolEndPacket(BasePacket):
    """Tool execution finished."""

    type: Literal["tool_end"] = "tool_end"
    tool_call_id: str
    tool_name: str
    status: Literal["success", "error", "cancelled"] = "success"
    result: str | dict[str, Any] | None = None
    error: str | None = None
    content: list[ContentBlock] | None = None  # Structured result content


# =============================================================================
# Agent Output Packets (from AgentMessageChunk)
# =============================================================================


class OutputStartPacket(BasePacket):
    """Begin agent's text output."""

    type: Literal["output_start"] = "output_start"


class OutputDeltaPacket(BasePacket):
    """Incremental agent text output."""

    type: Literal["output_delta"] = "output_delta"
    content: str  # Incremental text content
    content_block: ContentBlock | None = None  # Optional structured content


class OutputEndPacket(BasePacket):
    """Agent's text output finished."""

    type: Literal["output_end"] = "output_end"


# =============================================================================
# Plan Packets (from AgentPlanUpdate)
# =============================================================================


class PlanEntry(BaseModel):
    """A single entry in the agent's plan."""

    id: str
    description: str
    status: Literal["pending", "in_progress", "completed", "cancelled"] = "pending"
    priority: int | None = None


class PlanPacket(BasePacket):
    """Agent's execution plan."""

    type: Literal["plan"] = "plan"
    plan: str | None = None  # Text description of the plan
    entries: list[PlanEntry] | None = None  # Structured plan entries


# =============================================================================
# Mode Update Packets (from CurrentModeUpdate)
# =============================================================================


class ModeUpdatePacket(BasePacket):
    """Agent mode change (e.g., planning, implementing, debugging)."""

    type: Literal["mode_update"] = "mode_update"
    mode: str  # e.g., "plan", "implement", "debug"
    description: str | None = None


# =============================================================================
# Completion Packets (from PromptResponse)
# =============================================================================


class StopReason(str, Enum):
    """Reason for agent stopping."""

    END_TURN = "end_turn"
    MAX_TOKENS = "max_tokens"
    MAX_TURN_REQUESTS = "max_turn_requests"
    REFUSAL = "refusal"
    CANCELLED = "cancelled"


class DonePacket(BasePacket):
    """Signal completion with summary."""

    type: Literal["done"] = "done"
    summary: str
    stop_reason: StopReason | None = None
    usage: dict[str, Any] | None = None  # Token usage stats


# =============================================================================
# Error Packets (from ACP Error)
# =============================================================================


class ErrorPacket(BasePacket):
    """An error occurred."""

    type: Literal["error"] = "error"
    message: str
    code: int | None = None
    details: dict[str, Any] | None = None


# =============================================================================
# Custom Onyx Packets
# =============================================================================


class FileWritePacket(BasePacket):
    """File written to sandbox."""

    type: Literal["file_write"] = "file_write"
    path: str
    size_bytes: int | None = None
    operation: Literal["create", "update", "delete"] = "create"


class ArtifactType(str, Enum):
    """Type of artifact generated."""

    WEB_APP = "web_app"
    MARKDOWN = "markdown"
    IMAGE = "image"
    CSV = "csv"
    EXCEL = "excel"
    PPTX = "pptx"
    DOCX = "docx"
    PDF = "pdf"
    CODE = "code"
    OTHER = "other"


class Artifact(BaseModel):
    """An artifact generated by the agent."""

    id: str  # UUID
    type: ArtifactType
    name: str
    path: str  # Relative path from sandbox root
    preview_url: str | None = None
    download_url: str | None = None
    mime_type: str | None = None
    size_bytes: int | None = None
    metadata: dict[str, Any] | None = None


class ArtifactCreatedPacket(BasePacket):
    """New artifact generated."""

    type: Literal["artifact_created"] = "artifact_created"
    artifact: Artifact


# =============================================================================
# Permission Request Packets
# =============================================================================


class PermissionRequestPacket(BasePacket):
    """Request user permission for an operation."""

    type: Literal["permission_request"] = "permission_request"
    request_id: str
    operation: str
    description: str
    auto_approve: bool = False


class PermissionResponsePacket(BasePacket):
    """Response to a permission request."""

    type: Literal["permission_response"] = "permission_response"
    request_id: str
    approved: bool
    reason: str | None = None


# =============================================================================
# Union Type for All Packets
# =============================================================================

BuildPacket = (
    StepStartPacket
    | StepDeltaPacket
    | StepEndPacket
    | ToolStartPacket
    | ToolProgressPacket
    | ToolEndPacket
    | OutputStartPacket
    | OutputDeltaPacket
    | OutputEndPacket
    | PlanPacket
    | ModeUpdatePacket
    | DonePacket
    | ErrorPacket
    | FileWritePacket
    | ArtifactCreatedPacket
    | PermissionRequestPacket
    | PermissionResponsePacket
)


# =============================================================================
# Conversion Utilities
# =============================================================================


def extract_text_content(content_block: Any) -> str | None:
    """Extract text from a content block (handles ACP ContentBlock types)."""
    if hasattr(content_block, "text"):
        return content_block.text
    return None


def convert_acp_thought_to_step_delta(
    thought: AgentThoughtChunk, step_id: str = "thinking"
) -> StepDeltaPacket:
    """Convert an ACP AgentThoughtChunk to a StepDeltaPacket."""
    content_block = getattr(thought, "content", None)
    text = extract_text_content(content_block) or ""

    return StepDeltaPacket(
        step_id=step_id,
        content=text,
    )


def convert_acp_tool_start_to_tool_start(tool_start: ToolCallStart) -> ToolStartPacket:
    """Convert an ACP ToolCallStart to a ToolStartPacket."""
    return ToolStartPacket(
        tool_call_id=getattr(tool_start, "tool_call_id", ""),
        tool_name=getattr(tool_start, "tool_name", "unknown"),
        tool_input=getattr(tool_start, "input", {}),
        title=getattr(tool_start, "title", None),
    )


def convert_acp_tool_progress_to_tool_end(
    tool_progress: ToolCallProgress,
) -> ToolEndPacket:
    """Convert an ACP ToolCallProgress to a ToolEndPacket."""
    status = getattr(tool_progress, "status", "completed")

    # Map ACP status to our status
    if status == "completed":
        our_status: Literal["success", "error", "cancelled"] = "success"
    elif status == "failed":
        our_status = "error"
    elif status == "cancelled":
        our_status = "cancelled"
    else:
        our_status = "success"

    return ToolEndPacket(
        tool_call_id=getattr(tool_progress, "tool_call_id", ""),
        tool_name=getattr(tool_progress, "tool_name", ""),
        status=our_status,
        result=getattr(tool_progress, "result", None),
        error=getattr(tool_progress, "error", None),
    )


def convert_acp_message_chunk_to_output_delta(
    message_chunk: AgentMessageChunk,
) -> OutputDeltaPacket:
    """Convert an ACP AgentMessageChunk to an OutputDeltaPacket."""
    content_block = getattr(message_chunk, "content", None)
    text = extract_text_content(content_block) or ""

    return OutputDeltaPacket(
        content=text,
    )


def convert_acp_plan_to_plan(plan_update: AgentPlanUpdate) -> PlanPacket:
    """Convert an ACP AgentPlanUpdate to a PlanPacket."""
    plan_text = getattr(plan_update, "plan", None)

    # Try to extract structured entries if available
    entries = getattr(plan_update, "entries", None)
    if entries:
        plan_entries = [
            PlanEntry(
                id=entry.get("id", ""),
                description=entry.get("description", ""),
                status=entry.get("status", "pending"),
                priority=entry.get("priority"),
            )
            for entry in entries
        ]
    else:
        plan_entries = None

    return PlanPacket(
        plan=plan_text,
        entries=plan_entries,
    )


def convert_acp_mode_update_to_mode_update(
    mode_update: CurrentModeUpdate,
) -> ModeUpdatePacket:
    """Convert an ACP CurrentModeUpdate to a ModeUpdatePacket."""
    return ModeUpdatePacket(
        mode=getattr(mode_update, "mode", ""),
        description=getattr(mode_update, "description", None),
    )


def convert_acp_prompt_response_to_done(
    prompt_response: PromptResponse,
) -> DonePacket:
    """Convert an ACP PromptResponse to a DonePacket."""
    stop_reason_str = getattr(prompt_response, "stop_reason", None)

    # Try to parse stop reason enum
    stop_reason = None
    if stop_reason_str:
        try:
            stop_reason = StopReason(stop_reason_str)
        except ValueError:
            pass

    summary = f"Completed: {stop_reason_str}" if stop_reason_str else "Task completed"

    return DonePacket(
        summary=summary,
        stop_reason=stop_reason,
        usage=getattr(prompt_response, "usage", None),
    )


def convert_acp_error_to_error(acp_error: ACPError) -> ErrorPacket:
    """Convert an ACP Error to an ErrorPacket."""
    return ErrorPacket(
        message=getattr(acp_error, "message", "Unknown error"),
        code=getattr(acp_error, "code", None),
    )


def create_artifact_from_file(
    session_id: UUID,
    file_path: str,
    artifact_type: ArtifactType,
    name: str,
    mime_type: str | None = None,
) -> Artifact:
    """Create an Artifact from a file path."""
    import uuid

    artifact_id = str(uuid.uuid4())

    # Build preview URL based on artifact type
    if artifact_type == ArtifactType.WEB_APP:
        preview_url = f"/api/build/sessions/{session_id}/preview"
    elif artifact_type in [
        ArtifactType.IMAGE,
        ArtifactType.PPTX,
        ArtifactType.EXCEL,
        ArtifactType.DOCX,
    ]:
        preview_url = f"/api/build/sessions/{session_id}/artifacts/{file_path}"
    else:
        preview_url = None

    return Artifact(
        id=artifact_id,
        type=artifact_type,
        name=name,
        path=file_path,
        preview_url=preview_url,
        download_url=f"/api/build/sessions/{session_id}/artifacts/{file_path}",
        mime_type=mime_type,
    )
