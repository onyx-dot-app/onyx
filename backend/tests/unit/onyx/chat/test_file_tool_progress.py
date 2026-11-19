"""File tool calls report throttled progress while their arguments stream."""

import json
from collections.abc import Iterator

import pytest
from pydantic import JsonValue

from onyx.chat import file_tool_progress
from onyx.chat.models import MessageRendering
from onyx.chat.renderer import MessageRenderer, ResponseLayout
from onyx.llm.models import (
    ToolCall,
    ToolCallDeltaEvent,
    ToolCallEndEvent,
    ToolCallStartEvent,
)
from onyx.server.query_and_chat.streaming_models import (
    FileToolProgress,
    Packet,
    ToolCallArgumentDelta,
)


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Iterator[Clock]:
    clock = Clock()
    monkeypatch.setattr(file_tool_progress.time, "monotonic", clock)
    yield clock


class Stream:
    """One streamed file tool call, rendered as the browser receives it."""

    def __init__(self, tool_name: str) -> None:
        self.renderer = MessageRenderer(MessageRendering(), {}, ResponseLayout())
        self.tool_name = tool_name
        self.raw = ""
        self.renderer.consume(
            ToolCallStartEvent(
                content_index=0, tool_call_id="call", tool_name=tool_name
            )
        )

    def add(self, fragment: str) -> list[FileToolProgress]:
        self.raw += fragment
        return self._progress(
            self.renderer.consume(
                ToolCallDeltaEvent(content_index=0, arguments_delta=fragment)
            )
        )

    def end(self) -> list[FileToolProgress]:
        arguments: dict[str, JsonValue] = json.loads(self.raw)
        return self._progress(
            self.renderer.consume(
                ToolCallEndEvent(
                    content_index=0,
                    tool_call=ToolCall(
                        id="call", name=self.tool_name, arguments=arguments
                    ),
                )
            )
        )

    def _progress(self, packets: list[Packet]) -> list[FileToolProgress]:
        result: list[FileToolProgress] = []
        for packet in packets:
            assert isinstance(packet.obj, ToolCallArgumentDelta)
            assert packet.obj.tool_type == self.tool_name
            assert packet.obj.argument_deltas == {}
            assert packet.placement == self.renderer.tool_placement("call")
            assert packet.obj.file_progress is not None
            result.append(packet.obj.file_progress)
        return result


def test_write_reports_the_path_and_growing_line_count(clock: Clock) -> None:
    stream = Stream("write")
    # The first fragment opens the card before the path arrives.
    assert stream.add('{"file_path": "rep') == [FileToolProgress()]
    clock.now += 1
    # A cut-off path is not shown.
    assert stream.add("ort.md") == []
    clock.now += 1
    assert stream.add('", "content": "# Title\\nline two\\n') == [
        FileToolProgress(paths=["report.md"], lines=2)
    ]
    clock.now += 1
    assert stream.add("third") == [FileToolProgress(paths=["report.md"], lines=3)]
    clock.now += 1
    assert stream.add('\\nfourth"}') == [FileToolProgress(paths=["report.md"], lines=4)]
    # The complete arguments add nothing new.
    assert stream.end() == []


def test_progress_is_throttled_and_the_end_reports_the_final_count(
    clock: Clock,
) -> None:
    stream = Stream("write")
    reports = stream.add('{"file_path": "a.txt", "content": "')
    for index in range(1000):
        clock.now = index * 0.001
        reports += stream.add("x\\n")
    # One report on the first fragment, then one per interval of 0.25 s.
    assert len(reports) == 4
    assert reports[-1].lines < 1000
    stream.add('"}')
    assert stream.end() == [FileToolProgress(paths=["a.txt"], lines=1000)]


def test_edit_counts_the_lines_of_the_new_text(clock: Clock) -> None:
    stream = Stream("edit")
    stream.add('{"file_path": "src/app.py", "old_string": "a\\nb\\nc\\n"')
    clock.now += 1
    assert stream.add(', "new_string": "x\\ny') == [
        FileToolProgress(paths=["src/app.py"], lines=2)
    ]


def test_apply_patch_names_files_as_their_headers_complete(clock: Clock) -> None:
    stream = Stream("apply_patch")
    assert stream.add(
        '{"input": "*** Begin Patch\\n*** Add File: docs/new.md\\n+hello\\n*** Upd'
    ) == [FileToolProgress(paths=["docs/new.md"], lines=4)]
    clock.now += 1
    # The header spans two reports.
    assert stream.add("ate File: src/app.py\\n@@\\n-old\\n+new\\n") == [
        FileToolProgress(paths=["docs/new.md", "src/app.py"], lines=7)
    ]
    # Within the interval: only the end reports the last header.
    assert stream.add('*** Delete File: old.txt\\n*** End Patch"}') == []
    assert stream.end() == [
        FileToolProgress(paths=["docs/new.md", "src/app.py", "old.txt"], lines=9)
    ]
