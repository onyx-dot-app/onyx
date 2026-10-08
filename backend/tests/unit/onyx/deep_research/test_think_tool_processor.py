"""Think tool arguments stream in full and remain intact in recorded messages."""

import json

import pytest

from onyx.chat.models import MessageRendering
from onyx.chat.renderer import MessageRenderer, ResponseLayout
from onyx.deep_research.tool_definitions import THINK_TOOL_NAME
from onyx.llm.model_response import (
    ChatCompletionDeltaToolCall,
    Delta,
    MessageAccumulator,
    ModelResponseStream,
    ResponseFunctionCall,
    StreamingChoice,
)
from onyx.llm.models import (
    AssistantMessage,
    TextDeltaEvent,
    ToolCallDeltaEvent,
    ToolCallStartEvent,
)


def _chunk(delta: Delta) -> ModelResponseStream:
    return ModelResponseStream(
        id="think", created="1", choice=StreamingChoice(index=0, delta=delta)
    )


def _process(argument_chunks: list[str]) -> tuple[str, AssistantMessage]:
    accumulator = MessageAccumulator()
    renderer = MessageRenderer(
        MessageRendering(think_tool=THINK_TOOL_NAME), {}, ResponseLayout()
    )
    for index, arguments in enumerate(argument_chunks):
        delta = Delta(
            tool_calls=[
                ChatCompletionDeltaToolCall(
                    id="think_1" if index == 0 else None,
                    index=0,
                    function=ResponseFunctionCall(
                        name=THINK_TOOL_NAME if index == 0 else None,
                        arguments=arguments,
                    ),
                )
            ]
        )
        for event in accumulator.add(_chunk(delta)):
            if isinstance(event, (ToolCallStartEvent, ToolCallDeltaEvent)):
                renderer.consume(event)
    accumulator.finalize()
    renderer.complete(accumulator.message)
    return renderer.reasoning, accumulator.message


@pytest.mark.parametrize(
    "text",
    [
        "plan the search",
        "x",
        'line one\nline two\ttabbed "quoted" and C:\\path\\new',
        "ends with a backslash \\",
        'ends with a quote "',
        "unicode caf\u00e9 and emoji \U0001f600",
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
    assert call.name == THINK_TOOL_NAME
    assert call.arguments == {"reasoning": text}


def test_compact_json_without_space() -> None:
    reasoning, _ = _process(['{"reasoning":"a', 'b"', "}"])

    assert reasoning == "ab"


def test_passes_through_deltas_without_think_tool() -> None:
    accumulator = MessageAccumulator()
    renderer = MessageRenderer(
        MessageRendering(think_tool=THINK_TOOL_NAME), {}, ResponseLayout()
    )
    for event in accumulator.add(_chunk(Delta(content="hello"))):
        if isinstance(event, (TextDeltaEvent, ToolCallStartEvent, ToolCallDeltaEvent)):
            renderer.consume(event)
    assert renderer.answer == "hello"
    assert renderer.reasoning == ""
