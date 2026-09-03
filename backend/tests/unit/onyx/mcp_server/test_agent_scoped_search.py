"""Agent scoping in the MCP document-search tool.

`agent` resolves a name to a persona id on the search call itself, so the
happy path needs no discovery round trip. A name that does not resolve must
fail rather than fall back to an unscoped search.
"""

import json
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Any

import httpx
import pytest
import pytest_asyncio
from fastmcp.server.auth.auth import AccessToken

import onyx.mcp_server.tools.search as search_module
import onyx.mcp_server.utils as utils_module

_TOKEN = AccessToken(token="test-token", client_id="test", scopes=[])


@dataclass
class _Stub:
    """Bodies the tool sent to /search, and the agents /persona returns."""

    search_requests: list[dict[str, Any]]
    agents: list[dict[str, Any]]


@pytest_asyncio.fixture
async def stub(monkeypatch: pytest.MonkeyPatch) -> AsyncGenerator[_Stub, None]:
    """Stand in for the API server the MCP tools call."""
    state = _Stub(
        search_requests=[],
        agents=[
            {"id": 7, "name": "Support", "description": "Customer support"},
            {"id": 9, "name": "Engineering Wiki", "description": "Eng docs"},
        ],
    )

    def _handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/manage/indexed-sources"):
            return httpx.Response(200, json={"sources": ["github"]})
        if path.endswith("/persona"):
            return httpx.Response(200, json=state.agents)
        if path.endswith("/search"):
            state.search_requests.append(json.loads(request.content))
            return httpx.Response(200, json={"results": []})
        return httpx.Response(404, json={"detail": f"unexpected path {path}"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(_handler))
    monkeypatch.setattr(utils_module, "_http_client", client)
    monkeypatch.setattr(search_module, "require_access_token", lambda: _TOKEN)
    yield state
    await client.aclose()


@pytest.mark.asyncio
async def test_agent_name_resolves_to_persona_id(stub: _Stub) -> None:
    payload = await search_module.search_indexed_documents(
        query="anything", agent="Support"
    )

    assert "error" not in payload
    assert len(stub.search_requests) == 1
    assert stub.search_requests[0]["persona_id"] == 7


@pytest.mark.asyncio
async def test_agent_match_is_case_insensitive(stub: _Stub) -> None:
    await search_module.search_indexed_documents(query="anything", agent="sUpPoRt")

    assert stub.search_requests[0]["persona_id"] == 7


@pytest.mark.asyncio
async def test_search_without_agent_stays_unscoped(stub: _Stub) -> None:
    await search_module.search_indexed_documents(query="anything")

    assert stub.search_requests[0].get("persona_id") is None


@pytest.mark.asyncio
async def test_unknown_agent_errors_and_names_the_valid_ones(stub: _Stub) -> None:
    payload = await search_module.search_indexed_documents(
        query="anything", agent="no-such-agent"
    )

    assert payload["results"] == []
    assert "no-such-agent" in payload["error"]
    assert "Support" in payload["error"]
    assert "Engineering Wiki" in payload["error"]
    # The wrong scope returned as if it were right is worse than an error, so
    # the tool must not fall back to an unscoped search.
    assert stub.search_requests == []


@pytest.mark.asyncio
async def test_ambiguous_agent_name_errors(stub: _Stub) -> None:
    stub.agents.append({"id": 11, "name": "support", "description": "same name"})

    payload = await search_module.search_indexed_documents(
        query="anything", agent="SUPPORT"
    )

    assert payload["results"] == []
    assert "ambiguous" in payload["error"]
    assert stub.search_requests == []
