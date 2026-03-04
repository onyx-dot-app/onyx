"""Tests for _extract_referenced_file_descriptors in save_chat.py.

Verifies that only code interpreter generated files actually referenced
in the assistant's message text are extracted as FileDescriptors for
cross-turn persistence.
"""

from onyx.chat.save_chat import _extract_referenced_file_descriptors
from onyx.file_store.models import ChatFileType
from onyx.tools.models import PythonExecutionFile
from onyx.tools.models import ToolCallInfo


def _make_tool_call_info(
    generated_files: list[PythonExecutionFile] | None = None,
    tool_name: str = "python",
) -> ToolCallInfo:
    return ToolCallInfo(
        parent_tool_call_id=None,
        turn_index=0,
        tab_index=0,
        tool_name=tool_name,
        tool_call_id="tc_1",
        tool_id=1,
        reasoning_tokens=None,
        tool_call_arguments={"code": "print('hi')"},
        tool_call_response="{}",
        generated_files=generated_files,
    )


def test_returns_empty_when_no_generated_files() -> None:
    tool_call = _make_tool_call_info(generated_files=None)
    result = _extract_referenced_file_descriptors([tool_call], "some message")
    assert result == []


def test_returns_empty_when_file_not_referenced() -> None:
    files = [
        PythonExecutionFile(
            filename="chart.png",
            file_link="http://localhost/api/chat/file/abc-123",
        )
    ]
    tool_call = _make_tool_call_info(generated_files=files)
    result = _extract_referenced_file_descriptors([tool_call], "Here is your answer.")
    assert result == []


def test_extracts_referenced_file() -> None:
    file_id = "abc-123-def"
    files = [
        PythonExecutionFile(
            filename="chart.png",
            file_link=f"http://localhost/api/chat/file/{file_id}",
        )
    ]
    tool_call = _make_tool_call_info(generated_files=files)
    message = (
        f"Here is the chart: [chart.png](http://localhost/api/chat/file/{file_id})"
    )

    result = _extract_referenced_file_descriptors([tool_call], message)

    assert len(result) == 1
    assert result[0]["id"] == file_id
    assert result[0]["type"] == ChatFileType.IMAGE
    assert result[0]["name"] == "chart.png"


def test_filters_unreferenced_files() -> None:
    referenced_id = "ref-111"
    unreferenced_id = "unref-222"
    files = [
        PythonExecutionFile(
            filename="chart.png",
            file_link=f"http://localhost/api/chat/file/{referenced_id}",
        ),
        PythonExecutionFile(
            filename="data.csv",
            file_link=f"http://localhost/api/chat/file/{unreferenced_id}",
        ),
    ]
    tool_call = _make_tool_call_info(generated_files=files)
    message = f"Here is the chart: [chart.png](http://localhost/api/chat/file/{referenced_id})"

    result = _extract_referenced_file_descriptors([tool_call], message)

    assert len(result) == 1
    assert result[0]["id"] == referenced_id
    assert result[0]["name"] == "chart.png"


def test_extracts_from_multiple_tool_calls() -> None:
    id_1 = "file-aaa"
    id_2 = "file-bbb"
    tc1 = _make_tool_call_info(
        generated_files=[
            PythonExecutionFile(
                filename="plot.png",
                file_link=f"http://localhost/api/chat/file/{id_1}",
            )
        ]
    )
    tc2 = _make_tool_call_info(
        generated_files=[
            PythonExecutionFile(
                filename="report.csv",
                file_link=f"http://localhost/api/chat/file/{id_2}",
            )
        ]
    )
    message = (
        f"[plot.png](http://localhost/api/chat/file/{id_1}) "
        f"and [report.csv](http://localhost/api/chat/file/{id_2})"
    )

    result = _extract_referenced_file_descriptors([tc1, tc2], message)

    assert len(result) == 2
    ids = {d["id"] for d in result}
    assert ids == {id_1, id_2}


def test_csv_file_type() -> None:
    file_id = "csv-123"
    files = [
        PythonExecutionFile(
            filename="data.csv",
            file_link=f"http://localhost/api/chat/file/{file_id}",
        )
    ]
    tool_call = _make_tool_call_info(generated_files=files)
    message = f"[data.csv](http://localhost/api/chat/file/{file_id})"

    result = _extract_referenced_file_descriptors([tool_call], message)

    assert len(result) == 1
    assert result[0]["type"] == ChatFileType.CSV


def test_unknown_extension_defaults_to_plain_text() -> None:
    file_id = "bin-456"
    files = [
        PythonExecutionFile(
            filename="output.xyz",
            file_link=f"http://localhost/api/chat/file/{file_id}",
        )
    ]
    tool_call = _make_tool_call_info(generated_files=files)
    message = f"[output.xyz](http://localhost/api/chat/file/{file_id})"

    result = _extract_referenced_file_descriptors([tool_call], message)

    assert len(result) == 1
    assert result[0]["type"] == ChatFileType.PLAIN_TEXT


def test_skips_tool_calls_without_generated_files() -> None:
    file_id = "img-789"
    tc_no_files = _make_tool_call_info(generated_files=None)
    tc_empty = _make_tool_call_info(generated_files=[])
    tc_with_files = _make_tool_call_info(
        generated_files=[
            PythonExecutionFile(
                filename="result.png",
                file_link=f"http://localhost/api/chat/file/{file_id}",
            )
        ]
    )
    message = f"[result.png](http://localhost/api/chat/file/{file_id})"

    result = _extract_referenced_file_descriptors(
        [tc_no_files, tc_empty, tc_with_files], message
    )

    assert len(result) == 1
    assert result[0]["id"] == file_id
