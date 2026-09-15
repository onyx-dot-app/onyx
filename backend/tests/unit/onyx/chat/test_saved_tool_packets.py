"""Saved tool results preserve legacy display forms and validate structured fields."""

import pytest
from pydantic import ValidationError

from onyx.db.models import Tool, ToolCall
from onyx.server.query_and_chat.session_loading import _saved_tool_packets
from onyx.server.query_and_chat.streaming_models import CustomToolDelta, PythonToolDelta
from onyx.tools.tool_implementations.python.python_tool import PythonTool


@pytest.mark.parametrize(
    "response, expected_stdout, expected_files",
    [
        (
            '{"stdout":"report ready","generated_files":[{"file_link":"/api/chat/file/report.csv"}]}',
            "report ready",
            ["report.csv"],
        ),
        ("execution output", "execution output", []),
    ],
)
def test_python_history_reads_partial_summaries_and_text(
    response: str, expected_stdout: str, expected_files: list[str]
) -> None:
    call = ToolCall(
        tool_id=1,
        turn_number=0,
        tab_index=0,
        tool_call_arguments={"code": "print('report ready')"},
        tool_call_response=response,
    )
    packets = _saved_tool_packets(call, Tool(in_code_tool_id=PythonTool.__name__))
    output = next(
        packet.obj for packet in packets if isinstance(packet.obj, PythonToolDelta)
    )
    assert output.stdout == expected_stdout
    assert output.file_ids == expected_files


def test_custom_file_history_validates_references() -> None:
    call = ToolCall(
        tool_id=1,
        turn_number=0,
        tab_index=0,
        tool_call_arguments={},
        tool_call_response='{"tool_name":"export","response_type":"csv","tool_result":{"file_ids":["report.csv"]}}',
    )
    tool = Tool(name="export", display_name="Export", in_code_tool_id=None)
    packets = _saved_tool_packets(call, tool)
    output = next(
        packet.obj for packet in packets if isinstance(packet.obj, CustomToolDelta)
    )
    assert output.file_ids == ["report.csv"]
    assert output.data is None
    call.tool_call_response = (
        '{"tool_name":"export","response_type":"csv","tool_result":{"file_ids":[42]}}'
    )
    with pytest.raises(ValidationError):
        _saved_tool_packets(call, tool)
