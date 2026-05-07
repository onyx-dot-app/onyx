"""Unit tests for CodeInterpreterClient streaming-to-batch fallback.

When the streaming endpoint (/v1/execute/stream) returns 404 — e.g. because the
code-interpreter service is an older version that doesn't support streaming — the
client should transparently fall back to the batch endpoint (/v1/execute) and
convert the batch response into the same stream-event interface.
"""

from __future__ import annotations

import time
from collections.abc import Generator
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from onyx.tools.tool_implementations.python import code_interpreter_client as cic
from onyx.tools.tool_implementations.python.code_interpreter_client import (
    BashExecResponse,
)
from onyx.tools.tool_implementations.python.code_interpreter_client import (
    CodeInterpreterClient,
)
from onyx.tools.tool_implementations.python.code_interpreter_client import (
    CodeInterpreterVersionError,
)
from onyx.tools.tool_implementations.python.code_interpreter_client import (
    CreateSessionResponse,
)
from onyx.tools.tool_implementations.python.code_interpreter_client import FileInput
from onyx.tools.tool_implementations.python.code_interpreter_client import (
    HealthResponse,
)
from onyx.tools.tool_implementations.python.code_interpreter_client import (
    StreamOutputEvent,
)
from onyx.tools.tool_implementations.python.code_interpreter_client import (
    StreamResultEvent,
)


