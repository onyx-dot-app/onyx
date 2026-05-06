"""Unit tests for BashTool.

Covers:
- Happy path: response shape, emitted start + delta packets.
- Missing required ``cmd`` parameter raises ToolCallException.
- Exception during execute is caught and surfaces as an error result + delta.
- stdout/stderr are truncated at CODE_INTERPRETER_MAX_OUTPUT_LENGTH.
- Non-zero exit code populates the result's ``error`` field.
- Tool definition exposes the expected schema.
- Properties return the values set in __init__.
- ``is_available`` correctly gates on env / DB / health / supports().
"""

import json
from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from onyx.configs.app_configs import CODE_INTERPRETER_DEFAULT_TIMEOUT_MS
from onyx.configs.app_configs import CODE_INTERPRETER_MAX_OUTPUT_LENGTH
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import BashToolDelta
from onyx.server.query_and_chat.streaming_models import BashToolStart
from onyx.tools.models import ToolCallException
from onyx.tools.tool_implementations.bash.bash_tool import BashTool
from onyx.tools.tool_implementations.bash.bash_tool import BashToolOverrideKwargs
from onyx.tools.tool_implementations.bash.bash_tool import CMD_FIELD
from onyx.tools.tool_implementations.python.code_interpreter_client import (
    BashExecResponse,
)

TOOL_MODULE = "onyx.tools.tool_implementations.bash.bash_tool"


def _make_response(
    stdout: str = "",
    stderr: str = "",
    exit_code: int | None = 0,
    timed_out: bool = False,
    duration_ms: int = 10,
) -> BashExecResponse:
    return BashExecResponse(
        stdout=stdout,
        stderr=stderr,
        exit_code=exit_code,
        timed_out=timed_out,
        duration_ms=duration_ms,
    )


def _make_tool() -> tuple[BashTool, MagicMock]:
    emitter = MagicMock()
    tool = BashTool(tool_id=42, session_id="session-abc", emitter=emitter)
    return tool, emitter


def _patched_client(client: MagicMock) -> MagicMock:
    """Wrap a MagicMock as a context manager and patch CodeInterpreterClient."""
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=client)
    ctx.__exit__ = MagicMock(return_value=False)
    return ctx


def _placement() -> Placement:
    return Placement(turn_index=0, tab_index=0)


# ---------------------------------------------------------------------------
# Properties + tool definition
# ---------------------------------------------------------------------------


def test_properties_match_constructor_args() -> None:
    tool, _ = _make_tool()
    assert tool.id == 42
    assert tool.name == "bash"
    assert tool.display_name == "Bash"
    assert tool.session_id == "session-abc"
    assert tool.description  # non-empty


def test_tool_definition_shape() -> None:
    tool, _ = _make_tool()
    definition = tool.tool_definition()

    assert definition["type"] == "function"
    fn = definition["function"]
    assert fn["name"] == "bash"
    params = fn["parameters"]
    assert params["type"] == "object"
    assert CMD_FIELD in params["properties"]
    assert params["properties"][CMD_FIELD]["type"] == "string"
    assert params["required"] == [CMD_FIELD]


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_happy_path_returns_serialized_result_and_emits_packets() -> None:
    tool, emitter = _make_tool()
    client = MagicMock()
    client.execute_bash_in_session.return_value = _make_response(
        stdout="hello\n", stderr="", exit_code=0
    )

    with patch(
        f"{TOOL_MODULE}.CodeInterpreterClient", return_value=_patched_client(client)
    ):
        response = tool.run(
            placement=_placement(),
            override_kwargs=BashToolOverrideKwargs(),
            cmd="echo hello",
        )

    # Client called with the right args
    client.execute_bash_in_session.assert_called_once_with(
        session_id="session-abc",
        cmd="echo hello",
        timeout_ms=CODE_INTERPRETER_DEFAULT_TIMEOUT_MS,
    )

    # Response shape
    payload = json.loads(response.llm_facing_response)
    assert payload["stdout"] == "hello\n"
    assert payload["stderr"] == ""
    assert payload["exit_code"] == 0
    assert payload["timed_out"] is False
    assert payload["error"] is None  # exit_code == 0
    assert response.rich_response is None

    # Two packets emitted: start (with cmd) then delta (with stdout/stderr)
    assert emitter.emit.call_count == 2
    start_packet = emitter.emit.call_args_list[0].args[0]
    delta_packet = emitter.emit.call_args_list[1].args[0]
    assert isinstance(start_packet.obj, BashToolStart)
    assert start_packet.obj.cmd == "echo hello"
    assert isinstance(delta_packet.obj, BashToolDelta)
    assert delta_packet.obj.stdout == "hello\n"
    assert delta_packet.obj.exit_code == 0
    assert delta_packet.obj.timed_out is False


