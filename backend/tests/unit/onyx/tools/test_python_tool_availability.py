"""Tests for PythonTool availability based on server_enabled flag and health check.

Verifies that PythonTool reports itself as unavailable when either:
- CODE_INTERPRETER_BASE_URL is not set, or
- CodeInterpreterServer.server_enabled is False in the database, or
- The Code Interpreter service health check fails.

Also verifies that the health check result is cached with a TTL.
"""

from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session

TOOL_MODULE = "onyx.tools.tool_implementations.python.python_tool"
CLIENT_MODULE = "onyx.tools.tool_implementations.python.code_interpreter_client"


@pytest.fixture(autouse=True)
def _clear_health_cache() -> None:
    """Reset the health check cache before every test."""
    import onyx.tools.tool_implementations.python.code_interpreter_client as mod

    mod._health_cache = {}


# ------------------------------------------------------------------
# Unavailable when CODE_INTERPRETER_BASE_URL is not set
# ------------------------------------------------------------------


@patch(f"{TOOL_MODULE}.CODE_INTERPRETER_BASE_URL", None)
def test_python_tool_unavailable_without_base_url() -> None:
    from onyx.tools.tool_implementations.python.python_tool import PythonTool

    db_session = MagicMock(spec=Session)
    assert PythonTool.is_available(db_session) is False


@patch(f"{TOOL_MODULE}.CODE_INTERPRETER_BASE_URL", "")
def test_python_tool_unavailable_with_empty_base_url() -> None:
    from onyx.tools.tool_implementations.python.python_tool import PythonTool

    db_session = MagicMock(spec=Session)
    assert PythonTool.is_available(db_session) is False


# ------------------------------------------------------------------
# Unavailable when server_enabled is False
# ------------------------------------------------------------------


@patch(f"{TOOL_MODULE}.CODE_INTERPRETER_BASE_URL", "http://localhost:8000")
@patch(f"{TOOL_MODULE}.fetch_code_interpreter_server")
def test_python_tool_unavailable_when_server_disabled(
    mock_fetch: MagicMock,
) -> None:
    from onyx.tools.tool_implementations.python.python_tool import PythonTool

    mock_server = MagicMock()
    mock_server.server_enabled = False
    mock_fetch.return_value = mock_server

    db_session = MagicMock(spec=Session)
    assert PythonTool.is_available(db_session) is False


# ------------------------------------------------------------------
# Health check determines availability when URL + server are OK
# ------------------------------------------------------------------


@patch(f"{TOOL_MODULE}.CODE_INTERPRETER_BASE_URL", "http://localhost:8000")
@patch(f"{TOOL_MODULE}.fetch_code_interpreter_server")
@patch(f"{TOOL_MODULE}.CodeInterpreterClient")
def test_python_tool_available_when_health_check_passes(
    mock_client_cls: MagicMock,
    mock_fetch: MagicMock,
) -> None:
    from onyx.tools.tool_implementations.python.python_tool import PythonTool

    mock_server = MagicMock()
    mock_server.server_enabled = True
    mock_fetch.return_value = mock_server

    mock_client = MagicMock()
    mock_client.health.return_value = True
    mock_client_cls.return_value = mock_client

    db_session = MagicMock(spec=Session)
    assert PythonTool.is_available(db_session) is True
    mock_client.health.assert_called_once_with(use_cache=True)


@patch(f"{TOOL_MODULE}.CODE_INTERPRETER_BASE_URL", "http://localhost:8000")
@patch(f"{TOOL_MODULE}.fetch_code_interpreter_server")
@patch(f"{TOOL_MODULE}.CodeInterpreterClient")
def test_python_tool_unavailable_when_health_check_fails(
    mock_client_cls: MagicMock,
    mock_fetch: MagicMock,
) -> None:
    from onyx.tools.tool_implementations.python.python_tool import PythonTool

    mock_server = MagicMock()
    mock_server.server_enabled = True
    mock_fetch.return_value = mock_server

    mock_client = MagicMock()
    mock_client.health.return_value = False
    mock_client_cls.return_value = mock_client

    db_session = MagicMock(spec=Session)
    assert PythonTool.is_available(db_session) is False
    mock_client.health.assert_called_once_with(use_cache=True)


# ------------------------------------------------------------------
# Health check is NOT reached when preconditions fail
# ------------------------------------------------------------------


@patch(f"{TOOL_MODULE}.CODE_INTERPRETER_BASE_URL", "http://localhost:8000")
@patch(f"{TOOL_MODULE}.fetch_code_interpreter_server")
@patch(f"{TOOL_MODULE}.CodeInterpreterClient")
def test_health_check_not_called_when_server_disabled(
    mock_client_cls: MagicMock,
    mock_fetch: MagicMock,
) -> None:
    from onyx.tools.tool_implementations.python.python_tool import PythonTool

    mock_server = MagicMock()
    mock_server.server_enabled = False
    mock_fetch.return_value = mock_server

    db_session = MagicMock(spec=Session)
    assert PythonTool.is_available(db_session) is False
    mock_client_cls.assert_not_called()


# ------------------------------------------------------------------
# Health check caching (tested at the client level)
# ------------------------------------------------------------------


def test_health_check_cached_on_second_call() -> None:
    from onyx.tools.tool_implementations.python.code_interpreter_client import (
        CodeInterpreterClient,
    )

    client = CodeInterpreterClient(base_url="http://fake:9000")
    mock_response = MagicMock()
    mock_response.json.return_value = {"status": "ok"}

    with patch.object(client.session, "get", return_value=mock_response) as mock_get:
        assert client.health(use_cache=True) is True
        assert client.health(use_cache=True) is True
        # Only one HTTP call — the second used the cache
        mock_get.assert_called_once()


@patch(f"{CLIENT_MODULE}.time")
def test_health_check_refreshed_after_ttl_expires(mock_time: MagicMock) -> None:
    from onyx.tools.tool_implementations.python.code_interpreter_client import (
        CodeInterpreterClient,
        _HEALTH_CACHE_TTL_SECONDS,
    )

    client = CodeInterpreterClient(base_url="http://fake:9000")
    mock_response = MagicMock()
    mock_response.json.return_value = {"status": "ok"}

    with patch.object(client.session, "get", return_value=mock_response) as mock_get:
        # First call at t=0 — cache miss
        mock_time.monotonic.return_value = 0.0
        assert client.health(use_cache=True) is True
        assert mock_get.call_count == 1

        # Second call within TTL — cache hit
        mock_time.monotonic.return_value = float(_HEALTH_CACHE_TTL_SECONDS - 1)
        assert client.health(use_cache=True) is True
        assert mock_get.call_count == 1

        # Third call after TTL — cache miss, fresh request
        mock_time.monotonic.return_value = float(_HEALTH_CACHE_TTL_SECONDS + 1)
        assert client.health(use_cache=True) is True
        assert mock_get.call_count == 2


def test_health_check_no_cache_by_default() -> None:
    from onyx.tools.tool_implementations.python.code_interpreter_client import (
        CodeInterpreterClient,
    )

    client = CodeInterpreterClient(base_url="http://fake:9000")
    mock_response = MagicMock()
    mock_response.json.return_value = {"status": "ok"}

    with patch.object(client.session, "get", return_value=mock_response) as mock_get:
        assert client.health() is True
        assert client.health() is True
        # Both calls hit the network when use_cache=False (default)
        assert mock_get.call_count == 2
