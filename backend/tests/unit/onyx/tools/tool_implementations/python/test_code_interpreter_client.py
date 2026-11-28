"""Unit tests for CodeInterpreterClient streaming-to-batch fallback.

When the streaming endpoint (/v1/execute/stream) returns 404 — e.g. because the
code-interpreter service is an older version that doesn't support streaming — the
client should transparently fall back to the batch endpoint (/v1/execute) and
convert the batch response into the same stream-event interface.
"""

from __future__ import annotations

from collections.abc import Generator
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from unittest.mock import MagicMock, patch

import pytest
import requests

from onyx.tools.tool_implementations.python import code_interpreter_client as cic
from onyx.tools.tool_implementations.python.code_interpreter_client import (
    CodeInterpreterClient,
    FileInput,
    StreamOutputEvent,
    StreamResultEvent,
)


@pytest.fixture(autouse=True)
def _clear_health_cache() -> Generator[None, None, None]:
    cic._health_cache.clear()
    yield
    cic._health_cache.clear()


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
            captured_payloads.append(
                kwargs["json"]  # ty: ignore[invalid-argument-type]
            )
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


def _make_health_response(status: str = "ok") -> MagicMock:
    """Build a mock ``requests.Response`` for the /health endpoint."""
    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"status": status}
    return resp


def test_health_ok_reports_connected() -> None:
    client = CodeInterpreterClient(base_url="http://fake:9000")

    with patch.object(client.session, "get", return_value=_make_health_response()):
        result = client.health()

    assert result.connected is True
    assert result.error == ""


def test_health_non_ok_status_reports_connected_with_error() -> None:
    """A reachable service reporting a non-ok status is connected but unhealthy."""
    client = CodeInterpreterClient(base_url="http://fake:9000")
    resp = _make_health_response(status="error")
    resp.json.return_value = {"status": "error", "message": "sandbox crashed"}

    with patch.object(client.session, "get", return_value=resp):
        result = client.health()

    assert result.connected is True
    assert result.error == "sandbox crashed"


def test_health_http_error_reports_connected() -> None:
    """4xx/5xx means the service was reachable, so ``connected`` stays True and
    the raw exception text (which may embed the request URL) is not surfaced."""
    client = CodeInterpreterClient(base_url="http://fake:9000")

    resp = MagicMock()
    error_response = MagicMock()
    error_response.status_code = 503
    http_error = requests.HTTPError("503 Server Error for url: http://fake:9000/health")
    http_error.response = error_response
    resp.raise_for_status.side_effect = http_error

    with patch.object(client.session, "get", return_value=resp):
        result = client.health()

    assert result.connected is True
    assert "503" in result.error
    assert client.base_url not in result.error


def test_health_network_error_reports_not_connected() -> None:
    """A network-level failure is reported as disconnected with a sanitized error."""
    client = CodeInterpreterClient(base_url="http://fake:9000")

    with patch.object(
        client.session,
        "get",
        side_effect=requests.ConnectionError("failed to connect to http://fake:9000"),
    ):
        result = client.health()

    assert result.connected is False
    assert result.error == "Unable to reach the Code Interpreter service"
    assert client.base_url not in result.error


