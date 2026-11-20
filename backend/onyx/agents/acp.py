"""Emit ACP tool updates for one SDK run, including its replayed prefix."""

from typing import Literal
from urllib.parse import quote

from acp.helpers import start_tool_call, update_tool_call
from acp.schema import ToolCallProgress, ToolCallStart, ToolCallStatus, ToolKind
from pydantic import BaseModel

from onyx.llm.models import ToolResultFields

# A returned result is authoritative. None means the execution ended without
# returning a result. A release hook may report a failure after the return.
type ToolActivity = (
    ToolResultFields
    | None
    | Literal["preparing", "started", "waiting", "progress", "amended_failure"]
)


# The owner run plus the accepted message whose tool display is being produced.
type AcpToolScope = tuple[AcpRunTools, str]


class AcpRunTools:
    def __init__(self, run_id: str) -> None:
        self._prefix = quote(run_id, safe="")
        self._ids: dict[tuple[str | None, str], str] = {}

    @staticmethod
    def for_message(
        runs: dict[str, "AcpRunTools"] | None,
        run_id: str,
        message_id: str,
    ) -> AcpToolScope | None:
        if runs is None:
            return None
        if run_id not in runs:
            runs[run_id] = AcpRunTools(run_id)
        return runs[run_id], message_id

    def report(
        self,
        message_id: str,
        call_id: str,
        name: str,
        kind: ToolKind,
        *,
        activity: ToolActivity = "progress",
        public_output: BaseModel | None = None,
        nested: bool = False,
    ) -> ToolCallStart | ToolCallProgress:
        status: ToolCallStatus | None
        if isinstance(activity, ToolResultFields):
            status = "failed" if activity.is_error else "completed"
        elif activity is None or activity == "amended_failure":
            status = "failed"
        elif activity in ("preparing", "waiting"):
            status = "pending"
        elif activity == "started":
            status = "in_progress"
        else:
            # A detail update leaves the call in its current state.
            status = None

        # The SDK addresses a tool in its accepted assistant message. A
        # program's own call can appear in several observation messages.
        key = (None if nested else message_id, call_id)
        identity = self._ids.get(key)
        if identity is None:
            family = (
                "nested" if nested else f"message/{quote(message_id, safe='')}/tool"
            )
            identity = self._ids[key] = (
                f"{self._prefix}/{family}/{quote(call_id, safe='')}"
            )
            return start_tool_call(
                identity,
                name,
                kind=kind,
                status=status or "in_progress",
                raw_output=public_output,
            )
        return update_tool_call(identity, status=status, raw_output=public_output)
