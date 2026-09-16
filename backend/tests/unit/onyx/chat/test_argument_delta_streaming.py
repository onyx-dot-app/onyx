"""Decoded argument events remain independent of packet rendering."""

import json

import pytest

from onyx.agents.events import MessageUpdateEvent
from onyx.chat.renderer import PacketRenderer, RenderConfig
from onyx.llm.litellm_conversion import MessageAccumulator
from onyx.llm.litellm_models import (
    ChatCompletionDeltaToolCall,
    Delta,
    FunctionCall,
    ModelResponseStream,
    StreamingChoice,
)
from onyx.llm.models import ToolCallDeltaEvent
from onyx.server.query_and_chat.streaming_models import (
    PacketIdentity,
    ToolCallArgumentDelta,
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
                        function=FunctionCall(name="code", arguments=fragment),
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
    renderer = PacketRenderer(
        RenderConfig(argument_tools={"code"}),
        PacketIdentity(response_id=1, run_id="root", message_id="root:0"),
    )
    emitted: list[str] = []
    for offset in range(0, len(raw), size):
        for event in accumulator.add(chunk(raw[offset : offset + size])):
            emitted.extend(
                packet.obj.argument_deltas.get("code", "")
                for packet in renderer.consume_items(
                    MessageUpdateEvent(
                        run_id="root", step_index=0, generation_event=event
                    ).items
                )
                if isinstance(packet.obj, ToolCallArgumentDelta)
            )
    for event in accumulator.end():
        renderer.consume_items(
            MessageUpdateEvent(
                run_id="root", step_index=0, generation_event=event
            ).items
        )
    assert "".join(emitted) == text
    assert accumulator.message.tool_calls[0].arguments == json.loads(raw)


def test_interleaved_calls_have_independent_arguments_and_identities() -> None:
    accumulator = MessageAccumulator()
    renderer = PacketRenderer(
        RenderConfig(argument_tools={"code"}),
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
            for packet in renderer.consume_items(
                MessageUpdateEvent(
                    run_id="root", step_index=0, generation_event=event
                ).items
            ):
                if isinstance(packet.obj, ToolCallArgumentDelta):
                    assert packet.identity is not None
                    call_id = packet.identity.tool_call_id
                    assert call_id is not None
                    contents[call_id] = contents.get(
                        call_id, ""
                    ) + packet.obj.argument_deltas.get("code", "")
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


def test_argument_rendering_is_opt_in() -> None:
    accumulator = MessageAccumulator()
    renderer = PacketRenderer(
        RenderConfig(),
        PacketIdentity(response_id=1, run_id="root", message_id="root:0"),
    )
    packets = [
        packet
        for event in accumulator.add(chunk('{"code":"hello"}'))
        for packet in renderer.consume_items(
            MessageUpdateEvent(
                run_id="root", step_index=0, generation_event=event
            ).items
        )
    ]
    assert not any(isinstance(packet.obj, ToolCallArgumentDelta) for packet in packets)
    assert accumulator.finish().tool_calls[0].arguments == {"code": "hello"}


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
    assert accumulator.finish().tool_calls[0].arguments["code"] == "partial text"
