"""Chat decodes streamed arguments only for tools with live argument display."""

import json
from unittest.mock import patch

import pytest

from onyx.agents.execution_records import ExecutionStatus, RunStatus
from onyx.agents.models import StepRecord
from onyx.chat.models import MessageRendering, ResponseRecord
from onyx.chat.renderer import MessageRenderer, ResponseLayout
from onyx.chat.response import tool_arguments_for_display
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
    GenerationLifecycleEvent,
    ToolCallDeltaEvent,
    apply_generation_event,
)
from onyx.server.query_and_chat.session_loading import _response_packets
from onyx.server.query_and_chat.streaming_models import (
    PythonToolStart,
    ToolCallArgumentDelta,
)


def chunk(
    fragment: str, index: int = 0, name: str = "run_python"
) -> ModelResponseStream:
    return ModelResponseStream(
        id="model",
        created="1",
        choice=StreamingChoice(
            delta=Delta(
                tool_calls=[
                    ChatCompletionDeltaToolCall(
                        index=index,
                        id=f"call-{index}",
                        function=ResponseFunctionCall(name=name, arguments=fragment),
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
        ResponseLayout(),
    )
    emitted: list[str] = []
    for offset in range(0, len(raw), size):
        for event in accumulator.add(chunk(raw[offset : offset + size])):
            if isinstance(event, GenerationLifecycleEvent):
                continue
            emitted.extend(
                packet.obj.argument_deltas.get("code", "")
                for packet in renderer.consume(event)
                if isinstance(packet.obj, ToolCallArgumentDelta)
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
        ResponseLayout(),
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
                if isinstance(packet.obj, ToolCallArgumentDelta):
                    call_id = str(packet.placement.tab_index)
                    contents[call_id] = contents.get(
                        call_id, ""
                    ) + packet.obj.argument_deltas.get("code", "")
    accumulator.end()
    assert contents == {"0": "ac", "1": "bd"}
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


def test_partial_events_retain_raw_arguments_until_completion() -> None:
    accumulator = MessageAccumulator()
    events = accumulator.add(
        chunk('{"count":3,"nested":{"items":[1,true]},"code":"partial')
    )
    partial = events[-1]
    assert isinstance(partial, ToolCallDeltaEvent)
    assert (
        partial.arguments_delta
        == '{"count":3,"nested":{"items":[1,true]},"code":"partial'
    )
    accumulator.add(chunk(' text"}'))
    assert partial.arguments_delta.endswith('"partial')
    assert accumulator.message.tool_calls[0].arguments == {}
    accumulator.finalize()
    assert accumulator.message.tool_calls[0].arguments == {
        "count": 3,
        "nested": {"items": [1, True]},
        "code": "partial text",
    }


def test_search_arguments_do_not_need_partial_json_parsing() -> None:
    accumulator = MessageAccumulator()
    renderer = MessageRenderer(MessageRendering(), {}, ResponseLayout())
    with patch("onyx.chat.renderer.parse_partial_object") as parse:
        for fragment in ['{"queries":["first', '","second"]}']:
            for event in accumulator.add(chunk(fragment, name="internal_search")):
                if not isinstance(event, GenerationLifecycleEvent):
                    assert not renderer.consume(event)
        for event in accumulator.end():
            if not isinstance(event, GenerationLifecycleEvent):
                assert not renderer.consume(event)
        parse.assert_not_called()
    assert accumulator.message.tool_calls[0].arguments == {
        "queries": ["first", "second"]
    }


def test_invalid_python_arguments_stop_display_but_retain_raw_input() -> None:
    accumulator = MessageAccumulator()
    renderer = MessageRenderer(MessageRendering(), {}, ResponseLayout())
    fragments = ['{"code":"a', "\nb", 'c"}']
    code: list[str] = []
    for fragment in fragments:
        for event in accumulator.add(chunk(fragment)):
            if not isinstance(event, GenerationLifecycleEvent):
                code.extend(
                    packet.obj.argument_deltas.get("code", "")
                    for packet in renderer.consume(event)
                    if isinstance(packet.obj, ToolCallArgumentDelta)
                )
    for event in accumulator.end():
        if not isinstance(event, GenerationLifecycleEvent):
            assert not renderer.consume(event)
    assert "".join(code) == "a"
    assert accumulator.message.tool_calls[0].raw_arguments == "".join(fragments)
    assert accumulator.message.tool_calls[0].argument_error is not None


def test_interrupted_think_tool_replays_the_streamed_reasoning() -> None:
    accumulator = MessageAccumulator()
    settings = MessageRendering(think_tool="think")
    live = MessageRenderer(settings, {}, ResponseLayout())
    accepted = AssistantMessage()
    for fragment in ['{"reasoning":"check ', "the sources"]:
        for event in accumulator.add(chunk(fragment, name="think")):
            apply_generation_event(accepted, event)
            if not isinstance(event, GenerationLifecycleEvent):
                live.consume(event)
    saved = AssistantMessage.model_validate_json(accepted.model_dump_json())
    replay = MessageRenderer(settings, {}, ResponseLayout())
    replay.complete(saved)
    assert live.reasoning == replay.reasoning == "check the sources"
    assert tool_arguments_for_display(saved.tool_calls[0]) == {
        "reasoning": "check the sources"
    }
    assert saved.tool_calls[0].arguments == {}
    assert not saved.tool_calls[0].arguments_complete


def test_interrupted_python_call_replays_the_streamed_code() -> None:
    accumulator = MessageAccumulator()
    live = MessageRenderer(MessageRendering(), {}, ResponseLayout())
    accepted = AssistantMessage(id="response:0")
    emitted: list[str] = []
    fragments = ['{"code":"print(', '\\"hello\\")\\n']
    for fragment in fragments:
        for event in accumulator.add(chunk(fragment)):
            apply_generation_event(accepted, event)
            if not isinstance(event, GenerationLifecycleEvent):
                emitted.extend(
                    packet.obj.argument_deltas.get("code", "")
                    for packet in live.consume(event)
                    if isinstance(packet.obj, ToolCallArgumentDelta)
                )
    response = ResponseRecord(
        run_id="response",
        status=RunStatus.CANCELLED,
        steps=[
            StepRecord(message=accepted, generation_status=ExecutionStatus.CANCELLED)
        ],
    )
    saved = ResponseRecord.model_validate_json(response.model_dump_json())
    packets = _response_packets(saved, {}, {}, {})
    code = [
        packet.obj.code for packet in packets if isinstance(packet.obj, PythonToolStart)
    ]
    assert code == ["".join(emitted)] == ['print("hello")\n']
    call = saved.steps[0].message.tool_calls[0]
    assert call.raw_arguments == "".join(fragments)
    assert call.arguments == {}
    assert not call.arguments_complete
    assert not saved.steps[0].tools
