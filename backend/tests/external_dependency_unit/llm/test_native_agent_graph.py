"""Live native graph, signed history, and cancellation checks without a database."""

import threading
import time
from queue import Queue
from unittest.mock import patch

import pytest
from pydantic import BaseModel
from pydantic_ai import messages as pm
from pydantic_ai.exceptions import RunCancelled
from pydantic_ai.tools import ToolDefinition

from onyx.chat.agent_runtime import NativeAgentRequest, run_native_agent
from onyx.chat.emitter import Emitter
from onyx.llm.inference import run_inference
from onyx.llm.models import ReasoningEffort, ToolChoiceOptions
from onyx.llm.pydantic_ai_llm import PydanticAILLM
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import Packet, PydanticAIEvent
from onyx.tracing.flows import LLMFlow
from tests.utils.secret_names import TestSecret

PROVIDERS = [
    pytest.param(
        "openai",
        "gpt-5-mini",
        TestSecret.OPENAI_API_KEY,
        marks=pytest.mark.secrets(TestSecret.OPENAI_API_KEY),
    ),
    pytest.param(
        "anthropic",
        "claude-haiku-4-5",
        TestSecret.ANTHROPIC_API_KEY,
        marks=pytest.mark.secrets(TestSecret.ANTHROPIC_API_KEY),
    ),
]


def make_llm(provider: str, model: str, key: str) -> PydanticAILLM:
    return PydanticAILLM(
        api_key=key,
        model_provider=provider,
        model_name=model,
        max_input_tokens=32000,
        timeout=45,
    )


class CountOutput(BaseModel):
    count: int


@pytest.mark.parametrize("provider,model,secret", PROVIDERS)
def test_live_native_structured_inference(
    provider: str,
    model: str,
    secret: TestSecret,
    test_secrets: dict[TestSecret, str],
) -> None:
    llm = make_llm(provider, model, test_secrets[secret])
    with patch.object(llm, "record_usage") as record_usage:
        result = run_inference(
            llm=llm,
            messages=[
                pm.ModelRequest(
                    parts=[pm.UserPromptPart("Return count=3 as structured output.")]
                )
            ],
            output_type=CountOutput,
            flow=LLMFlow.SEMANTIC_QUERY_REPHRASE,
            max_tokens=1024,
            total_timeout_override=45,
        )
    assert result.count == 3
    assert 1 <= record_usage.call_count <= 2
    assert all(call.args[0].input_tokens > 0 for call in record_usage.call_args_list)


@pytest.mark.parametrize("provider,model,secret", PROVIDERS)
def test_live_native_tool_cycle_preserves_results_and_signed_history(
    provider: str,
    model: str,
    secret: TestSecret,
    test_secrets: dict[TestSecret, str],
) -> None:
    llm = make_llm(provider, model, test_secrets[secret])
    queue: Queue = Queue()
    histories: list[list[pm.ModelMessage]] = []
    calls: list[pm.ToolCallPart] = []
    schema = {
        "type": "object",
        "properties": {"item": {"type": "integer"}},
        "required": ["item"],
        "additionalProperties": False,
    }
    definition = {
        "type": "function",
        "function": {
            "name": "lookup_local",
            "description": "Read an ephemeral local test value.",
            "parameters": schema,
        },
    }

    def prepare(messages: list[pm.ModelMessage]) -> NativeAgentRequest:
        histories.append(list(messages))
        return NativeAgentRequest(
            messages,
            llm.model_settings(
                reasoning_effort=ReasoningEffort.LOW,
                max_tokens=4096,
                tool_choice=ToolChoiceOptions.NONE if calls else ToolChoiceOptions.AUTO,
            ),
            []
            if calls
            else [ToolDefinition(name="lookup_local", parameters_json_schema=schema)],
        )

    def execute(call: pm.ToolCallPart) -> str:
        calls.append(call)
        assert call.args_as_dict() == {"item": 7}
        return "ledger-result-47"

    with patch.object(llm, "record_usage") as record_usage:
        output = run_native_agent(
            llm=llm,
            prepare_step=prepare,
            finalize_step=lambda _response: None,
            execute_tool=execute,
            tool_definitions=[definition],
            max_requests=3,
            emitter=Emitter(queue),
            state_container=None,
            placement=lambda: Placement(turn_index=len(histories)),
            message_history=[
                pm.ModelRequest(
                    parts=[
                        pm.UserPromptPart(
                            "Call lookup_local with item 7 exactly once. Then repeat its exact result and nothing else. Do not guess the result."
                        )
                    ]
                )
            ],
            total_timeout=90,
        )
    assert "ledger-result-47" in output
    assert len(calls) == 1
    assert record_usage.call_count == 2
    assert any(
        isinstance(part, pm.ToolReturnPart) and part.content == "ledger-result-47"
        for message in histories[1]
        for part in message.parts
    )
    if provider == "anthropic":
        assert any(
            isinstance(part, pm.ThinkingPart) and part.signature
            for message in histories[1]
            for part in message.parts
        )
    packets = [queue.get_nowait()[1] for _ in range(queue.qsize())]
    kinds = {
        packet.obj.event["event_kind"]
        for packet in packets
        if isinstance(packet.obj, PydanticAIEvent)
    }
    assert {
        "part_start",
        "part_delta",
        "function_tool_call",
        "function_tool_result",
    } <= kinds


@pytest.mark.parametrize("provider,model,secret", PROVIDERS)
def test_live_native_stream_disconnect_cancels_and_accounts_once(
    provider: str,
    model: str,
    secret: TestSecret,
    test_secrets: dict[TestSecret, str],
) -> None:
    llm = make_llm(provider, model, test_secrets[secret])
    disconnected = threading.Event()
    started_content: list[float] = []

    class DisconnectingEmitter(Emitter):
        def emit(self, packet: Packet) -> None:
            super().emit(packet)
            if (
                isinstance(packet.obj, PydanticAIEvent)
                and packet.obj.event.get("event_kind") == "part_delta"
                and not started_content
            ):
                started_content.append(time.monotonic())
                disconnected.set()

    with patch.object(llm, "record_usage") as record_usage, pytest.raises(RunCancelled):
        run_native_agent(
            llm=llm,
            prepare_step=lambda messages: NativeAgentRequest(
                messages,
                llm.model_settings(
                    reasoning_effort=ReasoningEffort.LOW, max_tokens=8192
                ),
                [],
            ),
            finalize_step=lambda _response: None,
            execute_tool=lambda _call: "",
            tool_definitions=[],
            max_requests=1,
            emitter=DisconnectingEmitter(Queue(), drain_done=disconnected),
            state_container=None,
            placement=lambda: Placement(turn_index=0),
            message_history=[
                pm.ModelRequest(
                    parts=[
                        pm.UserPromptPart(
                            "Write the integers 1 through 2000 in words, one per line. Start immediately and do not summarize."
                        )
                    ]
                )
            ],
            total_timeout=90,
        )
    assert started_content
    assert time.monotonic() - started_content[0] < 10
    record_usage.assert_called_once()
