"""Sub-turn placement in the coding agent loop (``run_coding_agent_call``)."""

import json
import queue
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from unittest.mock import patch

from onyx.chat.emitter import Emitter
from onyx.coding_agent.mock_tools import (
    BASH_TOOL_NAME,
    CODING_AGENT_QUERY_KEY,
    CODING_AGENT_REPO_KEY,
    GENERATE_ANSWER_TOOL_NAME,
)
from onyx.coding_agent.models import CodingAgentCallResult
from onyx.deep_research.dr_mock_tools import (
    THINK_TOOL_NAME,
    THINK_TOOL_RESPONSE_MESSAGE,
)
from onyx.llm.interfaces import LLMConfig
from onyx.llm.model_response import (
    ChatCompletionDeltaToolCall,
    Delta,
    FunctionCall,
    ModelResponseStream,
    StreamingChoice,
)
from onyx.llm.models import SystemMessage, ToolMessage
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import (
    CodingAgentThinkingDelta,
    Packet,
    ReasoningDelta,
    ReasoningStart,
)
from onyx.tools.fake_tools import coding_agent
from onyx.tools.models import ToolCallKickoff, ToolResponse

MODULE = "onyx.tools.fake_tools.coding_agent"
TURN_INDEX = 3
TAB_INDEX = 1


def _chunk(delta: Delta) -> ModelResponseStream:
    return ModelResponseStream(id="c", created="0", choice=StreamingChoice(delta=delta))


def text(content: str) -> list[ModelResponseStream]:
    return [_chunk(Delta(content=content))]


def reasoning(content: str) -> list[ModelResponseStream]:
    return [_chunk(Delta(reasoning_content=content))]


def tool_call(
    index: int, call_id: str, name: str, args: dict[str, Any]
) -> list[ModelResponseStream]:
    return [
        _chunk(
            Delta(
                tool_calls=[
                    ChatCompletionDeltaToolCall(
                        id=call_id,
                        index=index,
                        function=FunctionCall(name=name, arguments=""),
                    )
                ]
            )
        ),
        _chunk(
            Delta(
                tool_calls=[
                    ChatCompletionDeltaToolCall(
                        index=index,
                        function=FunctionCall(arguments=json.dumps(args)),
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


class ScriptedLLM:
    def __init__(self, steps: list[list[ModelResponseStream]]) -> None:
        self._steps = list(steps)
        self.requests: list[dict[str, Any]] = []
        self.config = LLMConfig(
            model_provider="mock",
            model_name="mock-model",
            temperature=0.0,
            max_input_tokens=100_000,
        )

    def stream(self, **kwargs: Any) -> Iterator[ModelResponseStream]:
        self.requests.append(kwargs)
        if not self._steps:
            raise AssertionError("LLM called more times than scripted")
        return iter(self._steps.pop(0))


class FakeBashTool:
    def __init__(self, tool_id: int, session_id: str, emitter: Emitter) -> None:
        self.tool_id = tool_id
        self.session_id = session_id
        self.emitter = emitter

    def run(
        self,
        placement: Placement,  # noqa: ARG002
        override_kwargs: Any,  # noqa: ARG002
        **llm_kwargs: Any,
    ) -> ToolResponse:
        cmd = llm_kwargs["cmd"]
        return ToolResponse(rich_response=None, llm_facing_response=f"out:{cmd}")


class Run:
    def __init__(
        self,
        llm: ScriptedLLM,
        packets: list[Packet],
        result: CodingAgentCallResult | None,
    ) -> None:
        self.llm = llm
        self.packets = packets
        self.result = result


def run_agent(
    steps: list[list[ModelResponseStream]], *, is_reasoning_model: bool
) -> Run:
    llm = ScriptedLLM(steps)
    merged_queue: queue.Queue[tuple[int, Packet | Exception | object]] = queue.Queue()

    @contextmanager
    def fake_setup_session(
        repo: str,  # noqa: ARG001
        github_token: str | None,  # noqa: ARG001
    ) -> Iterator[str]:
        yield "session-1"

    with (
        patch(f"{MODULE}._setup_session", fake_setup_session),
        patch(f"{MODULE}.BashTool", FakeBashTool),
        patch(f"{MODULE}.model_is_reasoning_model", return_value=is_reasoning_model),
    ):
        result = coding_agent.run_coding_agent_call(
            coding_agent_call=ToolCallKickoff(
                tool_call_id="coding-call",
                tool_name="coding_agent",
                tool_args={
                    CODING_AGENT_QUERY_KEY: "How does chat work?",
                    CODING_AGENT_REPO_KEY: "onyx-dot-app/onyx",
                },
                placement=Placement(turn_index=TURN_INDEX, tab_index=TAB_INDEX),
            ),
            emitter=Emitter(merged_queue=merged_queue),
            llm=llm,  # ty: ignore[invalid-argument-type]
            token_counter=lambda s: len(s) // 4,
            user_identity=None,
            github_token="tok",
        )

    packets: list[Packet] = []
    while not merged_queue.empty():
        _, item = merged_queue.get_nowait()
        assert isinstance(item, Packet)
        packets.append(item)
    return Run(llm, packets, result)


def system_prompt(request: dict[str, Any]) -> str:
    first = request["prompt"][0]
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
        assert "you are on cycle 1" in system_prompt(run.llm.requests[1])

        tool_msgs = [
            m for m in run.llm.requests[1]["prompt"] if isinstance(m, ToolMessage)
        ]
        assert [(m.tool_call_id, m.content) for m in tool_msgs] == [
            ("t1", THINK_TOOL_RESPONSE_MESSAGE)
        ]
        assert run.result == CodingAgentCallResult(answer="The final answer.")

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

        prompts = [system_prompt(r) for r in run.llm.requests[:3]]
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