# ---------------------------------------------------------------------------
# Missing cmd parameter
# ---------------------------------------------------------------------------


def test_missing_cmd_raises_tool_call_exception() -> None:
    tool, emitter = _make_tool()

    with pytest.raises(ToolCallException) as excinfo:
        tool.run(
            placement=_placement(),
            override_kwargs=BashToolOverrideKwargs(),
        )

    # Internal message + llm-facing message both present and mention the field
    assert CMD_FIELD in str(excinfo.value)
    assert CMD_FIELD in excinfo.value.llm_facing_message

    # Nothing should have been emitted before the exception
    emitter.emit.assert_not_called()


@pytest.mark.parametrize(
    "bad_cmd",
    [
        None,
        42,
        ["ls", "-la"],
        {"cmd": "ls"},
        b"ls -la",
    ],
)
def test_non_string_cmd_raises_tool_call_exception(bad_cmd: object) -> None:
    """Regression: ``cast(str, ...)`` is a no-op at runtime, so a non-string
    ``cmd`` from the LLM (e.g. a list, None, an int) used to flow through
    and surface as either an opaque Pydantic validation error (from
    ``BashToolStart``) or a 422 from the upstream service. We now fail fast
    with a clear ``ToolCallException`` before any packet is emitted."""
    tool, emitter = _make_tool()

    with pytest.raises(ToolCallException) as excinfo:
        tool.run(
            placement=_placement(),
            override_kwargs=BashToolOverrideKwargs(),
            cmd=bad_cmd,
        )

    # llm-facing message names the field and the actual type so the model
    # can self-correct on the next try
    assert CMD_FIELD in excinfo.value.llm_facing_message
    assert type(bad_cmd).__name__ in excinfo.value.llm_facing_message

    # No packets emitted — failure is at validation, before BashToolStart
    emitter.emit.assert_not_called()


# ---------------------------------------------------------------------------
# Exception during execute is caught and surfaced
# ---------------------------------------------------------------------------


def test_client_exception_returns_error_result_and_emits_error_delta() -> None:
    tool, emitter = _make_tool()
    client = MagicMock()
    client.execute_bash_in_session.side_effect = RuntimeError("connection refused")

    with patch(
        f"{TOOL_MODULE}.CodeInterpreterClient", return_value=_patched_client(client)
    ):
        response = tool.run(
            placement=_placement(),
            override_kwargs=BashToolOverrideKwargs(),
            cmd="ls",
        )

    payload = json.loads(response.llm_facing_response)
    assert payload["stdout"] == ""
    assert "connection refused" in payload["stderr"]
    assert payload["exit_code"] == -1
    assert payload["timed_out"] is False
    assert "connection refused" in payload["error"]

    # Start + error-delta both emitted (still two packets)
    assert emitter.emit.call_count == 2
    delta_packet = emitter.emit.call_args_list[1].args[0]
    assert isinstance(delta_packet.obj, BashToolDelta)
    assert delta_packet.obj.exit_code == -1
    assert "connection refused" in delta_packet.obj.stderr


def test_client_constructor_failure_still_emits_closing_delta() -> None:
    """Regression: a ``CodeInterpreterClient()`` constructor failure (e.g.
    ``CODE_INTERPRETER_BASE_URL`` unset, raising ``ValueError`` in __init__)
    must NOT escape past the try/except. Without the fix, ``BashToolStart``
    would already be on the wire and no closing ``BashToolDelta`` would
    follow — leaving the frontend timeline stuck."""
    tool, emitter = _make_tool()

    with patch(
        f"{TOOL_MODULE}.CodeInterpreterClient",
        side_effect=ValueError("CODE_INTERPRETER_BASE_URL not configured"),
    ):
        response = tool.run(
            placement=_placement(),
            override_kwargs=BashToolOverrideKwargs(),
            cmd="ls",
        )

    # Error path: error result returned, no exception bubbled out
    payload = json.loads(response.llm_facing_response)
    assert payload["exit_code"] == -1
    assert "CODE_INTERPRETER_BASE_URL" in payload["error"]

    # Critically: both Start AND closing Delta were emitted, in that order
    assert emitter.emit.call_count == 2
    start_packet = emitter.emit.call_args_list[0].args[0]
    delta_packet = emitter.emit.call_args_list[1].args[0]
    assert isinstance(start_packet.obj, BashToolStart)
    assert isinstance(delta_packet.obj, BashToolDelta)
    assert delta_packet.obj.exit_code == -1


