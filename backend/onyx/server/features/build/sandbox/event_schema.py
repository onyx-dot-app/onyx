"""Onyx's internal sandbox-event schema.

Single import point for the typed events Onyx's sandbox layer emits and
consumes. Currently re-exports from the `agent-client-protocol` PyPI
package; the wrapper exists so consumers don't need to know that, and so
a future inlining of these types (or swap to a different upstream)
touches only this file. See docs/craft/drop-acp-layer.md.
"""

from acp.schema import AgentMessageChunk
from acp.schema import AgentPlanUpdate
from acp.schema import AgentThoughtChunk
from acp.schema import CurrentModeUpdate
from acp.schema import Error
from acp.schema import PromptResponse
from acp.schema import RequestPermissionRequest
from acp.schema import ToolCallProgress
from acp.schema import ToolCallStart

# Onyx-synthesized ``Error.code`` sentinels for turn-terminating failures.
# Negative so they never collide with opencode / JSON-RPC error codes.
TURN_ERROR_CODE_SESSION = -1  # opencode reported an error during the turn
TURN_ERROR_CODE_TIMEOUT = -2
TURN_ERROR_CODE_TRANSPORT = -3


class ActivityTimeoutError(Error):
    """A step produced no output within the inactivity window — recoverable by
    re-prompting, unlike a hard absolute/budget timeout. The distinction is
    carried by the type, not ``code`` (which it shares with the hard timeout)."""

    code: int = TURN_ERROR_CODE_TIMEOUT


__all__ = [
    "ActivityTimeoutError",
    "AgentMessageChunk",
    "AgentPlanUpdate",
    "AgentThoughtChunk",
    "CurrentModeUpdate",
    "Error",
    "PromptResponse",
    "RequestPermissionRequest",
    "ToolCallProgress",
    "ToolCallStart",
    "TURN_ERROR_CODE_SESSION",
    "TURN_ERROR_CODE_TIMEOUT",
    "TURN_ERROR_CODE_TRANSPORT",
]
