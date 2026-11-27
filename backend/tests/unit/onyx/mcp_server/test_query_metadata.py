"""The MCP metadata-query tool forwards its arguments to /search/postgres-query."""

import json
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest
import pytest_asyncio
from fastmcp.exceptions import ToolError
from fastmcp.server.auth.auth import AccessToken

import onyx.mcp_server.tools.search as search_module
import onyx.mcp_server.utils as utils_module
from tests.unit.onyx.mcp_server.tool_result import error_payload

_TOKEN = AccessToken(token="test-token", client_id="test", scopes=[])


@dataclass
class _Stub:
    requests: list[dict[str, Any]] = field(default_factory=list)
    status: int = 200
    response: dict[str, Any] = field(
        default_factory=lambda: {"result": "3 matching documents.", "is_error": False}
    )


@pytest_asyncio.fixture
async def stub(monkeypatch: pytest.MonkeyPatch) -> AsyncGenerator[_Stub, None]:
    """Stand in for the API server the MCP tool calls."""
    state = _Stub()

    def _handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/persona"):
            return httpx.Response(
                200, json=[{"id": 7, "name": "Support", "description": "support"}]
            )
        if path.endswith("/search/postgres-query"):
            state.requests.append(json.loads(request.content))
            return httpx.Response(state.status, json=state.response)
        return httpx.Response(404, json={"detail": f"unexpected path {path}"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(_handler))
    monkeypatch.setattr(utils_module, "_http_client", client)
    monkeypatch.setattr(search_module, "require_access_token", lambda: _TOKEN)
    yield state
    await client.aclose()


@pytest.mark.asyncio
async def test_sends_only_the_given_arguments(stub: _Stub) -> None:
    payload = await search_module.query_metadata(
        table="document",
        count=True,
        source_type=["jira", "linear"],
        updated_after="2026-11-01",
    )
    assert payload == {"result": "3 matching documents."}
    assert stub.requests == [
        {
            "arguments": {
                "table": "document",
                "count": True,
                "source_type": ["jira", "linear"],
                "updated_after": "2026-11-01",
            },
            "persona_id": None,
        }
    ]


@pytest.mark.asyncio
async def test_a_list_filter_takes_one_value(stub: _Stub) -> None:
    await search_module.query_metadata(table="document", title_contains="pricing")
    assert stub.requests[0]["arguments"]["title_contains"] == "pricing"


@pytest.mark.asyncio
async def test_agent_resolves_to_its_persona(stub: _Stub) -> None:
    await search_module.query_metadata(table="document", agent="Support")
    assert stub.requests[0]["persona_id"] == 7

    with pytest.raises(ToolError) as unknown:
        await search_module.query_metadata(table="document", agent="Nobody")
    assert "Agent 'Nobody' not found" in error_payload(unknown.value)["error"]
    assert len(stub.requests) == 1


@pytest.mark.asyncio
async def test_rejected_query_and_disabled_tool_return_errors(stub: _Stub) -> None:
    stub.response = {"result": "Invalid order_by 'score'.", "is_error": True}
    with pytest.raises(ToolError) as rejected:
        await search_module.query_metadata(table="document")
    assert error_payload(rejected.value)["error"] == "Invalid order_by 'score'."

    stub.status = 403
    stub.response = {
        "error_code": "FEATURE_DISABLED",
        "detail": "postgres_query is turned off.",
    }
    with pytest.raises(ToolError) as disabled:
        await search_module.query_metadata(table="document")
    assert error_payload(disabled.value)["error"] == "postgres_query is turned off."
