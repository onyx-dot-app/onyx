"""Packets of code mode calls: each `execute_code` or `wait_code` call is one card."""

from pydantic import BaseModel, JsonValue, TypeAdapter
from typing_extensions import override

from onyx.chat.renderer import ToolRenderer
from onyx.llm.models import ToolCall, ToolResult
from onyx.server.query_and_chat import streaming_models as packets
from onyx.server.query_and_chat.placement import Placement
from onyx.tools.constants import CODE_MODE_TOOL_NAMES, WAIT_CODE_TOOL_NAME
from onyx.tools.tool_implementations.code_mode.models import (
    CellWindow,
    CodeModeCall,
    CodeModeCallFinished,
    CodeModeCallProgress,
    CodeModeCallStarted,
    CodeModeExecutionResult,
    CodeModeStdout,
)

_STRING = TypeAdapter(str)
_INT = TypeAdapter(int)


def _stored_keys(window: CellWindow) -> list[str] | None:
    commit = window.commit
    if commit is None:
        return None
    return [key for key, value in commit.writes.items() if value is not None] or None


class CodeModeRenderer(ToolRenderer):
    """One observation of a cell. Each nested call renders with its tool's own
    renderer, at `sub_turn_index = call.index` of the card's placement."""

    def __init__(
        self, call: ToolCall, placement: Placement, tool_id: int | None = None
    ) -> None:
        super().__init__(call, placement, tool_id)
        self._children: dict[int, ToolRenderer] = {}
        self._stdout = ""

    def _start_objects(self, args: dict[str, JsonValue]) -> list[packets.PacketObj]:
        if self.call.name == WAIT_CODE_TOOL_NAME:
            return [
                packets.CodeModeStart(
                    code="",
                    cell_id=_INT.validate_python(args.get("cell_id")),
                    observation=1,
                )
            ]
        return [
            packets.CodeModeStart(code=_STRING.validate_python(args.get("code", "")))
        ]

    @override
    def update(
        self, details: BaseModel | None, content: str = ""
    ) -> list[packets.Packet]:
        if self._finished:
            return []
        if isinstance(details, CodeModeStdout):
            if not details.text:
                return []
            self._stdout += details.text
            return [
                packets.Packet(
                    placement=self.placement,
                    obj=packets.CodeModeDelta(stdout=details.text),
                )
            ]
        if isinstance(details, CodeModeCallStarted):
            return self._child(details.call).start()
        if isinstance(details, CodeModeCallProgress):
            child = self._children.get(details.index)
            return child.update(details.details, details.content) if child else []
        if isinstance(details, CodeModeCallFinished):
            return self._complete_child(details.call)
        return []

    def amend(self, result: ToolResult) -> list[packets.Packet]:
        """Complete the card if it is open, then render the cell's closing record."""
        output = self.complete(result)
        details = result.details
        if isinstance(details, CodeModeExecutionResult) and details.closing:
            output.extend(self._closing_packets(details))
        return output

    def _child(self, call: CodeModeCall) -> ToolRenderer:
        child = self._children.get(call.index)
        if child is None:
            child = ToolRenderer(
                ToolCall(
                    id=call.id,
                    name=call.tool_name,
                    arguments=call.arguments,
                ),
                self.placement.model_copy(update={"sub_turn_index": call.index}),
                call.tool_id,
            )
            self._children[call.index] = child
        return child

    def _complete_child(self, call: CodeModeCall) -> list[packets.Packet]:
        return self._child(call).complete(call.as_result())

    def _complete_open_children(self) -> list[packets.Packet]:
        return [
            packet
            for index in sorted(self._children)
            for packet in self._children[index].complete(None)
        ]

    def _result_packets(self, result: ToolResult | None) -> list[packets.Packet]:
        """Close nested calls, then send the program output and final status.

        Replay has no progress events, so the saved calls render here.
        """
        details = result.details if result is not None else None
        execution = details if isinstance(details, CodeModeExecutionResult) else None
        if execution is None:
            output = self._complete_open_children()
            if result is not None and result.is_error:
                final = packets.CodeModeDelta(error=result.text, status="failed")
            elif result is None:
                # The response ended before the call saved a result.
                final = packets.CodeModeDelta(
                    status="cancelled", tool_call_count=len(self._children)
                )
            else:
                return output
            output.append(packets.Packet(placement=self.placement, obj=final))
            return output
        # Calls still running when the observation ended stay open; a later
        # observation or the cell's closing record reports how they ended.
        output = [
            packet
            for call in execution.calls
            for packet in (
                self._child(call).start()
                if call.state == "running"
                else self._complete_child(call)
            )
        ]
        running = {call.index for call in execution.calls if call.state == "running"}
        output.extend(
            packet
            for index in sorted(self._children)
            if index not in running
            for packet in self._children[index].complete(None)
        )
        # Live output stops at the output limit; the saved output keeps the start
        # and the end. The final delta makes live output match replay.
        replace = bool(self._stdout) and self._stdout != execution.stdout
        output.append(
            packets.Packet(
                placement=self.placement,
                obj=packets.CodeModeDelta(
                    stdout=execution.stdout if replace or not self._stdout else "",
                    replace_stdout=replace,
                    result=execution.result,
                    error=execution.error,
                    status=execution.status,
                    duration_seconds=execution.duration_seconds,
                    tool_call_count=execution.tool_call_count,
                    stored_keys=_stored_keys(execution),
                    cell_id=execution.cell_id,
                    observation=execution.observation,
                ),
            )
        )
        return output

    def _closing_packets(
        self, observation: CodeModeExecutionResult
    ) -> list[packets.Packet]:
        """What the cell did after the observation, up to the end of the response,
        at the observation's placement after its final packets."""
        closing = observation.closing
        if closing is None:
            return []
        output = [
            packet for call in closing.calls for packet in self._complete_child(call)
        ]
        output.extend(self._complete_open_children())
        if closing.stdout:
            output.append(
                packets.Packet(
                    placement=self.placement,
                    obj=packets.CodeModeDelta(stdout=closing.stdout),
                )
            )
        output.append(
            packets.Packet(
                placement=self.placement,
                obj=packets.CodeModeDelta(
                    status=closing.status,
                    tool_call_count=closing.tool_call_count,
                    stored_keys=_stored_keys(closing),
                    response_ended=True,
                ),
            )
        )
        return output


def tool_renderer(
    call: ToolCall, placement: Placement, tool_id: int | None = None
) -> ToolRenderer:
    """The renderer of a tool call: a code mode card, or the generic tool display."""
    renderer = CodeModeRenderer if call.name in CODE_MODE_TOOL_NAMES else ToolRenderer
    return renderer(call, placement, tool_id)
