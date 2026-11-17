"""Onyx's internal sandbox-event schema.

Single import point for the typed events Onyx's sandbox layer emits and
consumes. Currently re-exports from the `agent-client-protocol` PyPI
package; the wrapper exists so consumers don't need to know that, and so
a future inlining of these types (or swap to a different upstream)
touches only this file.

If you replace the re-exports with local models, keep the
``model_dump(by_alias=True)`` output byte-identical. ``BuildMessage.message_metadata``
stores tool-call and plan events in that shape, and saved rows are not migrated.
"""

from typing import Any, NotRequired, TypedDict

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
from pydantic import BaseModel


class TextPartMetadata(TypedDict):
    """Live part identity and authoritative text from OpenCode part updates."""

    partId: str
    snapshotText: NotRequired[str]


# The Onyx wire version a tool call carries in ``_meta.onyx.version``. Rows
# saved without it are version 1.
ONYX_WIRE_VERSION = 2


class OnyxToolMeta(BaseModel):
    """Onyx data on a tool call that ACP has no field for, in ``_meta.onyx``.

    Sits beside the existing flat ``_meta`` keys (``toolName``, the subagent
    session ids). Every field but ``version`` is optional and left out when
    unset, so readers treat a missing key as "not reported".
    """

    version: int = ONYX_WIRE_VERSION
    # ACP's status has no cancelled state: a cancelled call is ``failed`` with
    # this set, so a stopped call reads apart from one that errored.
    cancelled: bool | None = None

    def to_meta(self) -> dict[str, Any]:
        return self.model_dump(exclude_none=True)


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
    "ONYX_WIRE_VERSION",
    "OnyxToolMeta",
    "AgentMessageChunk",
    "AgentPlanUpdate",
    "AgentThoughtChunk",
    "CurrentModeUpdate",
    "Error",
    "PromptResponse",
    "RequestPermissionRequest",
    "ToolCallProgress",
    "ToolCallStart",
    "TextPartMetadata",
    "TURN_ERROR_CODE_SESSION",
    "TURN_ERROR_CODE_TIMEOUT",
    "TURN_ERROR_CODE_TRANSPORT",
]
