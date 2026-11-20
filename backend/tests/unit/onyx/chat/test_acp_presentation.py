"""Exercise SDK execution facts through the live and saved ACP views."""

import json
from unittest.mock import patch

from acp.schema import ToolCallProgress, ToolCallStart
from pydantic import TypeAdapter

from onyx.agents.acp import AcpRunTools
from onyx.agents.events import (
    AgentEndEvent,
    InputRequiredEvent,
    MessageEndEvent,
    MessageStartEvent,
    ToolEndEvent,
)
from onyx.agents.models import (
    ExecutionStatus,
    RunStatus,
    StepRecord,
    ToolExecutionRecord,
)
from onyx.agents.tools import InputMode, PendingToolInput
from onyx.chat.emitter import Emitter
from onyx.chat.models import ResponseRecord
from onyx.chat.presentation import ResponsePresenter, replay_response
from onyx.chat.renderer import tool_renderer
from onyx.llm.models import AssistantMessage, ToolCall, ToolResult, ToolResultMessage
from onyx.server.query_and_chat.acp_stream import acp_line, acp_message, resume_block
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import (
    AgentResponseDelta,
    ExecEnd,
    Packet,
    UserMessagePacket,
    heartbeat_packet,
)
from onyx.tools.tool_implementations.sandbox.models import SandboxExecResult


def test_missing_error_details_preserve_failure_live_and_in_history() -> None:
    call = ToolCall(
        name="run_python",
        id="same/id",
        arguments={},
        argument_error="invalid arguments",
    )
    message = AssistantMessage(id="step", content=[call])
    result = ToolResult(content="invalid arguments", is_error=True)
    live: list[Packet] = []
    presenter = ResponsePresenter(Emitter(live.append))
    presenter.consume(MessageStartEvent(run_id="r", message_id="step", step_index=0))
    presenter.consume(
        MessageEndEvent(
            run_id="r",
            message_id="step",
            step_index=0,
            message=message,
            status=ExecutionStatus.COMPLETE,
        )
    )
    presenter.consume(
        ToolEndEvent(
            run_id="r", message_id="step", step_index=0, tool_call=call, result=result
        )
    )
    presenter.consume(AgentEndEvent(run_id="r", outcome=RunStatus.COMPLETE))
    record = ResponseRecord(
        run_id="r",
        status=RunStatus.COMPLETE,
        steps=[
            StepRecord(
                message=message,
                generation_status=ExecutionStatus.COMPLETE,
                tools={
                    call.id: ToolExecutionRecord(
                        status=ExecutionStatus.COMPLETE,
                        result=ToolResultMessage(
                            tool_name=call.name,
                            tool_call_id=call.id,
                            content=result.text,
                            is_error=True,
                        ),
                    )
                },
            )
        ],
    )
    replay = replay_response(record, {}, {}, {}, acp_runs={})
    tool_update = TypeAdapter(ToolCallStart | ToolCallProgress)
    for stream in [live, replay]:
        updates = [
            tool_update.validate_python(acp_message("s", packet)["params"]["update"])
            for packet in stream
            if packet.acp_update is not None
        ]
        assert [u.status for u in updates] == ["in_progress", "failed"]
        assert all(result.text not in u.model_dump_json() for u in updates)
        assert [u.tool_call_id for u in updates] == [
            "r/message/step/tool/same%2Fid"
        ] * 2
        assert updates[-1].field_meta and updates[-1].field_meta["onyx"]["packet"] == {
            "type": "section_end"
        }


def test_approval_request_keeps_tool_pending_and_heartbeat_independent() -> None:
    call = ToolCall(id="search", name="search", arguments={})
    output: list[Packet] = []
    presenter = ResponsePresenter(Emitter(output.append))
    presenter.consume(
        InputRequiredEvent(
            run_id="r",
            message_id="m",
            step_index=0,
            tool_call=call,
            request=PendingToolInput(
                request_id="req", prompt="Allow?", mode=InputMode.EXECUTE, approval=True
            ),
        )
    )
    opening = ToolCallStart.model_validate(
        acp_message("s", output[0])["params"]["update"]
    )
    assert opening.status == "pending"
    heartbeat = heartbeat_packet()
    assert acp_message("s", heartbeat)["method"] == "_onyx/chat_heartbeat"


