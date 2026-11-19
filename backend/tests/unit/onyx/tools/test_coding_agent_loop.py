"""Coding output uses the packets consumed by the coding card."""

import json
from collections.abc import Iterator
from unittest.mock import MagicMock, patch

import pytest
from pydantic import JsonValue

from onyx.agents.models import RunResult, RunStatus
from onyx.agents.tool_execution import NO_TOOL_CAN_RUN_RESULT
from onyx.chat.emitter import Emitter
from onyx.chat.presentation import ResponsePresenter
from onyx.chat.renderer import ToolRenderer
from onyx.coding_agent.agent import CodingAgent
from onyx.coding_agent.tool_definitions import (
    BASH_TOOL_NAME,
    CODING_AGENT_TOOL_NAME,
    GENERATE_ANSWER_TOOL_NAME,
)
from onyx.configs.chat_configs import LLM_SOCKET_READ_TIMEOUT
from onyx.llm.interfaces import LLMConfig, LLMUserIdentity
from onyx.llm.model_request import ChatCompletionMessage, ToolMessage
from onyx.llm.model_response import (
    ChatCompletionDeltaToolCall,
    Delta,
    ModelResponseStream,
    ResponseFunctionCall,
    StreamingChoice,
)
from onyx.llm.models import (
    ReasoningEffort,
    ToolCall,
    ToolChoice,
    ToolChoiceOptions,
    ToolResult,
    UserMessage,
)
from onyx.llm.multi_llm import LitellmLLM, ProviderOperation
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import (
    CodingAgentThinkingDelta,
    Packet,
    ReasoningStart,
)
from onyx.tools.tool_implementations.bash.bash_tool import BashTool

MODULE = "onyx.coding_agent.agent"
TURN_INDEX = 3
TAB_INDEX = 1


def _chunk(delta: Delta) -> ModelResponseStream:
    return ModelResponseStream(id="c", created="0", choice=StreamingChoice(delta=delta))


def text(content: str) -> list[ModelResponseStream]:
    return [_chunk(Delta(content=content))]


def reasoning(content: str) -> list[ModelResponseStream]:
    return [_chunk(Delta(reasoning_content=content))]


def tool_call(
    index: int, call_id: str, name: str, args: dict[str, JsonValue]
) -> list[ModelResponseStream]:
    return [
        _chunk(
            Delta(
                tool_calls=[
                    ChatCompletionDeltaToolCall(
                        id=call_id,
                        index=index,
                        function=ResponseFunctionCall(name=name, arguments=""),
                    )
                ]
            )
        ),
        _chunk(
            Delta(
                tool_calls=[
                    ChatCompletionDeltaToolCall(
                        index=index,
                        function=ResponseFunctionCall(arguments=json.dumps(args)),
                    )
                ]
            )
        ),
    ]


def bash(call_id: str, cmd: str) -> list[ModelResponseStream]:
    return tool_call(0, call_id, BASH_TOOL_NAME, {"cmd": cmd})


def generate_answer() -> list[ModelResponseStream]:
    return tool_call(0, "answer", GENERATE_ANSWER_TOOL_NAME, {})


FINAL_ANSWER = text("The final answer.")


class ScriptedLLM(LitellmLLM):
    def __init__(self, steps: list[list[ModelResponseStream]]) -> None:
        super().__init__(
            model_provider="openai",
            api_key=None,
            model_name="mock-model",
            max_input_tokens=100_000,
        )
        self._steps = list(steps)
        self.prompts: list[list[ChatCompletionMessage]] = []
        self.tool_choices: list[ToolChoice | None] = []

    @property
    def config(self) -> LLMConfig:
        return LLMConfig(
            model_provider="mock",
            model_name="mock-model",
            temperature=0.0,
            max_input_tokens=100_000,
        )

    def stream_raw(
        self,
        prompt: list[ChatCompletionMessage],
        tools: list[dict[str, JsonValue]] | None = None,  # noqa: ARG002
        tool_choice: ToolChoice | None = None,
        structured_response_format: dict[str, JsonValue] | None = None,  # noqa: ARG002
        max_tokens: int | None = None,  # noqa: ARG002
        reasoning_effort: ReasoningEffort = ReasoningEffort.AUTO,  # noqa: ARG002
        user_identity: LLMUserIdentity | None = None,  # noqa: ARG002
        stall_timeout_s: int = LLM_SOCKET_READ_TIMEOUT,  # noqa: ARG002
        operation: ProviderOperation | None = None,  # noqa: ARG002
        manage_tool_strictness: bool = False,  # noqa: ARG002
    ) -> Iterator[ModelResponseStream]:
        self.prompts.append(prompt)
        self.tool_choices.append(tool_choice)
        if not self._steps:
            raise AssertionError("LLM called more times than scripted")
        return iter(self._steps.pop(0))


