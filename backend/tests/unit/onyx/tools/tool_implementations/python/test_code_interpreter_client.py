"""Unit tests for CodeInterpreterClient streaming-to-batch fallback.

When the streaming endpoint (/v1/execute/stream) returns 404 — e.g. because the
code-interpreter service is an older version that doesn't support streaming — the
client should transparently fall back to the batch endpoint (/v1/execute) and
convert the batch response into the same stream-event interface.
"""

from __future__ import annotations

from unittest.mock import MagicMock
from unittest.mock import patch

from onyx.tools.tool_implementations.python.code_interpreter_client import (
    CodeInterpreterClient,
)
from onyx.tools.tool_implementations.python.code_interpreter_client import FileInput
from onyx.tools.tool_implementations.python.code_interpreter_client import (
    StreamOutputEvent,
)
from onyx.tools.tool_implementations.python.code_interpreter_client import (
    StreamResultEvent,
)


def _make_batch_response(
    stdout: str = "",
    stderr: str = "",
    exit_code: int = 0,
    timed_out: bool = False,
    duration_ms: int = 50,
) -> MagicMock:
    """Build a mock ``requests.Response`` for the batch /v1/execute endpoint."""
    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {
        "stdout": stdout,
        "stderr": stderr,
        "exit_code": exit_code,
        "timed_out": timed_out,
        "duration_ms": duration_ms,
        "files": [],
    }
    return resp


def _make_404_response() -> MagicMock:
    """Build a mock ``requests.Response`` that returns 404 (streaming not found)."""
    resp = MagicMock()
    resp.status_code = 404
    return resp


def test_execute_streaming_fallback_to_batch_on_404() -> None:
    """When /v1/execute/stream returns 404, the client should fall back to
    /v1/execute and yield equivalent StreamEvent objects."""

    client = CodeInterpreterClient(base_url="http://fake:9000")

    stream_resp = _make_404_response()
    batch_resp = _make_batch_response(
        stdout="hello world\n",
        stderr="a warning\n",
    )

    urls_called: list[str] = []

    def mock_post(url: str, **_kwargs: object) -> MagicMock:
        urls_called.append(url)
        if url.endswith("/v1/execute/stream"):
            return stream_resp
        if url.endswith("/v1/execute"):
            return batch_resp
        raise AssertionError(f"Unexpected URL: {url}")

    with patch.object(client.session, "post", side_effect=mock_post):
        events = list(client.execute_streaming(code="print('hello world')"))

    # Streaming endpoint was attempted first, then batch
    assert len(urls_called) == 2
    assert urls_called[0].endswith("/v1/execute/stream")
    assert urls_called[1].endswith("/v1/execute")

    # The 404 response must be closed before making the batch call
    stream_resp.close.assert_called_once()

    # _batch_as_stream yields: stdout event, stderr event, result event
    assert len(events) == 3

    assert isinstance(events[0], StreamOutputEvent)
    assert events[0].stream == "stdout"
    assert events[0].data == "hello world\n"

    assert isinstance(events[1], StreamOutputEvent)
    assert events[1].stream == "stderr"
    assert events[1].data == "a warning\n"

    assert isinstance(events[2], StreamResultEvent)
    assert events[2].exit_code == 0
    assert not events[2].timed_out
    assert events[2].duration_ms == 50
    assert events[2].files == []


def test_execute_streaming_fallback_stdout_only() -> None:
    """Fallback with only stdout (no stderr) should yield two events:
    one StreamOutputEvent for stdout and one StreamResultEvent."""

    client = CodeInterpreterClient(base_url="http://fake:9000")

    stream_resp = _make_404_response()
    batch_resp = _make_batch_response(stdout="result: 42\n")

    def mock_post(url: str, **_kwargs: object) -> MagicMock:
        if url.endswith("/v1/execute/stream"):
            return stream_resp
        if url.endswith("/v1/execute"):
            return batch_resp
        raise AssertionError(f"Unexpected URL: {url}")

    with patch.object(client.session, "post", side_effect=mock_post):
        events = list(client.execute_streaming(code="print(42)"))

    # No stderr → only stdout + result
    assert len(events) == 2

    assert isinstance(events[0], StreamOutputEvent)
    assert events[0].stream == "stdout"
    assert events[0].data == "result: 42\n"

    assert isinstance(events[1], StreamResultEvent)
    assert events[1].exit_code == 0


def test_execute_streaming_fallback_preserves_files_param() -> None:
    """When falling back, the files parameter must be forwarded to the
    batch endpoint so staged files are still available for execution."""

    client = CodeInterpreterClient(base_url="http://fake:9000")

    stream_resp = _make_404_response()
    batch_resp = _make_batch_response(stdout="ok\n")

    captured_payloads: list[dict] = []

    def mock_post(url: str, **kwargs: object) -> MagicMock:
        if "json" in kwargs:
            captured_payloads.append(kwargs["json"])  # type: ignore[arg-type]
        if url.endswith("/v1/execute/stream"):
            return stream_resp
        if url.endswith("/v1/execute"):
            return batch_resp
        raise AssertionError(f"Unexpected URL: {url}")

    files_input: list[FileInput] = [{"path": "data.csv", "file_id": "file-abc123"}]

    with patch.object(client.session, "post", side_effect=mock_post):
        events = list(
            client.execute_streaming(
                code="import pandas",
                files=files_input,
            )
        )

    # Both the streaming attempt and the batch fallback should include files
    assert len(captured_payloads) == 2
    for payload in captured_payloads:
        assert payload["files"] == files_input
        assert payload["code"] == "import pandas"

    # Should still yield valid events
    assert any(isinstance(e, StreamResultEvent) for e in events)
