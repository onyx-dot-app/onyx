"""POST /api/search writes one ``search.query`` event. MCP clients search
through this route, so the event also records their searches."""

import json
from collections.abc import Generator
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from onyx.context.search.models import SearchDoc, SearchDocsResponse
from onyx.db.models import User
from onyx.llm.models import ToolResult
from onyx.server.features.search.api import search
from onyx.server.features.search.models import SearchRequest
from onyx.tools.constants import SEARCH_TOOL_ID
from onyx.tools.tool_implementations.search.search_tool import SearchTool
from onyx.utils.audit import AuditEventCategory
from tests.utils.audit import events_for, use_audit_settings

_API = "onyx.server.features.search.api"
_QUERY = "what is the refund policy"

pytestmark = pytest.mark.usefixtures("enterprise_audit")


@pytest.fixture
def search_tool() -> Generator[MagicMock, None, None]:
    tool = MagicMock()
    tool.id = 7
    tool.in_code_tool_id = SEARCH_TOOL_ID
    search_tool_cls = MagicMock()
    search_tool_cls.NAME = SearchTool.NAME
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
        yield search_tool_cls.return_value


def test_search_writes_the_retrieved_document_ids(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    search_tool: MagicMock,
) -> None:
    use_audit_settings(monkeypatch, categories=(AuditEventCategory.SEARCH,))
    docs = [MagicMock(spec=SearchDoc, document_id=f"doc-{i}") for i in range(2)]
    search_tool.search.return_value = ToolResult(
        content=json.dumps({"results": []}),
        details=SearchDocsResponse.model_construct(search_docs=docs),
    )
    user = MagicMock(spec=User)
    user.id = uuid4()

    search(
        request=SearchRequest(query=_QUERY),
        user=user,
        db_session=MagicMock(),
    )

    (event,) = events_for(caplog, "search.query")
    assert event["actor"]["user_id"] == str(user.id)
    assert event["extra"]["api"] == "search_api"
    assert event["extra"]["retrieved_document_ids"] == ["doc-0", "doc-1"]
    # Query text is off by default.
    assert "query_text" not in event["extra"]
