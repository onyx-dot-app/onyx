"""Chat decodes streamed arguments only for tools with live argument display."""

import json
from collections.abc import Iterable
from unittest.mock import patch

import pytest

from onyx.agents.models import ExecutionStatus, RunStatus, StepRecord
from onyx.chat import renderer as renderer_module
from onyx.chat.models import MessageRendering, PresentationMode, ResponseRecord
from onyx.chat.presentation import replay_response
from onyx.chat.renderer import (
    ARGUMENT_REPORT_INTERVAL_SECONDS,
    MessageRenderer,
    ResponseLayout,
    file_tool_progress,
    tool_renderer,
)
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
    GenerationContentEvent,
    GenerationEvent,
    GenerationLifecycleEvent,
    ToolCall,
    ToolCallDeltaEvent,
    ToolCallStartEvent,
    apply_generation_event,
)
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import (
    ApplyPatchStart,
    FileToolProgress,
    Packet,
    PythonToolStart,
    ToolCallArgumentDelta,
)
from onyx.tools.tool_implementations.code_mode.code_mode_tool import CodeModeTool
from onyx.tools.tool_implementations.sandbox.patch import display_patch


class Clock:
    """The renderer's clock: each read moves it `step` seconds."""

    def __init__(self) -> None:
        self.now = 0.0
        self.step = ARGUMENT_REPORT_INTERVAL_SECONDS

    def __call__(self) -> float:
        self.now += self.step
        return self.now


@pytest.fixture(autouse=True)
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    # By default every fragment reports; throttle tests stop the clock.
    clock = Clock()
    monkeypatch.setattr(renderer_module, "monotonic", clock)
    return clock


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
    packets = replay_response(saved, {}, {}, {})
    code = [
        packet.obj.code for packet in packets if isinstance(packet.obj, PythonToolStart)
    ]
    assert code == ["".join(emitted)] == ['print("hello")\n']
    call = saved.steps[0].message.tool_calls[0]
    assert call.raw_arguments == "".join(fragments)
    assert call.arguments == {}
    assert not call.arguments_complete
    assert not saved.steps[0].tools


def test_code_argument_streams_live_as_execute_code() -> None:
    renderer = MessageRenderer(
        MessageRendering(mode=PresentationMode.ANSWER), {}, ResponseLayout()
    )
    renderer.consume(
        ToolCallStartEvent(
            content_index=0, tool_call_id="code-1", tool_name=CodeModeTool.NAME
        )
    )
    [packet] = renderer.consume(
        ToolCallDeltaEvent(content_index=0, arguments_delta='{"code": "print(1)')
    )
    assert isinstance(packet.obj, ToolCallArgumentDelta)
    assert packet.obj.tool_type == CodeModeTool.NAME
    assert packet.obj.argument_deltas == {"code": "print(1)"}


def content_events(events: Iterable[GenerationEvent]) -> list[GenerationContentEvent]:
    return [
        event for event in events if not isinstance(event, GenerationLifecycleEvent)
    ]


def progress(packets: Iterable[Packet]) -> list[FileToolProgress]:
    return [
        packet.obj for packet in packets if isinstance(packet.obj, FileToolProgress)
    ]


PATCH_TEXT = "\n".join(
    [
        "*** Begin Patch",
        "*** Add File: réport 😀.md",
        "+hi",
        "*** Update File: src/app.py",
        "@@",
        "-a",
        "+b",
        "*** Delete File: old.txt",
        "*** End Patch",
    ]
)


@pytest.mark.parametrize(
    "name,arguments,expected",
    [
        (
            "write",
            {"file_path": "réport 😀.md", "content": '# Title\nsnowman ☃\n"q"\nlast'},
            FileToolProgress(tool_name="write", paths=["réport 😀.md"], lines=4),
        ),
        (
            "apply_patch",
            {"input": PATCH_TEXT},
            FileToolProgress(
                tool_name="apply_patch",
                paths=["réport 😀.md", "src/app.py", "old.txt"],
                lines=9,
            ),
        ),
    ],
)
@pytest.mark.parametrize("ensure_ascii", [True, False])
@pytest.mark.parametrize("size", [1, 3, 1000])
def test_file_progress_survives_arbitrary_fragment_boundaries(
    name: str,
    arguments: dict[str, str],
    expected: FileToolProgress,
    ensure_ascii: bool,
    size: int,
) -> None:
    raw = json.dumps(arguments, ensure_ascii=ensure_ascii)
    accumulator = MessageAccumulator()
    renderer = MessageRenderer(MessageRendering(), {}, ResponseLayout())
    shown: list[FileToolProgress] = []
    for offset in range(0, len(raw), size):
        for event in content_events(
            accumulator.add(chunk(raw[offset : offset + size], name=name))
        ):
            shown += progress(renderer.consume(event))
    for event in content_events(accumulator.end()):
        shown += progress(renderer.consume(event))
    assert shown[-1] == expected
    for report in shown:
        # A path shows only once whole, and the line count only grows.
        assert report.paths == expected.paths[: len(report.paths)]
    assert [report.lines for report in shown] == sorted(
        report.lines for report in shown
    )


def test_reports_are_throttled_and_merge_the_text_between_them(clock: Clock) -> None:
    clock.step = 0
    accumulator = MessageAccumulator()
    renderer = MessageRenderer(MessageRendering(), {}, ResponseLayout())
    fragments = [
        '{"file_path": "a.txt", "content": "',
        *["x\\n"] * 1000,
        '"}',
    ]
    shown: list[Packet] = []
    for fragment in fragments:
        for event in content_events(accumulator.add(chunk(fragment, name="write"))):
            shown += renderer.consume(event)
    for event in content_events(accumulator.end()):
        shown += renderer.consume(event)
    # The first fragment reports; the rest wait for the interval or the end.
    assert progress(shown) == [
        FileToolProgress(tool_name="write", paths=["a.txt"], lines=0),
        FileToolProgress(tool_name="write", paths=["a.txt"], lines=1000),
    ]
    assert len(shown) == 2