def test_replay_and_live_share_the_frame_only_for_the_published_packet() -> None:
    packet = Packet(
        placement=Placement(turn_index=0), obj=AgentResponseDelta(content="hello")
    )
    cached = acp_line("session", packet, retain=True)
    with patch(
        "onyx.server.query_and_chat.acp_stream.acp_message", side_effect=AssertionError
    ):
        assert acp_line("session", packet) is cached
    assert json.loads(acp_line("other", packet))["params"]["sessionId"] == "other"
    copied = packet.model_copy(update={"placement": Placement(turn_index=1)})
    update = json.loads(acp_line("session", copied))["params"]["update"]
    assert update["_meta"]["onyx"]["placement"]["turn_index"] == 1


def test_large_tool_output_and_user_text_cross_the_wire_once() -> None:
    body = "many words " * 5000
    tool = tool_renderer(
        ToolCall(id="cmd", name="exec_command", arguments={"cmd": "cmd"}),
        Placement(turn_index=0),
        acp_tools=(AcpRunTools("r"), "message"),
    )
    result = ToolResult(
        content="private model observation",
        details=SandboxExecResult(output=body, wall_time_seconds=0.1),
    )
    end = next(p for p in tool.complete(result) if isinstance(p.obj, ExecEnd))
    user = Packet(
        placement=Placement(turn_index=1),
        obj=UserMessagePacket(id="7", message=body, mentions=[]),
    )
    for packet in (end, user):
        line = acp_line("s", packet)
        assert line.count(body) == 1
        assert "private model observation" not in line
        restored = resume_block(
            line, cached_acp=True, requested_acp=False, session_id="s"
        )
        assert json.loads(restored) == packet.model_dump(mode="json")


def test_reused_call_id_in_two_accepted_steps_has_distinct_live_and_replayed_tools() -> (
    None
):
    call = ToolCall(id="repeated", name="lookup", arguments={})
    live: list[Packet] = []
    presenter = ResponsePresenter(Emitter(live.append))
    steps: list[StepRecord] = []
    for index in range(2):
        message_id = f"step/{index}"
        message = AssistantMessage(id=message_id, content=[call])
        presenter.consume(
            MessageStartEvent(run_id="run", message_id=message_id, step_index=index)
        )
        presenter.consume(
            MessageEndEvent(
                run_id="run",
                message_id=message_id,
                step_index=index,
                message=message,
                status=ExecutionStatus.COMPLETE,
            )
        )
        presenter.consume(
            ToolEndEvent(
                run_id="run",
                message_id=message_id,
                step_index=index,
                tool_call=call,
                result=ToolResult(content="done"),
            )
        )
        steps.append(
            StepRecord(
                message=message,
                generation_status=ExecutionStatus.COMPLETE,
                tools={
                    call.id: ToolExecutionRecord(
                        status=ExecutionStatus.COMPLETE,
                        result=ToolResultMessage(
                            tool_name=call.name, tool_call_id=call.id, content="done"
                        ),
                    )
                },
            )
        )
    replay = replay_response(
        ResponseRecord(run_id="run", status=RunStatus.COMPLETE, steps=steps),
        {},
        {},
        {},
        acp_runs={},
    )
    expected = [
        "run/message/step%2F0/tool/repeated",
        "run/message/step%2F1/tool/repeated",
    ]
    for stream in (live, replay):
        assert [
            p.acp_update.tool_call_id
            for p in stream
            if isinstance(p.acp_update, ToolCallStart)
        ] == expected
        assert [
            p.acp_update.tool_call_id
            for p in stream
            if p.acp_update and p.acp_update.status == "completed"
        ] == expected
