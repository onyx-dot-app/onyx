"""Tool packets name external tools by their display name, live and on replay."""

from onyx.agents.models import (
    ExecutionStatus,
    RunState,
    RunStatus,
    StepRecord,
    ToolExecutionRecord,
)
from onyx.chat.models import ToolReplayData
from onyx.chat.presentation import project_response, replay_response
from onyx.chat.renderer import ToolRenderer, tool_renderer
from onyx.llm.models import AssistantMessage, ToolCall, ToolResultMessage
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
        if isinstance(packet.obj, (packets.CustomToolStart, packets.CustomToolDelta))
    ]


def test_live_tool_packets_carry_the_tool_display_name() -> None:
    renderer = ToolRenderer(CALL, Placement(turn_index=0), 3, LABEL)
    output = renderer.start() + renderer.complete(RESULT)

    assert _labels(output) == [(QUALIFIED, LABEL), (QUALIFIED, LABEL)]


def test_saved_responses_replay_the_tool_display_name() -> None:
    state = RunState(
        run_id="run",
        status=RunStatus.COMPLETE,
        steps=[
            StepRecord(
                message=AssistantMessage(id="run:0", content=[CALL]),
                generation_status=ExecutionStatus.COMPLETE,
                tools={
                    CALL.id: ToolExecutionRecord(
                        status=ExecutionStatus.COMPLETE, result=RESULT
                    )
                },
            )
        ],
    )
    projected = project_response(
        state, tool_ids={QUALIFIED: 3}, tool_labels={QUALIFIED: LABEL}
    )
    assert projected.response is not None
    assert projected.presentation["run:0"].tool_labels == {QUALIFIED: LABEL}

    replayed = replay_response(
        projected.response,
        {("run:0", CALL.id): ToolReplayData(tool_id=3)},
        projected.presentation,
        {},
    )

    assert _labels(replayed) == [(QUALIFIED, LABEL), (QUALIFIED, LABEL)]


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
