"""Onyx's internal sandbox-event schema.

Single import point for the typed events Onyx's sandbox layer emits and
consumes. Currently re-exports from the `agent-client-protocol` PyPI
package; the wrapper exists so consumers don't need to know that, and so
a future inlining of these types (or swap to a different upstream)
touches only this file. See docs/craft/drop-acp-layer.md.
"""

from acp.schema import (
    AgentMessageChunk,
    AgentPlanUpdate,
    AgentThoughtChunk,
    CurrentModeUpdate,
    Error,
    PromptResponse,
    RequestPermissionRequest,
    ToolCallProgress,
    ToolCallStart,
)

__all__ = [
    "AgentMessageChunk",
    "AgentPlanUpdate",
    "AgentThoughtChunk",
    "CurrentModeUpdate",
    "Error",
    "PromptResponse",
    "RequestPermissionRequest",
    "ToolCallProgress",
    "ToolCallStart",
]