def _make_status_response(
    status_code: int, retry_after: str | None = None
) -> MagicMock:
    """Build a mock ``requests.Response`` with an error status and headers."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.headers = {"Retry-After": retry_after} if retry_after is not None else {}
    http_error = requests.HTTPError(f"{status_code} Error")
    http_error.response = resp
    resp.raise_for_status.side_effect = http_error
    return resp


def test_health_parses_new_payload_fields() -> None:
    """0.4.8 adds ``executor_backend`` and ``network_isolation``; they are ignored."""
    client = CodeInterpreterClient(base_url="http://fake:9000")
    resp = _make_health_response()
    resp.json.return_value = {
        "status": "ok",
        "message": None,
        "version": "0.4.8",
        "executor_backend": "kubernetes",
        "network_isolation": "net_admin_init_container+network_policy",
    }

    with patch.object(client.session, "get", return_value=resp):
        result = client.health()

    assert result.healthy is True


@pytest.mark.parametrize("status_code", [429, 503])
def test_execute_retries_admission_rejection_then_succeeds(status_code: int) -> None:
    client = CodeInterpreterClient(base_url="http://fake:9000")
    rejected = _make_status_response(status_code, retry_after="3")
    ok = _make_batch_response(stdout="done\n")

    with (
        patch.object(client.session, "post", side_effect=[rejected, ok]) as post,
        patch.object(cic.time, "sleep") as sleep,
    ):
        result = client.execute(code="print('done')")

    assert result.stdout == "done\n"
    assert post.call_count == 2
    sleep.assert_called_once_with(3.0)
    rejected.close.assert_called_once()


def test_execute_raises_busy_error_when_retries_exhausted() -> None:
    client = CodeInterpreterClient(base_url="http://fake:9000")
    responses = [_make_status_response(429, retry_after="2") for _ in range(3)]

    with (
        patch.object(client.session, "post", side_effect=responses) as post,
        patch.object(cic.time, "sleep") as sleep,
        pytest.raises(cic.CodeInterpreterBusyError) as exc_info,
    ):
        client.execute(code="print(1)")

    assert post.call_count == cic._ADMISSION_MAX_ATTEMPTS
    assert sleep.call_count == cic._ADMISSION_MAX_ATTEMPTS - 1
    assert exc_info.value.status_code == 429
    assert "busy" in str(exc_info.value)


def test_execute_stops_retrying_when_wait_exceeds_budget() -> None:
    """A wait that would overrun the request budget is not taken."""
    client = CodeInterpreterClient(base_url="http://fake:9000")

    with (
        patch.object(
            client.session,
            "post",
            return_value=_make_status_response(503, retry_after="10"),
        ) as post,
        patch.object(cic.time, "sleep") as sleep,
        pytest.raises(cic.CodeInterpreterBusyError),
    ):
        # budget = 0s + 10s; a 10s wait cannot fit
        client.execute(code="print(1)", timeout_ms=0)

    assert post.call_count == 1
    sleep.assert_not_called()


@pytest.mark.parametrize("status_code", [422, 500])
def test_execute_does_not_retry_other_errors(status_code: int) -> None:
    client = CodeInterpreterClient(base_url="http://fake:9000")

    with (
        patch.object(
            client.session,
            "post",
            return_value=_make_status_response(status_code, retry_after="1"),
        ) as post,
        patch.object(cic.time, "sleep") as sleep,
        pytest.raises(requests.HTTPError),
    ):
        client.execute(code="print(1)")

    assert post.call_count == 1
    sleep.assert_not_called()


def _make_sse_response(body: str) -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status = MagicMock()
    resp.iter_lines.return_value = iter(body.split("\n"))
    return resp


def test_execute_streaming_retries_429_before_stream_starts() -> None:
    client = CodeInterpreterClient(base_url="http://fake:9000")
    rejected = _make_status_response(429, retry_after="2")
    stream = _make_sse_response(
        "event: output\n"
        'data: {"stream": "stdout", "data": "hi\\n"}\n'
        "\n"
        "event: result\n"
        'data: {"exit_code": 0, "timed_out": false, "duration_ms": 5, "files": []}\n'
        "\n"
    )

    with (
        patch.object(client.session, "post", side_effect=[rejected, stream]) as post,
        patch.object(cic.time, "sleep") as sleep,
    ):
        events = list(client.execute_streaming(code="print('hi')"))

    assert post.call_count == 2
    assert all(c.args[0].endswith("/v1/execute/stream") for c in post.call_args_list)
    sleep.assert_called_once_with(2.0)
    assert isinstance(events[0], StreamOutputEvent)
    assert isinstance(events[1], StreamResultEvent)


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("2", 2.0),
        ("0", 0.0),
        ("120", cic._ADMISSION_RETRY_AFTER_CAP_SECONDS),
        ("Wed, 21 Oct 2015 07:28:00 GMT", 0.0),
        ("-5", 0.0),
        ("nan", cic._ADMISSION_RETRY_AFTER_FALLBACK_SECONDS),
        (None, cic._ADMISSION_RETRY_AFTER_FALLBACK_SECONDS),
    ],
)
def test_parse_retry_after(header: str | None, expected: float) -> None:
    assert cic._parse_retry_after(header) == expected


def test_execute_caps_large_retry_after() -> None:
    client = CodeInterpreterClient(base_url="http://fake:9000")

    with (
        patch.object(
            client.session,
            "post",
            side_effect=[
                _make_status_response(429, retry_after="3600"),
                _make_batch_response(),
            ],
        ),
        patch.object(cic.time, "sleep") as sleep,
    ):
        client.execute(code="print(1)")

    sleep.assert_called_once_with(cic._ADMISSION_RETRY_AFTER_CAP_SECONDS)


def test_execute_invalid_retry_after_uses_fallback() -> None:
    client = CodeInterpreterClient(base_url="http://fake:9000")

    with (
        patch.object(
            client.session,
            "post",
            side_effect=[
                _make_status_response(429, retry_after="soon"),
                _make_batch_response(),
            ],
        ),
        patch.object(cic.time, "sleep") as sleep,
    ):
        client.execute(code="print(1)")

    sleep.assert_called_once_with(cic._ADMISSION_RETRY_AFTER_FALLBACK_SECONDS)


def test_parse_retry_after_future_http_date_is_capped() -> None:
    retry_at = datetime.now(timezone.utc) + timedelta(hours=1)
    assert cic._parse_retry_after(format_datetime(retry_at, usegmt=True)) == (
        cic._ADMISSION_RETRY_AFTER_CAP_SECONDS
    )


def test_execute_retry_gets_only_the_remaining_budget() -> None:
    """A retry must not get a fresh full timeout: the whole call stays within
    timeout_ms / 1000 + 10."""
    client = CodeInterpreterClient(base_url="http://fake:9000")
    clock = iter([100.0, 100.0, 130.0])
    timeouts: list[float] = []

    def fake_post(*_args: object, **kwargs: object) -> MagicMock:
        timeouts.append(kwargs["timeout"])  # ty: ignore[invalid-argument-type]
        if len(timeouts) == 1:
            return _make_status_response(429, retry_after="3")
        return _make_batch_response()

    with (
        patch.object(client.session, "post", side_effect=fake_post),
        patch.object(cic.time, "sleep"),
        patch.object(cic.time, "monotonic", side_effect=lambda: next(clock, 130.0)),
    ):
        client.execute(code="print(1)", timeout_ms=30000)

    # Budget is 40s from t=100; the retry starts at t=130 with 10s left.
    assert timeouts == [40.0, 10.0]


def test_execute_gives_up_when_wake_up_is_past_the_budget() -> None:
    """A late wake-up after the Retry-After sleep must not send past the deadline."""
    client = CodeInterpreterClient(base_url="http://fake:9000")
    clock = iter([100.0, 100.0, 139.0])

    with (
        patch.object(
            client.session,
            "post",
            return_value=_make_status_response(429, retry_after="3"),
        ) as post,
        patch.object(cic.time, "sleep"),
        patch.object(cic.time, "monotonic", side_effect=lambda: next(clock, 139.0)),
        pytest.raises(cic.CodeInterpreterBusyError),
    ):
        client.execute(code="print(1)", timeout_ms=30000)

    # Budget ends at t=140; waking at t=139 leaves 1s, below the 5s minimum.
    assert post.call_count == 1
