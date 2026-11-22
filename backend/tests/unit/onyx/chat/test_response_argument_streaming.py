"""Chat decodes streamed arguments only for tools with live argument display.

The tests that depend on the report throttle, the flush or the end run under
two clocks: one where each fragment reports, and one that stands still, so
only the first fragment of a call reports before a block boundary or the end.
"""

import json
from collections.abc import Iterable
from typing import Literal, get_args
from unittest.mock import patch

import pytest
from pydantic import JsonValue

from onyx.agents.events import (
    AgentEndEvent,
    MessageEndEvent,
    MessageStartEvent,
    MessageUpdateEvent,
)
from onyx.agents.models import ExecutionStatus, RunStatus, StepRecord
from onyx.chat import renderer as renderer_module
from onyx.chat.emitter import Emitter
from onyx.chat.models import MessageRendering, ResponseRecord
from onyx.chat.presentation import ResponsePresenter, replay_response
from onyx.chat.renderer import (
    ARGUMENT_REPORT_INTERVAL_SECONDS,
    FILE_TOOL_ARGUMENTS,
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
    ExecCommandStart,
    FileToolProgress,
    Packet,
    PacketObj,
    PublishFilesStart,
    PythonToolStart,
    ToolCallArgumentDelta,
    WriteStdinStart,
)
from onyx.tools.tool_implementations.code_mode.code_mode_tool import CodeModeTool
from onyx.tools.tool_implementations.sandbox.models import FileToolName


class Clock:
    """The renderer's clock: each read moves it `step` seconds."""

    def __init__(self, step: float) -> None:
        self.now = 0.0
        self.step = step

    def __call__(self) -> float:
        self.now += self.step
        return self.now


def use_clock(monkeypatch: pytest.MonkeyPatch, step: float) -> Clock:
    clock = Clock(step)
    monkeypatch.setattr(renderer_module, "monotonic", clock)
    return clock


