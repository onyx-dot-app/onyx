"""Tests that PythonTool.is_available() respects the server_enabled DB flag.

Uses a real DB session with CODE_INTERPRETER_BASE_URL mocked so the
environment-variable check passes and the DB flag is the deciding factor.
"""

from unittest.mock import patch

from sqlalchemy.orm import Session

from onyx.db.code_interpreter import fetch_code_interpreter_server
from onyx.db.code_interpreter import update_code_interpreter_server_enabled
from onyx.tools.tool_implementations.python.python_tool import PythonTool


def test_python_tool_unavailable_when_server_disabled(
    db_session: Session,
) -> None:
    """With a valid base URL, the tool should be unavailable when
    server_enabled is False in the DB."""
    server = fetch_code_interpreter_server(db_session)
    initial_enabled = server.server_enabled

    try:
        update_code_interpreter_server_enabled(db_session, enabled=False)

        with patch(
            "onyx.tools.tool_implementations.python.python_tool.CODE_INTERPRETER_BASE_URL",
            "http://fake:8888",
        ):
            assert PythonTool.is_available(db_session) is False
    finally:
        update_code_interpreter_server_enabled(db_session, enabled=initial_enabled)


def test_python_tool_available_when_server_enabled(
    db_session: Session,
) -> None:
    """With a valid base URL, the tool should be available when
    server_enabled is True in the DB."""
    server = fetch_code_interpreter_server(db_session)
    initial_enabled = server.server_enabled

    try:
        update_code_interpreter_server_enabled(db_session, enabled=True)

        with patch(
            "onyx.tools.tool_implementations.python.python_tool.CODE_INTERPRETER_BASE_URL",
            "http://fake:8888",
        ):
            assert PythonTool.is_available(db_session) is True
    finally:
        update_code_interpreter_server_enabled(db_session, enabled=initial_enabled)
