"""Search API preserves caller history and returns linked search results."""

import json
from unittest.mock import MagicMock

import pytest
from sqlalchemy.orm import Session

from onyx.configs.constants import MessageType
from onyx.db.models import Tool, User
from onyx.llm.models import ToolResult
from onyx.server.features.search import api
from onyx.server.features.search.models import SearchRequest
from onyx.tools.constants import SEARCH_TOOL_ID
from onyx.tools.models import ChatMinimalTextMessage
from onyx.tools.tool_implementations.search.search_tool import SearchTool


@pytest.mark.parametrize("has_history", [False, True])
def test_search_preserves_history_and_explicit_query(
    has_history: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    history = (
        [
            ChatMinimalTextMessage(message=kind.value, message_type=kind)
            for kind in MessageType
        ]
        if has_history
        else None
    )
    request = SearchRequest(query="current question", message_history=history)
    for name in (
        "get_default_llm",
        "get_current_search_settings",
        "get_default_document_index",
        "check_llm_cost_limit_for_provider",
        "load_settings",
    ):
        monkeypatch.setattr(api, name, MagicMock())
    monkeypatch.setattr(
        api, "get_tools", lambda _session: [Tool(id=7, in_code_tool_id=SEARCH_TOOL_ID)]
    )
    tool = MagicMock(spec=SearchTool)
    tool.search.return_value = ToolResult(
        content=json.dumps(
            {
                "results": [
                    {
                        "document": 1,
                        "title": "Guide",
                        "content": "Search result",
                        "url": "https://example.com/guide",
                        "source_type": "web",
                    }
                ]
            }
        )
    )
    factory = MagicMock(return_value=tool)
    monkeypatch.setattr(api, "SearchTool", factory)

    response = api.search(
        request, user=MagicMock(spec=User), db_session=MagicMock(spec=Session)
    )

    assert factory.call_args.kwargs["include_link"] is True
    assert tool.search.call_args.args == ([request.query],)
    assert tool.search.call_args.kwargs["original_query"] == request.query
    assert tool.search.call_args.kwargs["message_history"] == (
        history
        or [
            ChatMinimalTextMessage(message=request.query, message_type=MessageType.USER)
        ]
    )
    assert request.message_history == history
    assert response.results[0].link == "https://example.com/guide"
