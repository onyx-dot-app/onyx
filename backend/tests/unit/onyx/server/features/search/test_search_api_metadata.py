"""POST /api/search returns each document's metadata as an object."""

import json
from unittest.mock import MagicMock, patch

from onyx.db.models import User
from onyx.llm.models import ToolResult
from onyx.server.features.search.api import search
from onyx.server.features.search.models import SearchRequest
from onyx.tools.constants import SEARCH_TOOL_ID

_API = "onyx.server.features.search.api"


def _entry(metadata: str | None) -> dict[str, object]:
    return {
        "document": 1,
        "title": "PROJ-1",
        "source_type": "jira",
        "content": "Fix search",
        **({"metadata": metadata} if metadata is not None else {}),
    }


def test_search_returns_document_metadata() -> None:
    metadata = {"reporter": "Ada", "labels": ["mcp", "search"]}
    llm_facing = json.dumps({"results": [_entry(json.dumps(metadata)), _entry(None)]})
    tool = MagicMock(id=7, in_code_tool_id=SEARCH_TOOL_ID)
    search_tool_cls = MagicMock(NAME="internal_search")
    search_tool_cls.return_value.search.return_value = ToolResult(content=llm_facing)

    with (
        patch(f"{_API}.get_default_llm"),
        patch(f"{_API}.check_llm_cost_limit_for_provider"),
        patch(f"{_API}.check_model_spend_limits"),
        patch(f"{_API}.get_current_search_settings"),
        patch(f"{_API}.get_default_document_index"),
        patch(f"{_API}.load_settings"),
        patch(f"{_API}.get_tools", return_value=[tool]),
        patch(f"{_API}.SearchTool", search_tool_cls),
    ):
        response = search(
            request=SearchRequest(query="who reported PROJ-1"),
            user=MagicMock(spec=User),
            db_session=MagicMock(),
        )

    with_metadata, without = response.results
    assert with_metadata.metadata == metadata
    assert without.metadata is None
