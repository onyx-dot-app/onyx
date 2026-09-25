"""Think tool token processor: streamed reasoning and the flushed tool call."""

import json
from typing import Any

import pytest

from onyx.deep_research.dr_mock_tools import THINK_TOOL_NAME
from onyx.deep_research.utils import create_think_tool_token_processor
from onyx.llm.model_response import ChatCompletionDeltaToolCall, Delta, FunctionCall


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
