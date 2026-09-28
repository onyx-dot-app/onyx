"""Python output reaches chat once per chunk, with complete results for reload."""

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from onyx.agents.tools import ToolInvocation, ToolProgress
from onyx.chat.renderer import ToolRenderer
from onyx.llm.cancellation import CancellationSignal
from onyx.llm.models import ToolCall
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import PythonToolDelta
from onyx.tools.interface import ToolContext
from onyx.tools.models import LlmPythonExecutionResult, PythonExecutionDelta
from onyx.tools.tool_implementations.python.code_interpreter_client import (
    StreamErrorEvent,
    StreamOutputEvent,
    StreamResultEvent,
)
from onyx.tools.tool_implementations.python.python_tool import PythonTool

TOOL_MODULE = "onyx.tools.tool_implementations.python.python_tool"


@pytest.mark.parametrize("fails", [False, True])
def test_python_streams_chunks_without_repeating_final_output(fails: bool) -> None:
    chunks = [
        StreamOutputEvent(stream="stdout", data="hello\n"),
        StreamOutputEvent(stream="stderr", data="warning\n"),
        StreamOutputEvent(stream="stdout", data="hello\n"),
    ]
    client = MagicMock()
    client.execute_streaming.return_value = iter(
        [
            *chunks,
            StreamErrorEvent(message="execution failed")
            if fails
            else StreamResultEvent(
                exit_code=0, timed_out=False, duration_ms=10, files=[]
            ),
        ]
    )
    progress: list[ToolProgress] = []
    with (
        patch(f"{TOOL_MODULE}.CodeInterpreterClient") as client_class,
        patch(f"{TOOL_MODULE}.get_default_file_store"),
    ):
        client_class.return_value.__enter__.return_value = client
        result = PythonTool(tool_id=1, chat_session_id=uuid4()).run(
            ToolInvocation(
                call_id="python-1",
                arguments={"code": "print('hello')"},
                cancellation=CancellationSignal(),
                update=progress.append,
            ),
            ToolContext(chat_files=[]),
        )

    assert [update.details for update in progress] == [
        PythonExecutionDelta(stdout="hello\n"),
        PythonExecutionDelta(stderr="warning\n"),
        PythonExecutionDelta(stdout="hello\n"),
    ]
    call = ToolCall(id="python-1", name=PythonTool.NAME, arguments={})
    renderer = ToolRenderer(call, Placement(turn_index=0))
    packets = [
        packet for update in progress for packet in renderer.update(update.details)
    ]
    assert [
        (packet.obj.stdout, packet.obj.stderr)
        for packet in packets
        if isinstance(packet.obj, PythonToolDelta)
    ] == [("hello\n", ""), ("", "warning\n"), ("hello\n", "")]
    details = result.details
    assert isinstance(details, LlmPythonExecutionResult)
    if not fails:
        assert details.stdout == "hello\nhello\n"
        assert details.stderr == "warning\n"
        # A truncated saved result must not replace or repeat live output.
        details.stdout = "hello [truncated]"
    final_packets = renderer.complete(result)
    final_output = [
        packet.obj
        for packet in final_packets
        if isinstance(packet.obj, PythonToolDelta)
    ]
    assert len(final_output) == 1
    assert final_output[0].stdout == ""
    assert final_output[0].stderr == (details.error if fails else "")

    restored = ToolRenderer(call, Placement(turn_index=0)).complete(result)
    saved_output = [
        packet.obj for packet in restored if isinstance(packet.obj, PythonToolDelta)
    ]
    assert saved_output[0].stdout == details.stdout
    assert saved_output[0].stderr == details.stderr
