"""Decoded argument events remain independent of packet rendering."""

import json

import pytest

from onyx.chat.models import MessageRendering
from onyx.chat.renderer import MessageRenderer
from onyx.llm.litellm_conversion import MessageAccumulator
from onyx.llm.litellm_models import (
    ChatCompletionDeltaToolCall,
    Delta,
    ModelResponseStream,
    ResponseFunctionCall,
    StreamingChoice,
)
from onyx.llm.models import GenerationLifecycleEvent, ToolCallDeltaEvent
from onyx.server.query_and_chat.streaming_models import (
    ItemDelta,
    PacketIdentity,
    ToolArgumentsDelta,
)


def chunk(fragment: str, index: int = 0) -> ModelResponseStream:
    return ModelResponseStream(
        id="model",
        created="1",
        choice=StreamingChoice(
            delta=Delta(
                tool_calls=[
                    ChatCompletionDeltaToolCall(
                        index=index,
                        id=f"call-{index}",
                        function=ResponseFunctionCall(name="code", arguments=fragment),
                    )
                ]
            )
        ),
    )


@pytest.mark.parametrize(
    "text",
    [
        "",
        "hello",
        'print("hello")',
        "line1\nline2",
        "\tindent",
        "back\\slash",
        "a/b",
        "snowman ☃",
        "emoji 😀",
        "\r\n",
        'quote "',
        "many words " * 20,
    ],
)
@pytest.mark.parametrize("size", [1, 3, 1000])
def test_decoded_strings_survive_arbitrary_fragment_boundaries(
    text: str, size: int
) -> None:
    raw = json.dumps(
        {"code": text, "count": 3, "enabled": True, "items": [1, {"x": "y"}]}
    )
    accumulator = MessageAccumulator()
    renderer = MessageRenderer(
        MessageRendering(),
        {},
        PacketIdentity(response_id=1, run_id="root", message_id="root:0"),
    )
    emitted: list[str] = []
    for offset in range(0, len(raw), size):
        for event in accumulator.add(chunk(raw[offset : offset + size])):
            if isinstance(event, GenerationLifecycleEvent):
                continue
            emitted.extend(
                packet.obj.delta.arguments.get("code", "")
                for packet in renderer.consume(event)
                if isinstance(packet.obj, ItemDelta)
                and isinstance(packet.obj.delta, ToolArgumentsDelta)
            )
    for event in accumulator.end():
        if not isinstance(event, GenerationLifecycleEvent):
            renderer.consume(event)
    assert "".join(emitted) == text
    assert accumulator.message.tool_calls[0].arguments == json.loads(raw)


def test_interleaved_calls_have_independent_arguments_and_identities() -> None:
    accumulator = MessageAccumulator()
    renderer = MessageRenderer(
        MessageRendering(),
        {},
        PacketIdentity(response_id=1, run_id="root", message_id="root:0"),
    )
    contents: dict[str, str] = {}
    for index, fragment in [
        (0, '{"code":"a'),
        (1, '{"code":"b'),
        (0, 'c"}'),
        (1, 'd"}'),
    ]:
        for event in accumulator.add(chunk(fragment, index)):
            if isinstance(event, GenerationLifecycleEvent):
                continue
            for packet in renderer.consume(event):
                if isinstance(packet.obj, ItemDelta) and isinstance(
                    packet.obj.delta, ToolArgumentsDelta
                ):
                    assert packet.identity is not None
                    call_id = packet.identity.tool_call_id
                    assert call_id is not None
                    contents[call_id] = contents.get(
                        call_id, ""
                    ) + packet.obj.delta.arguments.get("code", "")
    accumulator.end()
    assert contents == {"call-0": "ac", "call-1": "bd"}
    assert [call.arguments for call in accumulator.message.tool_calls] == [
        {"code": "ac"},
        {"code": "bd"},
    ]


@pytest.mark.parametrize(
    "raw", ['{"code":oops}', '{"code":"unfinished', "[]", '{"code":1} trailing']
)
def test_malformed_arguments_remain_error_calls(raw: str) -> None:
    accumulator = MessageAccumulator()
    for char in raw:
        accumulator.add(chunk(char))
    accumulator.end()
    assert accumulator.message.tool_calls[0].argument_error


def test_partial_events_include_non_string_arguments() -> None:
    accumulator = MessageAccumulator()
    events = accumulator.add(
        chunk('{"count":3,"nested":{"items":[1,true]},"code":"partial')
    )
    partial = events[-1]
    assert isinstance(partial, ToolCallDeltaEvent)
    assert partial.tool_call.arguments == {
        "count": 3,
        "nested": {"items": [1, True]},
        "code": "partial",
    }
    accumulator.add(chunk(' text"}'))
    assert partial.tool_call.arguments["code"] == "partial"
    accumulator.finalize()
    assert accumulator.message.tool_calls[0].arguments["code"] == "partial text"
