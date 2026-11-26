"""The ACP translation of calls whose pre-start packets precede their start."""

from typing import Any

import pytest

from onyx.server.query_and_chat.acp_stream import ChatAcpTranslator
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import (
    ApplyPatchStart,
    CodeModeStart,
    FileToolProgress,
    Packet,
    PacketObj,
    PythonToolStart,
    SectionEnd,
    ToolCallArgumentDelta,
)


def test_file_tool_progress_opens_the_call_that_its_start_continues() -> None:
    translator = ChatAcpTranslator()

    def translate(obj: PacketObj) -> list[dict[str, Any]]:
        packet = Packet(placement=Placement(turn_index=0), obj=obj)
        return list(translator.translate(packet.model_dump(mode="json")))

    [opened] = translate(FileToolProgress(tool_name="write", paths=[]))
    assert {
        key: opened[key] for key in ("sessionUpdate", "kind", "title", "status")
    } == {
        "sessionUpdate": "tool_call",
        "kind": "edit",
        "title": "Editing files",
        "status": "in_progress",
    }
    call_id = opened["toolCallId"]

    # Later progress updates the open call; only the start names it again.
    [progress] = translate(FileToolProgress(tool_name="write", paths=["a.md"]))
    assert progress["sessionUpdate"] == "tool_call_update"
    assert progress["toolCallId"] == call_id
    assert "title" not in progress
    [started] = translate(ApplyPatchStart(patch="", tool_name="write"))
    assert (started["toolCallId"], started["title"]) == (call_id, "Editing files")
    [ended] = translate(SectionEnd())
    assert (ended["toolCallId"], ended["status"]) == (call_id, "completed")


@pytest.mark.parametrize(
    "tool_type,start,title",
    [
        ("run_python", PythonToolStart(code="print(1)"), "Running Python"),
        ("execute_code", CodeModeStart(code="print(1)"), "Running code"),
    ],
)
def test_streamed_code_opens_a_call_that_its_start_renames(
    tool_type: str, start: PacketObj, title: str
) -> None:
    translator = ChatAcpTranslator()

    def translate(obj: PacketObj) -> list[dict[str, Any]]:
        packet = Packet(placement=Placement(turn_index=0), obj=obj)
        return list(translator.translate(packet.model_dump(mode="json")))

    [opened] = translate(
        ToolCallArgumentDelta(tool_type=tool_type, argument_deltas={"code": "print(1)"})
    )
    assert (opened["sessionUpdate"], opened["kind"], opened["title"]) == (
        "tool_call",
        "execute",
        "Writing code",
    )
    [started] = translate(start)
    assert (started["sessionUpdate"], started["title"]) == (
        "tool_call_update",
        title,
    )
