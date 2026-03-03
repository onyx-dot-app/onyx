"""Tests for PythonTool availability based on server_enabled flag and health check.

Verifies that PythonTool reports itself as unavailable when either:
- CODE_INTERPRETER_BASE_URL is not set, or
- CodeInterpreterServer.server_enabled is False in the database, or
- The Code Interpreter service health check fails.
"""

from unittest.mock import MagicMock
from unittest.mock import patch

from sqlalchemy.orm import Session


# ------------------------------------------------------------------
# Unavailable when CODE_INTERPRETER_BASE_URL is not set
# ------------------------------------------------------------------


@patch(
    "onyx.tools.tool_implementations.python.python_tool.CODE_INTERPRETER_BASE_URL",
    None,
)
def test_python_tool_unavailable_without_base_url() -> None:
    from onyx.tools.tool_implementations.python.python_tool import PythonTool

    db_session = MagicMock(spec=Session)
    assert PythonTool.is_available(db_session) is False


@patch(
    "onyx.tools.tool_implementations.python.python_tool.CODE_INTERPRETER_BASE_URL",
    "",
)
def test_python_tool_unavailable_with_empty_base_url() -> None:
    from onyx.tools.tool_implementations.python.python_tool import PythonTool

    db_session = MagicMock(spec=Session)
    assert PythonTool.is_available(db_session) is False


# ------------------------------------------------------------------
# Unavailable when server_enabled is False
# ------------------------------------------------------------------


@patch(
    "onyx.tools.tool_implementations.python.python_tool.CODE_INTERPRETER_BASE_URL",
    "http://localhost:8000",
)
@patch(
    "onyx.tools.tool_implementations.python.python_tool.fetch_code_interpreter_server",
)
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


@patch(
    "onyx.tools.tool_implementations.python.python_tool.CODE_INTERPRETER_BASE_URL",
    "http://localhost:8000",
)
@patch(
    "onyx.tools.tool_implementations.python.python_tool.fetch_code_interpreter_server",
)
@patch(
    "onyx.tools.tool_implementations.python.python_tool.CodeInterpreterClient",
)
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
    mock_client.health.assert_called_once()


@patch(
    "onyx.tools.tool_implementations.python.python_tool.CODE_INTERPRETER_BASE_URL",
    "http://localhost:8000",
)
@patch(
    "onyx.tools.tool_implementations.python.python_tool.fetch_code_interpreter_server",
)
@patch(
    "onyx.tools.tool_implementations.python.python_tool.CodeInterpreterClient",
)
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
    mock_client.health.assert_called_once()


# ------------------------------------------------------------------
# Health check is NOT reached when preconditions fail
# ------------------------------------------------------------------


@patch(
    "onyx.tools.tool_implementations.python.python_tool.CODE_INTERPRETER_BASE_URL",
    "http://localhost:8000",
)
@patch(
    "onyx.tools.tool_implementations.python.python_tool.fetch_code_interpreter_server",
)
@patch(
    "onyx.tools.tool_implementations.python.python_tool.CodeInterpreterClient",
)
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
