"""Unit tests for PythonTool file-upload caching.

Verifies that PythonTool reuses code-interpreter file IDs across multiple
run() calls within the same session instead of re-uploading identical content
on every agent loop iteration.
"""

from unittest.mock import MagicMock
from unittest.mock import patch

from onyx.tools.models import ChatFile
from onyx.tools.models import PythonToolOverrideKwargs
from onyx.tools.tool_implementations.python.code_interpreter_client import (
    StreamResultEvent,
)
from onyx.tools.tool_implementations.python.python_tool import PythonTool

TOOL_MODULE = "onyx.tools.tool_implementations.python.python_tool"


def _make_stream_result() -> StreamResultEvent:
    return StreamResultEvent(
        exit_code=0,
        timed_out=False,
        duration_ms=10,
        files=[],
    )


def _make_tool() -> PythonTool:
    emitter = MagicMock()
    return PythonTool(tool_id=1, emitter=emitter)


def _make_override(files: list[ChatFile]) -> PythonToolOverrideKwargs:
    return PythonToolOverrideKwargs(chat_files=files)


def _run_tool(tool: PythonTool, mock_client: MagicMock, files: list[ChatFile]) -> None:
    """Call tool.run() with a mocked CodeInterpreterClient context manager."""
    from onyx.server.query_and_chat.placement import Placement

    mock_client.execute_streaming.return_value = iter([_make_stream_result()])

    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=mock_client)
    ctx.__exit__ = MagicMock(return_value=False)

    placement = Placement(turn_index=0, tab_index=0)
    override = _make_override(files)

    with patch(f"{TOOL_MODULE}.CodeInterpreterClient", return_value=ctx):
        tool.run(placement=placement, override_kwargs=override, code="print('hi')")


# ---------------------------------------------------------------------------
# Cache hit: same content uploaded in a second call reuses the file_id
# ---------------------------------------------------------------------------


@patch(f"{TOOL_MODULE}.CODE_INTERPRETER_BASE_URL", "http://fake:8000")
def test_same_file_uploaded_only_once_across_two_runs() -> None:
    tool = _make_tool()
    client = MagicMock()
    client.upload_file.return_value = "file-id-abc"

    pptx_content = b"fake pptx bytes"
    files = [ChatFile(filename="report.pptx", content=pptx_content)]

    _run_tool(tool, client, files)
    _run_tool(tool, client, files)

    # upload_file should only have been called once across both runs
    client.upload_file.assert_called_once_with(pptx_content, "report.pptx")


@patch(f"{TOOL_MODULE}.CODE_INTERPRETER_BASE_URL", "http://fake:8000")
def test_cached_file_id_is_staged_on_second_run() -> None:
    tool = _make_tool()
    client = MagicMock()
    client.upload_file.return_value = "file-id-abc"

    files = [ChatFile(filename="data.pptx", content=b"content")]

    _run_tool(tool, client, files)

    # On the second run, execute_streaming should still receive the file
    client.execute_streaming.return_value = iter([_make_stream_result()])
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=client)
    ctx.__exit__ = MagicMock(return_value=False)

    from onyx.server.query_and_chat.placement import Placement

    placement = Placement(turn_index=1, tab_index=0)
    with patch(f"{TOOL_MODULE}.CodeInterpreterClient", return_value=ctx):
        tool.run(
            placement=placement,
            override_kwargs=_make_override(files),
            code="print('hi')",
        )

    # The second execute_streaming call should include the file
    _, kwargs = client.execute_streaming.call_args
    staged_files = kwargs.get("files") or []
    assert any(f["file_id"] == "file-id-abc" for f in staged_files)


# ---------------------------------------------------------------------------
# Cache miss: different content triggers a new upload
# ---------------------------------------------------------------------------


@patch(f"{TOOL_MODULE}.CODE_INTERPRETER_BASE_URL", "http://fake:8000")
def test_different_file_content_uploaded_separately() -> None:
    tool = _make_tool()
    client = MagicMock()
    client.upload_file.side_effect = ["file-id-v1", "file-id-v2"]

    file_v1 = ChatFile(filename="report.pptx", content=b"version 1")
    file_v2 = ChatFile(filename="report.pptx", content=b"version 2")

    _run_tool(tool, client, [file_v1])
    _run_tool(tool, client, [file_v2])

    assert client.upload_file.call_count == 2


@patch(f"{TOOL_MODULE}.CODE_INTERPRETER_BASE_URL", "http://fake:8000")
def test_multiple_distinct_files_each_uploaded_once() -> None:
    tool = _make_tool()
    client = MagicMock()
    client.upload_file.side_effect = ["id-a", "id-b"]

    files = [
        ChatFile(filename="a.pptx", content=b"aaa"),
        ChatFile(filename="b.xlsx", content=b"bbb"),
    ]

    _run_tool(tool, client, files)
    _run_tool(tool, client, files)

    # Two distinct files — each uploaded exactly once
    assert client.upload_file.call_count == 2


# ---------------------------------------------------------------------------
# No cross-instance sharing: a fresh PythonTool re-uploads everything
# ---------------------------------------------------------------------------


@patch(f"{TOOL_MODULE}.CODE_INTERPRETER_BASE_URL", "http://fake:8000")
def test_new_tool_instance_re_uploads_file() -> None:
    client = MagicMock()
    client.upload_file.side_effect = ["id-session-1", "id-session-2"]

    files = [ChatFile(filename="deck.pptx", content=b"slide data")]

    tool_session_1 = _make_tool()
    _run_tool(tool_session_1, client, files)

    tool_session_2 = _make_tool()
    _run_tool(tool_session_2, client, files)

    # Different instances — each uploads independently
    assert client.upload_file.call_count == 2


# ---------------------------------------------------------------------------
# Upload failure: failed upload is not cached, retried next run
# ---------------------------------------------------------------------------


@patch(f"{TOOL_MODULE}.CODE_INTERPRETER_BASE_URL", "http://fake:8000")
def test_upload_failure_not_cached() -> None:
    tool = _make_tool()
    client = MagicMock()
    # First call raises, second succeeds
    client.upload_file.side_effect = [Exception("network error"), "file-id-ok"]

    files = [ChatFile(filename="slides.pptx", content=b"data")]

    # First run — upload fails, file is skipped but not cached
    _run_tool(tool, client, files)

    # Second run — should attempt upload again
    _run_tool(tool, client, files)

    assert client.upload_file.call_count == 2
