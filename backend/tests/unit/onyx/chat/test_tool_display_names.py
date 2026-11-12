"""Tool start packets name external tools by their display name."""

from onyx.chat.renderer import ToolRenderer, tool_renderer
from onyx.llm.models import ToolCall, ToolResultMessage
from onyx.server.query_and_chat import streaming_models as packets
from onyx.server.query_and_chat.placement import Placement
from onyx.tools.models import CustomToolCallSummary
from onyx.tools.tool_implementations.code_mode.code_mode_tool import CodeModeTool
from onyx.tools.tool_implementations.code_mode.models import (
    CodeModeCall,
    CodeModeCallStarted,
)

# A server name that contains `__`; normalization keeps it.
QUALIFIED = "mcp__3__my__srv__create_issue"
LABEL = "Create issue"
CALL = ToolCall(id="call", name=QUALIFIED, arguments={"title": "Bug"})
RESULT = ToolResultMessage(
    tool_call_id=CALL.id,
    tool_name=QUALIFIED,
    content="created",
    details=CustomToolCallSummary(
        tool_name=QUALIFIED, response_type="json", tool_result={"id": 1}
    ),
)


def _labels(output: list[packets.Packet]) -> list[tuple[str, str]]:
    return [
        (packet.obj.tool_name, packet.obj.display_name)
        for packet in output
        if isinstance(packet.obj, packets.CustomToolStart)
    ]


def test_live_tool_packets_carry_the_tool_display_name() -> None:
    renderer = ToolRenderer(CALL, Placement(turn_index=0), 3, LABEL)
    output = renderer.start() + renderer.complete(RESULT)

    assert _labels(output) == [(QUALIFIED, LABEL)]


def test_code_mode_calls_carry_the_called_tool_display_name() -> None:
    renderer = tool_renderer(
        ToolCall(id="code", name=CodeModeTool.NAME, arguments={"code": ""}),
        Placement(turn_index=0),
    )
    renderer.start()
    output = renderer.update(
        CodeModeCallStarted(
            call=CodeModeCall(
                index=0,
                id="code:0",
                tool_name=QUALIFIED,
                tool_id=3,
                display_name=LABEL,
                function_name="create_issue",
                arguments={},
                state="running",
            )
        )
    )

    assert _labels(output) == [(QUALIFIED, LABEL)]