def _prime_health(base_url: str, version: str) -> None:
    """Populate the module-level health cache so version checks don't hit
    the network."""
    cic._health_cache[base_url] = (
        time.monotonic(),
        HealthResponse(healthy=True, version=version),
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


def _make_create_session_response(
    session_id: str = "sess-abc123",
    expires_at: float = 1234567890.0,
) -> MagicMock:
    """Build a mock ``requests.Response`` for POST /v1/sessions."""
    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {
        "session_id": session_id,
        "expires_at": expires_at,
    }
    return resp


def _make_bash_response(
    stdout: str = "",
    stderr: str = "",
    exit_code: int | None = 0,
    timed_out: bool = False,
    duration_ms: int = 25,
) -> MagicMock:
    """Build a mock ``requests.Response`` for POST /v1/sessions/{id}/bash."""
    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {
        "stdout": stdout,
        "stderr": stderr,
        "exit_code": exit_code,
        "timed_out": timed_out,
        "duration_ms": duration_ms,
    }
    return resp


def test_create_session_default_payload() -> None:
    """create_session with default args should POST {ttl_seconds: 900} and
    return a parsed CreateSessionResponse."""

    client = CodeInterpreterClient(base_url="http://fake:9000")
    _prime_health(client.base_url, version="0.4.0")

    captured_url: list[str] = []
    captured_payloads: list[dict] = []

    def mock_post(url: str, **kwargs: object) -> MagicMock:
        captured_url.append(url)
        if "json" in kwargs:
            captured_payloads.append(
                kwargs["json"]  # ty: ignore[invalid-argument-type]
            )
        return _make_create_session_response()

    with patch.object(client.session, "post", side_effect=mock_post):
        result = client.create_session()

    assert len(captured_url) == 1
    assert captured_url[0] == "http://fake:9000/v1/sessions"
    assert captured_payloads == [{"ttl_seconds": 15 * 60}]

    assert isinstance(result, CreateSessionResponse)
    assert result.session_id == "sess-abc123"
    assert result.expires_at == 1234567890.0


def test_create_session_with_ttl_and_files() -> None:
    """create_session should forward custom ttl_seconds and the files list."""

    client = CodeInterpreterClient(base_url="http://fake:9000")
    _prime_health(client.base_url, version="0.4.0")

    files_input: list[FileInput] = [{"path": "data.csv", "file_id": "file-xyz"}]
    captured_payloads: list[dict] = []

    def mock_post(_url: str, **kwargs: object) -> MagicMock:
        if "json" in kwargs:
            captured_payloads.append(
                kwargs["json"]  # ty: ignore[invalid-argument-type]
            )
        return _make_create_session_response(session_id="sess-with-files")

    with patch.object(client.session, "post", side_effect=mock_post):
        result = client.create_session(ttl_seconds=60, files=files_input)

    assert captured_payloads == [{"ttl_seconds": 60, "files": files_input}]
    assert result.session_id == "sess-with-files"


def test_create_session_omits_files_when_none() -> None:
    """create_session must not include a 'files' key when files is None."""

    client = CodeInterpreterClient(base_url="http://fake:9000")
    _prime_health(client.base_url, version="0.4.0")

    captured_payloads: list[dict] = []

    def mock_post(_url: str, **kwargs: object) -> MagicMock:
        if "json" in kwargs:
            captured_payloads.append(
                kwargs["json"]  # ty: ignore[invalid-argument-type]
            )
        return _make_create_session_response()

    with patch.object(client.session, "post", side_effect=mock_post):
        client.create_session(ttl_seconds=120, files=None)

    assert len(captured_payloads) == 1
    assert "files" not in captured_payloads[0]


def test_delete_session_calls_correct_url() -> None:
    """delete_session should issue a DELETE to /v1/sessions/{session_id}."""

    client = CodeInterpreterClient(base_url="http://fake:9000")
    _prime_health(client.base_url, version="0.4.0")

    delete_resp = MagicMock()
    delete_resp.status_code = 204
    delete_resp.raise_for_status = MagicMock()

    captured_urls: list[str] = []

    def mock_delete(url: str, **_kwargs: object) -> MagicMock:
        captured_urls.append(url)
        return delete_resp

    with patch.object(client.session, "delete", side_effect=mock_delete):
        result = client.delete_session("sess-abc123")

    assert result is None
    assert captured_urls == ["http://fake:9000/v1/sessions/sess-abc123"]
    delete_resp.raise_for_status.assert_called_once()


def test_delete_session_propagates_http_errors() -> None:
    """An HTTP error from the upstream service must propagate, not be swallowed."""

    client = CodeInterpreterClient(base_url="http://fake:9000")
    _prime_health(client.base_url, version="0.4.0")

    delete_resp = MagicMock()
    delete_resp.raise_for_status.side_effect = RuntimeError("boom")

    with patch.object(client.session, "delete", return_value=delete_resp):
        try:
            client.delete_session("sess-abc123")
        except RuntimeError as e:
            assert str(e) == "boom"
        else:
            raise AssertionError("Expected RuntimeError to propagate")


def test_execute_bash_in_session_default_timeout() -> None:
    """execute_bash_in_session should POST cmd + default timeout_ms and return
    a parsed BashExecResponse."""

    client = CodeInterpreterClient(base_url="http://fake:9000")
    _prime_health(client.base_url, version="0.4.0")

    captured_urls: list[str] = []
    captured_payloads: list[dict] = []
    captured_timeouts: list[float] = []

    def mock_post(url: str, **kwargs: object) -> MagicMock:
        captured_urls.append(url)
        if "json" in kwargs:
            captured_payloads.append(
                kwargs["json"]  # ty: ignore[invalid-argument-type]
            )
        if "timeout" in kwargs:
            captured_timeouts.append(
                kwargs["timeout"]  # ty: ignore[invalid-argument-type]
            )
        return _make_bash_response(stdout="hello\n", exit_code=0, duration_ms=42)

    with patch.object(client.session, "post", side_effect=mock_post):
        result = client.execute_bash_in_session("sess-abc123", "echo hello")

    assert captured_urls == ["http://fake:9000/v1/sessions/sess-abc123/bash"]
    assert captured_payloads == [{"cmd": "echo hello", "timeout_ms": 30000}]
    # request timeout should be timeout_ms / 1000 + 10 buffer = 40s
    assert captured_timeouts == [40.0]

    assert isinstance(result, BashExecResponse)
    assert result.stdout == "hello\n"
    assert result.stderr == ""
    assert result.exit_code == 0
    assert not result.timed_out
    assert result.duration_ms == 42


def test_execute_bash_in_session_custom_timeout() -> None:
    """A custom timeout_ms should be forwarded in the payload and used to
    derive the requests-level timeout (timeout_ms / 1000 + 10)."""

    client = CodeInterpreterClient(base_url="http://fake:9000")
    _prime_health(client.base_url, version="0.4.0")

    captured_payloads: list[dict] = []
    captured_timeouts: list[float] = []

    def mock_post(_url: str, **kwargs: object) -> MagicMock:
        if "json" in kwargs:
            captured_payloads.append(
                kwargs["json"]  # ty: ignore[invalid-argument-type]
            )
        if "timeout" in kwargs:
            captured_timeouts.append(
                kwargs["timeout"]  # ty: ignore[invalid-argument-type]
            )
        return _make_bash_response()

    with patch.object(client.session, "post", side_effect=mock_post):
        client.execute_bash_in_session("sess-xyz", "ls -la", timeout_ms=5000)

    assert captured_payloads == [{"cmd": "ls -la", "timeout_ms": 5000}]
    assert captured_timeouts == [15.0]


def test_execute_bash_in_session_parses_timeout_and_nonzero_exit() -> None:
    """A timed-out / failed bash exec should be parsed into the response model
    without raising on the client side."""

    client = CodeInterpreterClient(base_url="http://fake:9000")
    _prime_health(client.base_url, version="0.4.0")

    bash_resp = _make_bash_response(
        stdout="",
        stderr="killed\n",
        exit_code=None,
        timed_out=True,
        duration_ms=30000,
    )

    with patch.object(client.session, "post", return_value=bash_resp):
        result = client.execute_bash_in_session("sess-abc", "sleep 999")

    assert result.timed_out is True
    assert result.exit_code is None
    assert result.stderr == "killed\n"


# ---------------------------------------------------------------------------
# Version gating
# ---------------------------------------------------------------------------


def test_create_session_passes_when_server_meets_minimum() -> None:
    client = CodeInterpreterClient(base_url="http://fake:9000")
    _prime_health(client.base_url, version="0.4.0")

    with patch.object(
        client.session, "post", return_value=_make_create_session_response()
    ):
        client.create_session()


def test_create_session_raises_version_error_when_server_too_old() -> None:
    """Self-gating: skipping ``supports()`` must still surface a typed
    error, not a 404."""
    client = CodeInterpreterClient(base_url="http://fake:9000")
    _prime_health(client.base_url, version="0.3.0")

    with pytest.raises(CodeInterpreterVersionError) as exc_info:
        client.create_session()

    assert exc_info.value.method_name == "create_session"
    assert exc_info.value.server_version == "0.3.0"
    assert exc_info.value.required == "0.4.0"


def test_delete_session_raises_version_error_when_server_too_old() -> None:
    client = CodeInterpreterClient(base_url="http://fake:9000")
    _prime_health(client.base_url, version="0.3.0")

    with pytest.raises(CodeInterpreterVersionError) as exc_info:
        client.delete_session("sess-abc")

    assert exc_info.value.method_name == "delete_session"


def test_execute_bash_in_session_raises_version_error_when_server_too_old() -> None:
    client = CodeInterpreterClient(base_url="http://fake:9000")
    _prime_health(client.base_url, version="0.3.0")

    with pytest.raises(CodeInterpreterVersionError) as exc_info:
        client.execute_bash_in_session("sess-abc", "echo hi")

    assert exc_info.value.method_name == "execute_bash_in_session"


def test_version_error_message_includes_method_and_versions() -> None:
    err = CodeInterpreterVersionError(
        method_name="create_session",
        server_version="0.3.1",
        required="0.4.0",
    )
    msg = str(err)
    assert "create_session" in msg
    assert "0.3.1" in msg
    assert "0.4.0" in msg


def test_parse_version_handles_prerelease_and_build_metadata() -> None:
    assert cic._parse_version("0.4.0") == (0, 4, 0)
    assert cic._parse_version("v0.4.0") == (0, 4, 0)
    assert cic._parse_version("0.4.0-rc.1") == (0, 4, 0)
    assert cic._parse_version("0.4.0+build.7") == (0, 4, 0)
    # Malformed input must not crash the gate.
    assert cic._parse_version("not-a-version") == (0, 0, 0)


def test_requires_rejects_malformed_version_at_decoration_time() -> None:
    """Programmer bug: a typo'd version should fail loud, not silently
    parse to 0.0.0 and skip every gate forever."""
    with pytest.raises(ValueError, match="MAJOR.MINOR.PATCH"):
        cic.requires("not-a-version")

    with pytest.raises(ValueError, match="MAJOR.MINOR.PATCH"):
        cic.requires("0.4")


def test_requires_accepts_valid_versions() -> None:
    cic.requires("0.4.0")
    cic.requires("1.2.3")
    cic.requires("0.4.0-rc.1")
    cic.requires("0.4.0+build.7")


# ---------------------------------------------------------------------------
# supports()
# ---------------------------------------------------------------------------


def test_supports_returns_true_when_server_meets_minimum() -> None:
    client = CodeInterpreterClient(base_url="http://fake:9000")
    _prime_health(client.base_url, version="0.4.0")
    assert client.supports(client.create_session) is True
    assert client.supports(client.execute_bash_in_session) is True


def test_supports_returns_true_for_newer_server() -> None:
    client = CodeInterpreterClient(base_url="http://fake:9000")
    _prime_health(client.base_url, version="1.2.3")
    assert client.supports(client.create_session) is True


def test_supports_returns_false_for_older_server() -> None:
    client = CodeInterpreterClient(base_url="http://fake:9000")
    _prime_health(client.base_url, version="0.3.9")
    assert client.supports(client.create_session) is False


def test_supports_returns_false_for_default_zero_version() -> None:
    """``0.0.0`` is health()'s fallback for unreachable servers — gated
    methods correctly degrade to unsupported."""
    client = CodeInterpreterClient(base_url="http://fake:9000")
    _prime_health(client.base_url, version="0.0.0")
    assert client.supports(client.create_session) is False


def test_supports_with_multiple_methods_requires_all_supported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Any unmet requirement fails the whole check. Simulates a future
    split via monkeypatch."""
    client = CodeInterpreterClient(base_url="http://fake:9000")
    _prime_health(client.base_url, version="0.4.5")

    assert (
        client.supports(client.create_session, client.execute_bash_in_session) is True
    )

    monkeypatch.setattr(
        CodeInterpreterClient.execute_bash_in_session,
        cic._MIN_VERSION_ATTR,
        "0.5.0",
    )

    assert client.supports(client.create_session) is True
    assert client.supports(client.execute_bash_in_session) is False
    assert (
        client.supports(client.create_session, client.execute_bash_in_session) is False
    )


def test_supports_treats_undecorated_method_as_always_available() -> None:
    client = CodeInterpreterClient(base_url="http://fake:9000")
    _prime_health(client.base_url, version="0.0.0")
    # ``execute`` is unconditional.
    assert client.supports(client.execute) is True


def test_supports_with_no_arguments_raises() -> None:
    """Empty input would be vacuously true — reject it."""
    client = CodeInterpreterClient(base_url="http://fake:9000")
    _prime_health(client.base_url, version="0.4.0")

    with pytest.raises(ValueError, match="at least one"):
        client.supports()


def test_min_version_for_undecorated_method_defaults_to_zero() -> None:
    client = CodeInterpreterClient(base_url="http://fake:9000")
    assert cic._min_version_for(client.execute) == cic._DEFAULT_SERVER_VERSION


def test_min_version_for_decorated_method_returns_declared_value() -> None:
    client = CodeInterpreterClient(base_url="http://fake:9000")
    assert cic._min_version_for(client.create_session) == "0.4.0"
    assert cic._min_version_for(client.delete_session) == "0.4.0"
    assert cic._min_version_for(client.execute_bash_in_session) == "0.4.0"