class Run:
    def __init__(
        self,
        llm: ScriptedLLM,
        packets: list[Packet],
        result: RunResult,
    ) -> None:
        self.llm = llm
        self.packets = packets
        self.result = result


def run_agent(
    steps: list[list[ModelResponseStream]],
    *,
    is_reasoning_model: bool,
    max_steps: int | None = None,
) -> Run:
    llm = ScriptedLLM(steps)
    packets: list[Packet] = []
    presenter = ResponsePresenter(Emitter(packets.append))
    presenter.tools[("parent-run", "parent-message", "coding-call")] = ToolRenderer(
        ToolCall(id="coding-call", name=CODING_AGENT_TOOL_NAME, arguments={}),
        Placement(turn_index=TURN_INDEX, tab_index=TAB_INDEX),
        tool_id=1,
    )
    bash_tool = MagicMock(spec=BashTool)
    bash_tool.run.return_value = ToolResult(content="Command output")
    with patch(f"{MODULE}.model_is_reasoning_model", return_value=is_reasoning_model):
        feature = CodingAgent(
            repo="onyx-dot-app/onyx",
            llm=llm,
            token_counter=lambda text: len(text) // 4,
            user_identity=None,
            bash_tool=bash_tool,
        )
        assert {tool.name for tool in feature.tools} == {
            BASH_TOOL_NAME,
            GENERATE_ANSWER_TOOL_NAME,
        }
        run = feature.start(
            max_steps=max_steps or len(steps),
            messages=[UserMessage(content="How does chat work?")],
            parent_run_id="parent-run",
            parent_message_id="parent-message",
            parent_tool_call_id="coding-call",
            on_event=presenter.consume,
        )
        result = run.result(timeout=5)
        assert run.wait_for_idle(5)
    return Run(llm, packets, result)


def thinking_sub_turns(packets: list[Packet]) -> list[int | None]:
    return [
        p.placement.sub_turn_index
        for p in packets
        if isinstance(p.obj, CodingAgentThinkingDelta)
    ]


def reasoning_sub_turns(packets: list[Packet]) -> list[int | None]:
    return [
        p.placement.sub_turn_index for p in packets if isinstance(p.obj, ReasoningStart)
    ]


class TestCodingPlacement:
    @pytest.mark.parametrize("reasoning_model", [True, False])
    def test_narration_after_reasoning_follows_reasoning(
        self, reasoning_model: bool
    ) -> None:
        run = run_agent(
            [
                reasoning("hmm") + text("narration") + bash("b1", "ls"),
                text("more") + generate_answer(),
                FINAL_ANSWER,
            ],
            is_reasoning_model=reasoning_model,
        )

        assert reasoning_sub_turns(run.packets) == []
        assert thinking_sub_turns(run.packets) == [0, 0, 2]
        assert [
            p.obj.content
            for p in run.packets
            if isinstance(p.obj, CodingAgentThinkingDelta)
        ] == ["hmm", "narration", "more"]
        assert all(
            (p.placement.turn_index, p.placement.tab_index) == (TURN_INDEX, TAB_INDEX)
            for p in run.packets
            if isinstance(p.obj, (ReasoningStart, CodingAgentThinkingDelta))
        )


def test_final_reasoning_uses_parent_card_without_duplicate_answer_text() -> None:
    run = run_agent(
        [generate_answer(), reasoning("Final reasoning") + FINAL_ANSWER],
        is_reasoning_model=True,
    )
    assert reasoning_sub_turns(run.packets) == []
    assert (
        "".join(
            packet.obj.content
            for packet in run.packets
            if isinstance(packet.obj, CodingAgentThinkingDelta)
        )
        == "Final reasoning"
    )
    assert all(
        (packet.placement.turn_index, packet.placement.tab_index)
        == (TURN_INDEX, TAB_INDEX)
        for packet in run.packets
        if isinstance(packet.obj, CodingAgentThinkingDelta)
    )
    assert run.result.output.text == "The final answer."


def test_denied_final_call_before_the_limit_takes_one_last_answer_step() -> None:
    run = run_agent(
        [generate_answer(), bash("late", "ls"), FINAL_ANSWER],
        is_reasoning_model=True,
        max_steps=10,
    )

    assert run.llm.tool_choices == [
        ToolChoiceOptions.REQUIRED,
        ToolChoiceOptions.NONE,
        ToolChoiceOptions.NONE,
    ]
    denied = [m for m in run.llm.prompts[2] if isinstance(m, ToolMessage)]
    assert [(m.tool_call_id, m.content) for m in denied][-1] == (
        "late",
        NO_TOOL_CAN_RUN_RESULT,
    )
    assert run.result.stop_reason == RunStatus.COMPLETE
    assert run.result.steps == 3
    # The answer is the third step's message.
    assert (run.result.output.id or "").endswith(":2")
    assert run.result.output.text == "The final answer."
