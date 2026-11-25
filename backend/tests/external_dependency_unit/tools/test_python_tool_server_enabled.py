"""The database flag controls availability when the interpreter is healthy."""

from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session

from onyx.db.code_interpreter import (
    fetch_code_interpreter_server,
    update_code_interpreter_server_enabled,
)
from onyx.tools.tool_implementations.python.code_interpreter_client import (
    HealthResponse,
)
from onyx.tools.tool_implementations.python.python_tool import PythonTool


@pytest.mark.parametrize("enabled", [False, True], ids=["disabled", "enabled"])
def test_python_tool_server_enabled(db_session: Session, enabled: bool) -> None:
    initial_enabled = fetch_code_interpreter_server(db_session).server_enabled
    try:
        update_code_interpreter_server_enabled(db_session, enabled=enabled)
        with (
            patch(
                "onyx.tools.tool_implementations.python.python_tool.CODE_INTERPRETER_BASE_URL",
                "http://interpreter.test",
            ),
            patch(
                "onyx.tools.tool_implementations.python.python_tool.CodeInterpreterClient"
            ) as client,
        ):
            health = client.return_value.__enter__.return_value.health
            health.return_value = HealthResponse(connected=True)
            assert PythonTool.is_available(db_session) is enabled
    finally:
        update_code_interpreter_server_enabled(db_session, enabled=initial_enabled)
