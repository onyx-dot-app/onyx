"""Tests for SearchTool availability for *configuration* vs *runtime*.

``is_available`` gates whether internal search can actually run on a chat turn
(it requires connectors / federated connectors / user files to exist).

``is_available_for_configuration`` gates whether internal search can be attached
to an agent in the editor. It must stay True whenever the vector DB is enabled —
even with no indexed content yet — so an agent created with knowledge before its
first source finishes indexing is not silently saved without the search tool.
"""

from unittest.mock import MagicMock
from unittest.mock import patch

from sqlalchemy.orm import Session

SEARCH_MODULE = "onyx.tools.tool_implementations.search.search_tool"


def _patch_no_indexed_content() -> list:
    """Patch every 'does searchable content exist' check to return False."""
    return [
        patch(f"{SEARCH_MODULE}.check_connectors_exist", return_value=False),
        patch(f"{SEARCH_MODULE}.check_federated_connectors_exist", return_value=False),
        patch("onyx.db.connector.check_user_files_exist", return_value=False),
    ]


@patch("onyx.configs.app_configs.DISABLE_VECTOR_DB", False)
def test_runtime_unavailable_without_any_content() -> None:
    """With the vector DB on but nothing indexed, search cannot run yet."""
    from onyx.tools.tool_implementations.search.search_tool import SearchTool

    db_session = MagicMock(spec=Session)
    patches = _patch_no_indexed_content()
    for p in patches:
        p.start()
    try:
        assert SearchTool.is_available(db_session) is False
    finally:
        for p in patches:
            p.stop()


@patch("onyx.configs.app_configs.DISABLE_VECTOR_DB", False)
def test_configurable_without_any_content() -> None:
    """The fix: search stays *configurable* with the vector DB on even when no
    content is indexed, so the agent editor still attaches it when Knowledge is
    enabled. (Runtime execution is re-gated by ``is_available`` at chat time.)"""
    from onyx.tools.tool_implementations.search.search_tool import SearchTool

    db_session = MagicMock(spec=Session)
    patches = _patch_no_indexed_content()
    for p in patches:
        p.start()
    try:
        assert SearchTool.is_available_for_configuration(db_session) is True
    finally:
        for p in patches:
            p.stop()


@patch("onyx.configs.app_configs.DISABLE_VECTOR_DB", True)
def test_not_configurable_when_vector_db_disabled() -> None:
    """When the vector DB is disabled, search is neither runnable nor configurable."""
    from onyx.tools.tool_implementations.search.search_tool import SearchTool

    db_session = MagicMock(spec=Session)
    assert SearchTool.is_available(db_session) is False
    assert SearchTool.is_available_for_configuration(db_session) is False


@patch("onyx.configs.app_configs.DISABLE_VECTOR_DB", False)
def test_runtime_available_once_a_connector_exists() -> None:
    """Once a connector exists, search becomes runnable too — confirming the two
    checks converge as soon as there is something to search."""
    from onyx.tools.tool_implementations.search.search_tool import SearchTool

    db_session = MagicMock(spec=Session)
    with (
        patch(f"{SEARCH_MODULE}.check_connectors_exist", return_value=True),
        patch(f"{SEARCH_MODULE}.check_federated_connectors_exist", return_value=False),
        patch("onyx.db.connector.check_user_files_exist", return_value=False),
    ):
        assert SearchTool.is_available(db_session) is True
        assert SearchTool.is_available_for_configuration(db_session) is True


@patch("onyx.configs.app_configs.DISABLE_VECTOR_DB", False)
def test_persona_can_attach_search_tool_without_any_content() -> None:
    """Regression: creating an agent with Knowledge enabled before any source is
    indexed must not be rejected by persona tool validation (this is the same
    configuration-time action as the editor offering the tool)."""
    from onyx.db.persona import validate_persona_tools

    db_session = MagicMock(spec=Session)
    search_tool_row = MagicMock()
    search_tool_row.in_code_tool_id = "SearchTool"

    patches = _patch_no_indexed_content()
    for p in patches:
        p.start()
    try:
        # Must not raise
        validate_persona_tools([search_tool_row], db_session)
    finally:
        for p in patches:
            p.stop()


@patch("onyx.configs.app_configs.DISABLE_VECTOR_DB", True)
def test_persona_cannot_attach_search_tool_when_vector_db_disabled() -> None:
    import pytest

    from onyx.db.persona import validate_persona_tools

    db_session = MagicMock(spec=Session)
    search_tool_row = MagicMock()
    search_tool_row.in_code_tool_id = "SearchTool"

    with pytest.raises(ValueError, match="SearchTool is not available"):
        validate_persona_tools([search_tool_row], db_session)