# ---------------------------------------------------------------------------
# Output truncation
# ---------------------------------------------------------------------------


def test_long_stdout_is_truncated() -> None:
    tool, _ = _make_tool()
    client = MagicMock()
    long_output = "x" * (CODE_INTERPRETER_MAX_OUTPUT_LENGTH + 5_000)
    client.execute_bash_in_session.return_value = _make_response(
        stdout=long_output, stderr="", exit_code=0
    )

    with patch(
        f"{TOOL_MODULE}.CodeInterpreterClient", return_value=_patched_client(client)
    ):
        response = tool.run(
            placement=_placement(),
            override_kwargs=BashToolOverrideKwargs(),
            cmd="cat huge.txt",
        )

    payload = json.loads(response.llm_facing_response)
    assert "[output truncated" in payload["stdout"]
    # Truncated to MAX + truncation footer; should be much shorter than original
    assert len(payload["stdout"]) < len(long_output)


def test_short_stdout_is_not_truncated() -> None:
    tool, _ = _make_tool()
    client = MagicMock()
    client.execute_bash_in_session.return_value = _make_response(
        stdout="short", stderr="", exit_code=0
    )

    with patch(
        f"{TOOL_MODULE}.CodeInterpreterClient", return_value=_patched_client(client)
    ):
        response = tool.run(
            placement=_placement(),
            override_kwargs=BashToolOverrideKwargs(),
            cmd="echo short",
        )

    payload = json.loads(response.llm_facing_response)
    assert payload["stdout"] == "short"
    assert "[output truncated" not in payload["stdout"]


# ---------------------------------------------------------------------------
# Non-zero exit code populates error field
# ---------------------------------------------------------------------------


def test_nonzero_exit_code_sets_error_field_to_stderr() -> None:
    tool, _ = _make_tool()
    client = MagicMock()
    client.execute_bash_in_session.return_value = _make_response(
        stdout="", stderr="cat: missing.txt: No such file", exit_code=1
    )

    with patch(
        f"{TOOL_MODULE}.CodeInterpreterClient", return_value=_patched_client(client)
    ):
        response = tool.run(
            placement=_placement(),
            override_kwargs=BashToolOverrideKwargs(),
            cmd="cat missing.txt",
        )

    payload = json.loads(response.llm_facing_response)
    assert payload["exit_code"] == 1
    assert payload["error"] == "cat: missing.txt: No such file"
    assert payload["stderr"] == "cat: missing.txt: No such file"


def test_zero_exit_code_with_stderr_does_not_set_error() -> None:
    """A command can write to stderr while still exiting cleanly (e.g. progress
    bars). We only treat it as an error when exit_code != 0."""
    tool, _ = _make_tool()
    client = MagicMock()
    client.execute_bash_in_session.return_value = _make_response(
        stdout="ok", stderr="warning: deprecated", exit_code=0
    )

    with patch(
        f"{TOOL_MODULE}.CodeInterpreterClient", return_value=_patched_client(client)
    ):
        response = tool.run(
            placement=_placement(),
            override_kwargs=BashToolOverrideKwargs(),
            cmd="legacy-cmd",
        )

    payload = json.loads(response.llm_facing_response)
    assert payload["exit_code"] == 0
    assert payload["stderr"] == "warning: deprecated"
    assert payload["error"] is None


# ---------------------------------------------------------------------------
# emit_start is a deliberate no-op
# ---------------------------------------------------------------------------


def test_emit_start_is_a_noop() -> None:
    tool, emitter = _make_tool()
    tool.emit_start(_placement())
    emitter.emit.assert_not_called()


# ---------------------------------------------------------------------------
# Timed-out command surfaces as timed_out=True
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# is_available — gates on env, DB, health, and capability/supports check
# ---------------------------------------------------------------------------


