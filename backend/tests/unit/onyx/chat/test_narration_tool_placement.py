"""Native narration and domain tool progress occupy separate render groups."""

from queue import Queue
from unittest.mock import Mock

from pydantic_ai import messages as pm
from pydantic_ai.models.function import DeltaToolCall, FunctionModel
from pydantic_ai.tools import ToolDefinition

from onyx.chat.agent_runtime import NativeAgentRequest, run_native_agent
from onyx.chat.emitter import Emitter
from onyx.llm.interfaces import LLM, LLMConfig
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import PydanticAIEvent, SearchToolStart


def test_narration_and_tool_progress_keep_distinct_native_groups() -> None:
    requests = 0
    queue = Queue()
    emitter = Emitter(queue)
    responses: list[pm.ModelResponse] = []

    async def stream(_messages, _info):
        nonlocal requests
        requests += 1
        if requests == 1:
            yield "Let me search first."
            yield {1: DeltaToolCall(name="search", json_args="{}", tool_call_id="call")}
        else:
            yield "Here is the answer."

    llm = Mock(spec=LLM)
    llm.config = LLMConfig(
        model_provider="openai",
        model_name="gpt-5-mini",
        max_input_tokens=8000,
        temperature=0,
    )
    llm.model = FunctionModel(stream_function=stream)

    def execute(call: pm.ToolCallPart) -> str:
        index = next(
            index
            for index, part in enumerate(responses[-1].parts)
            if isinstance(part, pm.ToolCallPart)
            and part.tool_call_id == call.tool_call_id
        )
        emitter.report(
            placement=Placement(turn_index=0, tab_index=index), obj=SearchToolStart()
        )
        return "found"

    run_native_agent(
        llm=llm,
        prepare_step=lambda messages: NativeAgentRequest(
            messages, {}, [ToolDefinition(name="search")]
        ),
        finalize_step=responses.append,
        execute_tool=execute,
        tool_definitions=[
            {
                "type": "function",
                "function": {
                    "name": "search",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ],
        max_requests=2,
        emitter=emitter,
        state_container=None,
        placement=lambda: Placement(turn_index=max(0, requests - 1)),
        message_history=[pm.ModelRequest(parts=[pm.UserPromptPart("find")])],
    )
    packets = [queue.get_nowait()[1] for _ in range(queue.qsize())]
    narration = next(
        packet
        for packet in packets
        if isinstance(packet.obj, PydanticAIEvent)
        and packet.obj.text_delta.startswith("Let")
    )
    tool = next(packet for packet in packets if isinstance(packet.obj, SearchToolStart))
    assert narration.placement.tab_index != tool.placement.tab_index
    assert sum(isinstance(packet.obj, SearchToolStart) for packet in packets) == 1
    assert requests == 2
