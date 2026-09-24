"""Think tool token processor: streamed reasoning and the flushed tool call."""

import json
from typing import Any

import pytest

from onyx.chat.llm_step import run_llm_step_pkt_generator
from onyx.deep_research.dr_mock_tools import THINK_TOOL_NAME
from onyx.deep_research.utils import create_think_tool_token_processor
from onyx.llm.interfaces import ToolChoiceOptions
from onyx.llm.model_response import ChatCompletionDeltaToolCall, Delta, FunctionCall
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import Packet, ReasoningDelta
from tests.unit.onyx.deep_research.fakes import (
    ScriptedLLM,
    summarize,
    tool_call_chunks,
)


def _args_delta(arguments: str, name: str | None = None) -> Delta:
    return Delta(
        tool_calls=[
            ChatCompletionDeltaToolCall(
                id="think_1" if name else None,
                index=0,
                function=FunctionCall(name=name, arguments=arguments),
            )
        ]
    )


def _process(argument_chunks: list[str]) -> tuple[str, Delta | None]:
    processor = create_think_tool_token_processor()
    state: Any = None
    reasoning = ""
    for delta in [_args_delta("", THINK_TOOL_NAME)] + [
        _args_delta(chunk) for chunk in argument_chunks
    ]:
        out, state = processor(delta, state)
        if out is not None:
            assert out.tool_calls == []
            reasoning += out.reasoning_content or ""
    flushed, _ = processor(None, state)
    return reasoning, flushed


@pytest.mark.parametrize(
    "text",
    [
        "plan the search",
        "x",
        'line one\nline two\ttabbed "quoted" and C:\\path\\new',
        "ends with a backslash \\",
        'ends with a quote "',
    ],
)
@pytest.mark.parametrize("chunk_size", [1, 2, 3, 1000])
def test_streams_full_reasoning_and_flushes_unchanged_call(
    text: str, chunk_size: int
) -> None:
    arguments = json.dumps({"reasoning": text})
    chunks = [
        arguments[i : i + chunk_size] for i in range(0, len(arguments), chunk_size)
    ]

    reasoning, flushed = _process(chunks)

    assert reasoning == text
    assert flushed is not None
    [call] = flushed.tool_calls
    assert call.id == "think_1"
    assert call.function is not None
    assert call.function.name == THINK_TOOL_NAME
    assert call.function.arguments == arguments


def test_compact_json_without_space() -> None:
    reasoning, _ = _process(['{"reasoning":"a', 'b"', "}"])

    assert reasoning == "ab"


def test_passes_through_deltas_without_think_tool() -> None:
    processor = create_think_tool_token_processor()
    delta = Delta(content="hello")

    out, state = processor(delta, None)
    flushed, _ = processor(None, state)

    assert out is delta
    assert flushed is None


def test_llm_step_streams_and_saves_full_reasoning() -> None:
    llm = ScriptedLLM(
        [
            tool_call_chunks(
                "think_1",
                THINK_TOOL_NAME,
                ['{"reasoning": "', "first idea, second", ' idea"}'],
            )
        ]
    )
    gen = run_llm_step_pkt_generator(
        history=[],
        tool_definitions=[],
        tool_choice=ToolChoiceOptions.REQUIRED,
        llm=llm,
        placement=Placement(turn_index=1),
        state_container=None,
        citation_processor=None,
        custom_token_processor=create_think_tool_token_processor(),
        is_deep_research=True,
    )
    packets: list[Packet] = []
    while True:
        try:
            packets.append(next(gen))
        except StopIteration as stop:
            result, has_reasoned = stop.value
            break

    summary = summarize(packets)
    assert summary[0] == ("ReasoningStart", 1, 0, None)
    assert summary[-1] == ("ReasoningDone", 1, 0, None)
    assert {s[0] for s in summary[1:-1]} == {"ReasoningDelta"}
    streamed = "".join(
        p.obj.reasoning for p in packets if isinstance(p.obj, ReasoningDelta)
    )
    assert streamed == "first idea, second idea"
    assert has_reasoned is True
    assert result.reasoning == streamed
    assert result.tool_calls is not None
    assert [
        (tc.tool_call_id, tc.tool_name, tc.tool_args, tc.placement)
        for tc in result.tool_calls
    ] == [
        (
            "think_1",
            THINK_TOOL_NAME,
            {"reasoning": "first idea, second idea"},
            Placement(turn_index=1, tab_index=0),
        )
    ]