def _make_db_session() -> MagicMock:
    """Build a MagicMock db_session. The session itself is opaque —
    ``fetch_code_interpreter_server`` is patched, so only that mock's
    return value matters for is_available tests."""
    return MagicMock()


@contextmanager
def _is_available_env(
    *,
    base_url: str = "http://fake:8000",
    server_enabled: bool = True,
    healthy: bool = True,
    server_version: str = "1.0.0",
    supports_return: bool = True,
) -> Iterator[MagicMock]:
    """Patch the four moving parts ``BashTool.is_available`` consults
    (``CODE_INTERPRETER_BASE_URL``, ``fetch_code_interpreter_server``, the
    ``CodeInterpreterClient`` class, and the client's ``health`` /
    ``supports`` return values), yielding the inner mock client so tests
    can assert on which methods were called.
    """
    from onyx.tools.tool_implementations.python.code_interpreter_client import (
        HealthResponse,
    )

    with (
        patch(f"{TOOL_MODULE}.CODE_INTERPRETER_BASE_URL", base_url),
        patch(f"{TOOL_MODULE}.fetch_code_interpreter_server") as mock_fetch,
        patch(f"{TOOL_MODULE}.CodeInterpreterClient") as mock_client_cls,
    ):
        mock_server = MagicMock()
        mock_server.server_enabled = server_enabled
        mock_fetch.return_value = mock_server

        mock_client = MagicMock()
        mock_client.health.return_value = HealthResponse(
            healthy=healthy, version=server_version
        )
        mock_client.supports.return_value = supports_return

        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

        yield mock_client


def test_is_available_true_when_all_checks_pass() -> None:
    with _is_available_env(
        healthy=True, server_version="0.4.0", supports_return=True
    ) as mock_client:
        assert BashTool.is_available(_make_db_session()) is True
        # supports() should have been called once with the three session
        # methods BashTool transitively depends on. The method identities
        # come from the patched CodeInterpreterClient (so they're child
        # mocks at runtime); assert by name rather than by identity.
        mock_client.supports.assert_called_once()
        called_args, _ = mock_client.supports.call_args
        called_names = {getattr(arg, "_mock_name", "") for arg in called_args}
        assert called_names == {
            "create_session",
            "execute_bash_in_session",
            "delete_session",
        }


def test_is_available_false_when_base_url_missing() -> None:
    with _is_available_env(base_url="") as mock_client:
        assert BashTool.is_available(_make_db_session()) is False
        # Short-circuit: never even hit the DB or the client
        mock_client.health.assert_not_called()
        mock_client.supports.assert_not_called()


def test_is_available_false_when_server_disabled_in_db() -> None:
    with _is_available_env(server_enabled=False) as mock_client:
        assert BashTool.is_available(_make_db_session()) is False
        # Short-circuit before the network probe
        mock_client.health.assert_not_called()
        mock_client.supports.assert_not_called()


def test_is_available_false_when_unhealthy() -> None:
    with _is_available_env(healthy=False) as mock_client:
        assert BashTool.is_available(_make_db_session()) is False
        # Short-circuit before the version-gate probe
        mock_client.supports.assert_not_called()


def test_is_available_false_when_server_too_old() -> None:
    """Healthy + reachable but the deployed code-interpreter version doesn't
    expose the session/bash routes that BashTool depends on."""
    with _is_available_env(
        healthy=True, server_version="0.3.9", supports_return=False
    ) as mock_client:
        assert BashTool.is_available(_make_db_session()) is False
        # supports() must have been called — that's how we detected the gap
        mock_client.supports.assert_called_once()


def test_timed_out_response_is_propagated() -> None:
    tool, emitter = _make_tool()
    client = MagicMock()
    client.execute_bash_in_session.return_value = _make_response(
        stdout="partial", stderr="", exit_code=None, timed_out=True
    )

    with patch(
        f"{TOOL_MODULE}.CodeInterpreterClient", return_value=_patched_client(client)
    ):
        response = tool.run(
            placement=_placement(),
            override_kwargs=BashToolOverrideKwargs(),
            cmd="sleep 99999",
        )

    payload = json.loads(response.llm_facing_response)
    assert payload["timed_out"] is True
    assert payload["exit_code"] is None
    delta_packet = emitter.emit.call_args_list[1].args[0]
    assert isinstance(delta_packet.obj, BashToolDelta)
    assert delta_packet.obj.timed_out is True