@pytest.fixture(params=[ARGUMENT_REPORT_INTERVAL_SECONDS, 0.0], ids=["each", "stopped"])
def clock(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> Clock:
    return use_clock(monkeypatch, request.param)


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


def content_events(events: Iterable[GenerationEvent]) -> list[GenerationContentEvent]:
    return [
        event for event in events if not isinstance(event, GenerationLifecycleEvent)
    ]


class Live:
    """A provider stream through the accumulator into a renderer. Collects
    every packet, including those of the end events and the completion."""

    def __init__(self, settings: MessageRendering | None = None) -> None:
        self.accumulator = MessageAccumulator()
        self.renderer = MessageRenderer(
            settings or MessageRendering(), {}, ResponseLayout()
        )
        self.accepted = AssistantMessage(id="response:0")
        self.packets: list[Packet] = []

    def _consume(self, events: list[GenerationEvent]) -> None:
        for event in events:
            apply_generation_event(self.accepted, event)
        for event in content_events(events):
            self.packets += self.renderer.consume(event)

    def add(self, fragment: str, index: int = 0, name: str = "run_python") -> None:
        self._consume(self.accumulator.add(chunk(fragment, index, name)))

    def end_calls(self) -> None:
        """The provider's end: each open call's end event."""
        self._consume(self.accumulator.end())

    def end(self) -> None:
        self.end_calls()
        self.packets += self.renderer.complete(self.accepted)

    def interrupt(self, how: Literal["complete", "finish"]) -> None:
        """A stream that stops without end events."""
        self.packets += (
            self.renderer.complete(self.accepted)
            if how == "complete"
            else self.renderer.finish()
        )

    def code(self, placement: Placement | None = None) -> str:
        return "".join(
            str(packet.obj.argument_deltas.get("code", ""))
            for packet in self.packets
            if isinstance(packet.obj, ToolCallArgumentDelta)
            and (placement is None or packet.placement == placement)
        )

    def progress(self) -> list[FileToolProgress]:
        return [
            packet.obj
            for packet in self.packets
            if isinstance(packet.obj, FileToolProgress)
        ]


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
    text: str, size: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_clock(monkeypatch, ARGUMENT_REPORT_INTERVAL_SECONDS)
    raw = json.dumps(
        {"code": text, "count": 3, "enabled": True, "items": [1, {"x": "y"}]}
    )
    live = Live()
    for offset in range(0, len(raw), size):
        live.add(raw[offset : offset + size])
    live.end()
    assert live.code() == text
    assert live.accumulator.message.tool_calls[0].arguments == json.loads(raw)


@pytest.mark.usefixtures("clock")
def test_interleaved_calls_have_independent_arguments_and_identities() -> None:
    live = Live()
    for index, fragment in [
        (0, '{"code":"a'),
        (1, '{"code":"b'),
        (0, 'c"}'),
        (1, 'd"}'),
    ]:
        live.add(fragment, index)
    live.end()
    assert [
        live.code(live.renderer.tool_placement(call.id))
        for call in live.accumulator.message.tool_calls
    ] == ["ac", "bd"]
    assert [call.arguments for call in live.accumulator.message.tool_calls] == [
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
    live = Live()
    with patch("onyx.chat.renderer.parse_partial_object") as parse:
        for fragment in ['{"queries":["first', '","second"]}']:
            live.add(fragment, name="internal_search")
        live.end()
        parse.assert_not_called()
    assert not live.packets
    assert live.accumulator.message.tool_calls[0].arguments == {
        "queries": ["first", "second"]
    }


@pytest.mark.usefixtures("clock")
def test_invalid_python_arguments_stop_display_but_retain_raw_input() -> None:
    live = Live()
    # A raw newline is not valid inside a JSON string.
    fragments = ['{"code":"a', "\nb", 'c"}']
    for fragment in fragments:
        live.add(fragment)
    live.end()
    assert live.code() == "a"
    assert live.accumulator.message.tool_calls[0].raw_arguments == "".join(fragments)
    assert live.accumulator.message.tool_calls[0].argument_error is not None


@pytest.mark.usefixtures("clock")
@pytest.mark.parametrize("name", ["run_python", "write"])
def test_an_invalid_call_shows_every_fragment_it_streamed(name: str) -> None:
    """Arguments cut off at the token limit end the call with an error and
    empty arguments; the end reports what the fragments hold."""
    live = Live()
    key = {"run_python": "code", "write": "content"}[name]
    for fragment in ['{"file_path": "a.md", "' + key + '": "a', "\\nb", "c"]:
        live.add(fragment, name=name)
    live.end_calls()
    assert live.accumulator.message.tool_calls[0].argument_error is not None
    if name == "run_python":
        assert live.code() == "a\nbc"
    else:
        assert live.progress()[-1] == FileToolProgress(
            tool_name="write", paths=["a.md"]
        )


@pytest.mark.usefixtures("clock")
@pytest.mark.parametrize("how", ["complete", "finish"])
def test_interrupted_python_call_replays_the_streamed_code(
    how: Literal["complete", "finish"],
) -> None:
    live = Live()
    fragments = ['{"code":"print(', '\\"hello\\")\\n']
    for fragment in fragments:
        live.add(fragment)
    live.interrupt(how)
    response = ResponseRecord(
        run_id="response",
        status=RunStatus.CANCELLED,
        steps=[
            StepRecord(
                message=live.accepted, generation_status=ExecutionStatus.CANCELLED
            )
        ],
    )
    saved = ResponseRecord.model_validate_json(response.model_dump_json())
    packets = replay_response(saved, {}, {}, {})
    code = [
        packet.obj.code for packet in packets if isinstance(packet.obj, PythonToolStart)
    ]
    assert code == [live.code()] == ['print("hello")\n']
    call = saved.steps[0].message.tool_calls[0]
    assert call.raw_arguments == "".join(fragments)
    assert call.arguments == {}
    assert not call.arguments_complete
    assert not saved.steps[0].tools


def code_deltas(packets: list[Packet], name: str) -> list[str]:
    return [
        packet.obj.argument_deltas["code"]
        for packet in packets
        if isinstance(packet.obj, ToolCallArgumentDelta)
        and packet.obj.tool_type == name
    ]


@pytest.mark.parametrize("name", ["run_python", CodeModeTool.NAME])
def test_code_reports_merge_the_text_between_them(
    monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    use_clock(monkeypatch, 0)
    live = Live()
    for fragment in ['{"code": "a', *["b"] * 100, 'c"}']:
        live.add(fragment, name=name)
    # The first fragment reports; the rest wait for the interval or the end.
    assert code_deltas(live.packets, name) == ["a"]
    live.end()
    assert code_deltas(live.packets, name) == ["a", "b" * 100 + "c"]


def test_a_report_after_the_interval_holds_the_fragments_since_the_last(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Each fragment arrives half an interval after the one before.
    use_clock(monkeypatch, ARGUMENT_REPORT_INTERVAL_SECONDS / 2)
    live = Live()
    for fragment in ['{"code": "a', "b", "c", "d"]:
        live.add(fragment)
    # "b" waits for the interval; "c" reports it with itself; "d" waits.
    assert code_deltas(live.packets, "run_python") == ["a", "bc"]
    live.add('"}')
    live.end()
    assert code_deltas(live.packets, "run_python") == ["a", "bc", "d"]


def test_a_report_at_a_block_boundary_restarts_the_interval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = use_clock(monkeypatch, 0.0)
    live = Live()
    live.add('{"code": "a')
    clock.now = ARGUMENT_REPORT_INTERVAL_SECONDS / 2
    live.add("b")
    # The next call's start reports the held "b".
    clock.now = ARGUMENT_REPORT_INTERVAL_SECONDS
    live.add('{"code": "x', index=1)
    # "c" arrives within the interval of that report, so it waits.
    clock.now = ARGUMENT_REPORT_INTERVAL_SECONDS * 1.5
    live.add("c")
    assert code_deltas(live.packets, "run_python") == ["a", "b", "x"]


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
            FileToolProgress(tool_name="write", paths=["réport 😀.md"]),
        ),
        (
            "apply_patch",
            {"input": PATCH_TEXT},
            FileToolProgress(
                tool_name="apply_patch",
                paths=["réport 😀.md", "src/app.py", "old.txt"],
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
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    use_clock(monkeypatch, ARGUMENT_REPORT_INTERVAL_SECONDS)
    raw = json.dumps(arguments, ensure_ascii=ensure_ascii)
    live = Live()
    for offset in range(0, len(raw), size):
        live.add(raw[offset : offset + size], name=name)
    live.end()
    shown = live.progress()
    assert shown[-1] == expected
    for report in shown:
        # A path shows only once whole.
        assert report.paths == expected.paths[: len(report.paths)]
    # Each report names a new set of files.
    assert all(before != after for before, after in zip(shown, shown[1:], strict=False))


@pytest.mark.usefixtures("clock")
def test_a_file_call_reports_only_when_its_files_change() -> None:
    live = Live()
    live.add('{"file_path": "a.txt", "content": "', name="write")
    for _ in range(1000):
        live.add("x\\n", name="write")
    live.add('"}', name="write")
    live.end()
    assert live.progress() == [FileToolProgress(tool_name="write", paths=["a.txt"])]
    assert len(live.packets) == 1


@pytest.mark.usefixtures("clock")
def test_parallel_file_calls_report_their_own_progress() -> None:
    live = Live()
    for index, name, fragment in [
        (0, "write", '{"file_path": "a.md", '),
        (1, "edit", '{"file_path": "b.py", '),
        (0, "write", '"content": "1\\n2\\n'),
        (1, "edit", '"old_string": "x\\ny\\nz", "new_string": "w'),
        (0, "write", '3"}'),
        (1, "edit", '"}'),
    ]:
        live.add(fragment, index, name)
    live.end()
    last: dict[int, FileToolProgress] = {}
    for packet in live.packets:
        assert isinstance(packet.obj, FileToolProgress)
        last[packet.placement.tab_index] = packet.obj
    assert last == {
        0: FileToolProgress(tool_name="write", paths=["a.md"]),
        1: FileToolProgress(tool_name="edit", paths=["b.py"]),
    }


@pytest.mark.usefixtures("clock")
def test_invalid_file_arguments_stop_progress() -> None:
    live = Live()
    # A raw newline is not valid inside a JSON string.
    for fragment in ['{"file_path": "a.txt", "content": "a', "\nb", 'c"}']:
        live.add(fragment, name="write")
    live.end()
    assert live.progress() == [FileToolProgress(tool_name="write", paths=["a.txt"])]
    assert live.accumulator.message.tool_calls[0].argument_error is not None


@pytest.mark.parametrize("how", ["complete", "finish"])
def test_an_interrupted_file_call_reports_its_last_fragments(
    monkeypatch: pytest.MonkeyPatch, how: Literal["complete", "finish"]
) -> None:
    use_clock(monkeypatch, 0)
    live = Live()
    for fragment in ['{"input": "*** Begin Patch\\n', "*** Add File: a.md\\n+x"]:
        live.add(fragment, name="apply_patch")
    assert live.progress() == [FileToolProgress(tool_name="apply_patch", paths=[])]
    # The interrupted message has no end event; its completion reports.
    live.interrupt(how)
    assert live.progress()[-1] == FileToolProgress(
        tool_name="apply_patch", paths=["a.md"]
    )


@pytest.mark.usefixtures("clock")
def test_a_stopped_file_call_shows_as_on_replay_apart_from_its_progress() -> None:
    output: list[Packet] = []
    presenter = ResponsePresenter(Emitter(output.append))
    raw = '{"file_path": "a.md", "content": "x\\ny'
    call = ToolCall(
        id="write",
        name="write",
        arguments={},
        raw_arguments=raw,
        arguments_complete=False,
    )
    message = AssistantMessage(id="m", content=[call])
    presenter.consume(MessageStartEvent(run_id="r", message_id="m", step_index=0))
    for update in (
        ToolCallStartEvent(content_index=0, tool_call_id=call.id, tool_name=call.name),
        ToolCallDeltaEvent(content_index=0, arguments_delta=raw[:20]),
        ToolCallDeltaEvent(content_index=0, arguments_delta=raw[20:]),
    ):
        presenter.consume(
            MessageUpdateEvent(
                run_id="r", message_id="m", step_index=0, generation_event=update
            )
        )
    presenter.consume(
        MessageEndEvent(
            run_id="r",
            message_id="m",
            step_index=0,
            message=message,
            status=ExecutionStatus.CANCELLED,
        )
    )
    presenter.consume(AgentEndEvent(run_id="r", outcome=RunStatus.CANCELLED))
    replay = replay_response(
        ResponseRecord(
            run_id="r",
            status=RunStatus.CANCELLED,
            steps=[
                StepRecord(message=message, generation_status=ExecutionStatus.CANCELLED)
            ],
        ),
        {},
        {},
        {},
    )
    assert any(isinstance(packet.obj, FileToolProgress) for packet in output)

    def shown(packets: list[Packet]) -> list[tuple[Placement, object]]:
        # Live packets name the model of a multi-model turn; replay does not.
        return [
            (packet.placement.model_copy(update={"model_index": None}), packet.obj)
            for packet in packets
            if not isinstance(packet.obj, FileToolProgress)
        ]

    assert shown(output) == shown(replay)


@pytest.mark.parametrize(
    "text,complete,paths",
    [
        # The last header may still be cut off until its line ends.
        ("*** Add File: a.md\n*** Delete File: b", False, ["a.md"]),
        ("*** Add File: a.md\n*** Delete File: b", True, ["a.md", "b"]),
        # Two hunks of one file name it once.
        ("*** Update File: a.py\n@@\n*** Update File: a.py\n", False, ["a.py"]),
    ],
)
def test_patch_paths_come_from_whole_header_lines(
    text: str, complete: bool, paths: list[str]
) -> None:
    assert file_tool_progress("apply_patch", {"input": text}, complete).paths == paths


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


@pytest.mark.parametrize(
    "name,arguments,start",
    [
        (
            "write",
            {"file_path": None, "content": "x"},
            ApplyPatchStart(patch="", tool_name="write"),
        ),
        (
            "edit",
            {"file_path": 3, "old_string": "a", "new_string": "b"},
            ApplyPatchStart(patch="", tool_name="edit"),
        ),
        (
            "write",
            {"content": "+x\n-y"},
            ApplyPatchStart(patch="", tool_name="write"),
        ),
        (
            "write",
            {"file_path": "", "content": "+x\n-y"},
            ApplyPatchStart(patch="", tool_name="write"),
        ),
        (
            "edit",
            {"old_string": "a", "new_string": "+b"},
            ApplyPatchStart(patch="", tool_name="edit"),
        ),
        ("exec_command", {"cmd": ["ls"]}, ExecCommandStart(cmd="")),
        (
            "write_stdin",
            {"session_id": ["x"]},
            WriteStdinStart(session_id="", chars=""),
        ),
        ("publish_files", {"files": "a.md"}, PublishFilesStart()),
    ],
)
def test_a_call_with_unusable_arguments_keeps_its_own_card(
    name: str, arguments: dict[str, JsonValue], start: PacketObj
) -> None:
    """A tool with its own end packet starts its own card with empty values
    when its arguments are missing or wrong-typed."""
    call = ToolCall(id="c", name=name, arguments=arguments)
    assert [
        packet.obj for packet in tool_renderer(call, Placement(turn_index=0)).start()
    ] == [start]


def test_each_file_tool_names_its_arguments() -> None:
    assert set(FILE_TOOL_ARGUMENTS) == set(get_args(FileToolName))
