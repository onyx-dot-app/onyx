"""Tests for tool availability when DISABLE_VECTOR_DB is True.

Verifies that SearchTool and OpenURLTool report themselves as unavailable
when the vector DB is disabled, and that FileReaderTool remains available.
"""

from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session


# ------------------------------------------------------------------
# SearchTool
# ------------------------------------------------------------------


@patch("onyx.configs.app_configs.DISABLE_VECTOR_DB", True)
def test_search_tool_unavailable_when_vector_db_disabled() -> None:
    from onyx.tools.tool_implementations.search.search_tool import SearchTool

    db_session = MagicMock(spec=Session)
    assert SearchTool.is_available(db_session) is False


@patch("onyx.configs.app_configs.DISABLE_VECTOR_DB", False)
@patch(
    "onyx.tools.tool_implementations.search.search_tool.check_connectors_exist",
    return_value=True,
)
def test_search_tool_available_when_vector_db_enabled(
    _mock_connectors: MagicMock,
) -> None:
    from onyx.tools.tool_implementations.search.search_tool import SearchTool

    db_session = MagicMock(spec=Session)
    assert SearchTool.is_available(db_session) is True


# ------------------------------------------------------------------
# OpenURLTool
# ------------------------------------------------------------------


@patch("onyx.configs.app_configs.DISABLE_VECTOR_DB", True)
def test_open_url_tool_unavailable_when_vector_db_disabled() -> None:
    from onyx.tools.tool_implementations.open_url.open_url_tool import OpenURLTool

    db_session = MagicMock(spec=Session)
    assert OpenURLTool.is_available(db_session) is False


# ------------------------------------------------------------------
# FileReaderTool — always available regardless of vector DB state
# ------------------------------------------------------------------


@pytest.mark.parametrize("vector_db_disabled", [True, False])
def test_file_reader_tool_always_available(vector_db_disabled: bool) -> None:
    with patch("onyx.configs.app_configs.DISABLE_VECTOR_DB", vector_db_disabled):
        from onyx.tools.tool_implementations.file_reader.file_reader_tool import (
            FileReaderTool,
        )

        db_session = MagicMock(spec=Session)
        assert FileReaderTool.is_available(db_session) is True
