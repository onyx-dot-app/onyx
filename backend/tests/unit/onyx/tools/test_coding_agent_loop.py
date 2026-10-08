"""Coding runtime output retains main's reasoning and narration placement."""

import json
from collections.abc import Iterator
from unittest.mock import MagicMock, patch

from pydantic import JsonValue

from onyx.agents.models import RunResult
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
from onyx.deep_research.tool_definitions import (
    THINK_TOOL_NAME,
    THINK_TOOL_RESPONSE_MESSAGE,
)
from onyx.llm.interfaces import LLMConfig, LLMUserIdentity
from onyx.llm.model_request import ChatCompletionMessage, SystemMessage, ToolMessage
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
    ToolResult,
    UserMessage,
)
from onyx.llm.multi_llm import LitellmLLM, ProviderOperation
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import (
    CodingAgentThinkingDelta,
    Packet,
    ReasoningDelta,
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


def think(call_id: str, thought: str) -> list[ModelResponseStream]:
    return tool_call(0, call_id, THINK_TOOL_NAME, {"reasoning": thought})


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
        tool_choice: ToolChoice | None = None,  # noqa: ARG002
        structured_response_format: dict[str, JsonValue] | None = None,  # noqa: ARG002
        max_tokens: int | None = None,  # noqa: ARG002
        reasoning_effort: ReasoningEffort = ReasoningEffort.AUTO,  # noqa: ARG002
        user_identity: LLMUserIdentity | None = None,  # noqa: ARG002
        stall_timeout_s: int = LLM_SOCKET_READ_TIMEOUT,  # noqa: ARG002
        operation: ProviderOperation | None = None,  # noqa: ARG002
    ) -> Iterator[ModelResponseStream]:
        self.prompts.append(prompt)
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
    steps: list[list[ModelResponseStream]], *, is_reasoning_model: bool
) -> Run:
    llm = ScriptedLLM(steps)
    packets: list[Packet] = []
    presenter = ResponsePresenter(Emitter(packets.append))
    presenter.tools[("parent-message", "coding-call")] = ToolRenderer(
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
        run = feature.start(
            max_steps=len(steps),
            messages=[UserMessage(content="How does chat work?")],
            parent_run_id="parent-run",
            parent_message_id="parent-message",
            parent_tool_call_id="coding-call",
            on_event=presenter.consume,
        )
        result = run.result(timeout=5)
        assert run.wait_for_idle(5)
    return Run(llm, packets, result)


def system_prompt(prompt: list[ChatCompletionMessage]) -> str:
    first = prompt[0]
    assert isinstance(first, SystemMessage)
    return first.content


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


class TestThinkPlacement:
    def test_think_tool_reasoning_advances_sub_turn(self) -> None:
        run = run_agent(
            [
                think("t1", "I should look at the repo layout first"),
                text("narration") + bash("b1", "ls"),
                generate_answer(),
                FINAL_ANSWER,
            ],
            is_reasoning_model=False,
        )

        assert reasoning_sub_turns(run.packets) == [0]
        reasoning_text = "".join(
            p.obj.reasoning for p in run.packets if isinstance(p.obj, ReasoningDelta)
        )
        assert reasoning_text.startswith("I should look at the repo")
        assert thinking_sub_turns(run.packets) == [1]
        assert "you are on cycle 1" in system_prompt(run.llm.prompts[1])

        tool_msgs = [m for m in run.llm.prompts[1] if isinstance(m, ToolMessage)]
        assert [(m.tool_call_id, m.content) for m in tool_msgs] == [
            ("t1", THINK_TOOL_RESPONSE_MESSAGE)
        ]
        assert run.result.output.text == "The final answer."

    def test_silent_think_keeps_sub_turn(self) -> None:
        run = run_agent(
            [
                think("t1", "plan"),
                text("narration") + bash("b1", "ls"),
                text("more") + generate_answer(),
                FINAL_ANSWER,
            ],
            is_reasoning_model=True,
        )

        prompts = [system_prompt(r) for r in run.llm.prompts[:3]]
        assert "you are on cycle 0" in prompts[0]
        assert "you are on cycle 1" in prompts[1]
        assert "you are on cycle 2" in prompts[2]
        assert thinking_sub_turns(run.packets) == [0, 1]

    def test_think_with_narration_advances_sub_turn(self) -> None:
        run = run_agent(
            [
                text("let me plan") + think("t1", "plan"),
                text("narration") + bash("b1", "ls"),
                generate_answer(),
                FINAL_ANSWER,
            ],
            is_reasoning_model=True,
        )

        assert thinking_sub_turns(run.packets) == [0, 1]

    def test_narration_after_reasoning_follows_reasoning(self) -> None:
        run = run_agent(
            [
                reasoning("hmm") + text("narration") + bash("b1", "ls"),
                text("more") + generate_answer(),
                FINAL_ANSWER,
            ],
            is_reasoning_model=True,
        )

        assert reasoning_sub_turns(run.packets) == [0]
        assert thinking_sub_turns(run.packets) == [1, 2]
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
    assert reasoning_sub_turns(run.packets) == [None]
    assert (
        "".join(
            packet.obj.reasoning
            for packet in run.packets
            if isinstance(packet.obj, ReasoningDelta)
        )
        == "Final reasoning"
    )
    assert not thinking_sub_turns(run.packets)
    assert run.result.output.text == "The final answer."
