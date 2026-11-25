"""The generic card of a result without details shows its content once, live
as on replay: a tool of the agent, and a call inside a code mode cell."""

from onyx.agents.runtime import Agent
from onyx.agents.tools import AgentTool, ToolInvocation
from onyx.chat.emitter import Emitter
from onyx.chat.presentation import (
    ResponsePresenter,
    project_response,
    replay_response,
)
from onyx.llm.cancellation import CancellationSignal
from onyx.llm.interfaces import GenerationContext
from onyx.llm.models import (
    AssistantMessage,
    GenerationRequest,
    TextContent,
    ToolCall,
    ToolDefinition,
    ToolResult,
)
from onyx.server.query_and_chat import streaming_models as packets
from onyx.tools.constants import EXEC_TOOL_NAME
from onyx.tools.tool_implementations.code_mode.models import (
    CodeModeCall,
    CodeModeExecutionResult,
)
from onyx.tracing.flows import LLMFlow
from tests.unit.onyx.agents.fakes import FakeModelClient


def _live_and_replayed(
    call: ToolCall, result: ToolResult
) -> tuple[list[packets.Packet], list[packets.Packet]]:
    """The packets of a response that makes `call`, which returns `result`,
    then answers: as streamed, and as a reload sends them."""

    def reply(
        request: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        if len(request.messages) > 1:
            return AssistantMessage(content=[TextContent(text="answer")])
        return AssistantMessage(content=[call])

    def execute(_invocation: ToolInvocation) -> ToolResult:
        return result

    live: list[packets.Packet] = []
    run = Agent(
        FakeModelClient(reply),
        generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
        tools=[
            AgentTool(
                definition=ToolDefinition(
                    name=call.name, description="", parameters={}
                ),
                execute=execute,
            )
        ],
    ).start(max_steps=5, on_event=ResponsePresenter(Emitter(live.append)).consume)
    run.wait_for_completion(timeout=10)
    assert run.wait_for_idle(timeout=10)
    projected = project_response(run.snapshot(), tool_ids={})
    assert projected.response is not None
    return live, replay_response(projected.response, {}, {}, {})


def _deltas(output: list[packets.Packet]) -> list[tuple[int | None, object]]:
    return [
        (packet.placement.sub_turn_index, packet.obj.data)
        for packet in output
        if isinstance(packet.obj, packets.CustomToolDelta)
    ]


def test_a_tool_result_without_details_shows_its_content_once() -> None:
    live, replayed = _live_and_replayed(
        ToolCall(id="lookup", name="lookup", arguments={}),
        ToolResult(content="found it"),
    )
    assert _deltas(live) == [(None, "found it")]
    assert _deltas(replayed) == _deltas(live)


def test_a_program_call_without_details_shows_its_content_once() -> None:
    live, replayed = _live_and_replayed(
        ToolCall(id="exec", name=EXEC_TOOL_NAME, arguments={"code": "work()"}),
        ToolResult(
            content="Execution finished",
            details=CodeModeExecutionResult(
                cell_id=1,
                observation=0,
                code="work()",
                status="completed",
                calls=[
                    CodeModeCall(
                        id="exec:0",
                        index=0,
                        tool_name="lookup",
                        function_name="lookup",
                        arguments={},
                        state="ok",
                        content="found it",
                    )
                ],
                tool_call_count=1,
            ),
        ),
    )
    assert _deltas(live) == [(0, "found it")]
    assert _deltas(replayed) == _deltas(live)