def test_code_deltas_merge_the_text_between_reports(clock: Clock) -> None:
    clock.step = 0
    accumulator = MessageAccumulator()
    renderer = MessageRenderer(MessageRendering(), {}, ResponseLayout())
    code: list[str] = []
    for fragment in ['{"code": "a', *["b"] * 100, 'c"}']:
        for event in content_events(accumulator.add(chunk(fragment))):
            code += [
                packet.obj.argument_deltas["code"]
                for packet in renderer.consume(event)
                if isinstance(packet.obj, ToolCallArgumentDelta)
            ]
    assert code == ["a"]
    for event in content_events(accumulator.end()):
        code += [
            packet.obj.argument_deltas["code"]
            for packet in renderer.consume(event)
            if isinstance(packet.obj, ToolCallArgumentDelta)
        ]
    assert code == ["a", "b" * 100 + "c"]


def test_parallel_file_calls_report_their_own_progress() -> None:
    accumulator = MessageAccumulator()
    renderer = MessageRenderer(MessageRendering(), {}, ResponseLayout())
    shown: dict[int, FileToolProgress] = {}
    for index, name, fragment in [
        (0, "write", '{"file_path": "a.md", '),
        (1, "edit", '{"file_path": "b.py", '),
        (0, "write", '"content": "1\\n2\\n'),
        (1, "edit", '"old_string": "x\\ny\\nz", "new_string": "w'),
        (0, "write", '3"}'),
        (1, "edit", '"}'),
    ]:
        for event in content_events(accumulator.add(chunk(fragment, index, name))):
            for packet in renderer.consume(event):
                assert isinstance(packet.obj, FileToolProgress)
                shown[packet.placement.tab_index] = packet.obj
    for event in content_events(accumulator.end()):
        renderer.consume(event)
    assert shown == {
        0: FileToolProgress(tool_name="write", paths=["a.md"], lines=3),
        1: FileToolProgress(tool_name="edit", paths=["b.py"], lines=1),
    }


@pytest.mark.parametrize(
    "fragments",
    [
        # A raw newline is not valid inside a JSON string.
        ['{"file_path": "a.txt", "content": "a', "\nb", 'c"}'],
        # Arguments cut off at the token limit never complete.
        ['{"file_path": "a.txt", "content": "a', "bc"],
    ],
)
def test_invalid_file_arguments_stop_progress(fragments: list[str]) -> None:
    accumulator = MessageAccumulator()
    renderer = MessageRenderer(MessageRendering(), {}, ResponseLayout())
    shown: list[FileToolProgress] = []
    for fragment in fragments:
        for event in content_events(accumulator.add(chunk(fragment, name="write"))):
            shown += progress(renderer.consume(event))
    for event in content_events(accumulator.end()):
        assert not renderer.consume(event)
    assert shown[-1].paths == ["a.txt"]
    assert accumulator.message.tool_calls[0].argument_error is not None


def test_an_interrupted_file_call_reports_its_last_fragments(clock: Clock) -> None:
    clock.step = 0
    accumulator = MessageAccumulator()
    renderer = MessageRenderer(MessageRendering(), {}, ResponseLayout())
    accepted = AssistantMessage()
    shown: list[FileToolProgress] = []
    for fragment in ['{"input": "*** Begin Patch\\n', "*** Add File: a.md\\n+x"]:
        for event in accumulator.add(chunk(fragment, name="apply_patch")):
            apply_generation_event(accepted, event)
            if not isinstance(event, GenerationLifecycleEvent):
                shown += progress(renderer.consume(event))
    assert shown == [FileToolProgress(tool_name="apply_patch", lines=1)]
    # The interrupted message has no end event; completing it reports.
    assert progress(renderer.complete(accepted)) == [
        FileToolProgress(tool_name="apply_patch", paths=["a.md"], lines=3)
    ]


@pytest.mark.parametrize(
    "arguments,complete,paths",
    [
        # The last header may still be cut off until its line ends.
        ({"input": "*** Add File: a.md\n*** Delete File: b"}, False, ["a.md"]),
        ({"input": "*** Add File: a.md\n*** Delete File: b"}, True, ["a.md", "b"]),
    ],
)
def test_patch_paths_come_from_whole_header_lines(
    arguments: dict[str, str], complete: bool, paths: list[str]
) -> None:
    assert file_tool_progress("apply_patch", dict(arguments), complete).paths == paths


@pytest.mark.parametrize(
    "arguments,complete,paths",
    [
        # A partial parse keeps a cut-off path as the last key.
        ({"file_path": "rep"}, False, []),
        ({"file_path": "report.md"}, True, ["report.md"]),
        ({"file_path": "report.md", "content": ""}, False, ["report.md"]),
        ({"file_path": None, "content": "x"}, True, []),
    ],
)
def test_a_file_path_shows_once_whole(
    arguments: dict[str, str | None], complete: bool, paths: list[str]
) -> None:
    assert file_tool_progress("write", dict(arguments), complete).paths == paths


def test_a_file_call_with_wrong_typed_arguments_keeps_the_patch_card() -> None:
    # Its streamed progress opened a patch card; the start keeps that card.
    call = ToolCall(id="c", name="write", arguments={"file_path": None, "content": "x"})
    assert [
        packet.obj for packet in tool_renderer(call, Placement(turn_index=0)).start()
    ] == [ApplyPatchStart(patch=display_patch("", None, "x"), tool_name="write")]
