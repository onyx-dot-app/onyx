from unittest.mock import MagicMock, patch
from uuid import uuid4

from onyx.context.search.models import BaseFilters, PersonaSearchInfo
from onyx.db.models import User
from onyx.tools.interface import Tool
from onyx.tools.tool_constructor import (
    CustomToolConfig,
    SearchToolConfig,
    postgres_query_tool_for_turn,
)
from onyx.tools.tool_implementations.postgres.postgres_tool import PostgresTool
from onyx.tools.tool_implementations.search.search_tool import SearchTool

_USER = User(id=uuid4(), email="user@example.com")
_CONFIGURATION = MagicMock(
    search=PersonaSearchInfo(
        document_set_names=["Eng"],
        search_start_date=None,
        attached_document_ids=[],
        hierarchy_node_ids=[],
    )
)
_SESSION_ID = uuid4()


def _tool(tools: list[Tool]) -> PostgresTool | None:
    return postgres_query_tool_for_turn(
        tools,
        _USER,
        _CONFIGURATION,
        SearchToolConfig(user_selected_filters=BaseFilters(document_set=["Sales"])),
        CustomToolConfig(chat_session_id=_SESSION_ID),
    )


def test_a_turn_with_internal_search_gets_the_tool_with_its_scope() -> None:
    tool = _tool([MagicMock(spec=Tool), MagicMock(spec=SearchTool)])
    assert tool is not None
    # The request's document sets replace the agent's, as for search.
    assert tool._scope.document_set_names == ["Sales"]
    assert tool._current_chat_session_id == _SESSION_ID
    assert tool.id is None


def test_a_turn_without_internal_search_does_not() -> None:
    assert _tool([MagicMock(spec=Tool)]) is None
    assert _tool([]) is None


def test_the_deployment_can_turn_the_tool_off() -> None:
    with patch("onyx.tools.tool_constructor.DISABLE_POSTGRES_QUERY_TOOL", True):
        assert _tool([MagicMock(spec=SearchTool)]) is None
