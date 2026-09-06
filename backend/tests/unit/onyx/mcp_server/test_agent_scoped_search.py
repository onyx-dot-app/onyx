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
    """Bodies the tool sent to /search, plus what the API server returns."""

    search_requests: list[dict[str, Any]]
    agents: list[dict[str, Any]]
    sources: list[str]


async def _unreachable_indexed_sources(_access_token: AccessToken) -> list[str]:
    raise AssertionError("indexed-sources must not be consulted for an agent search")


@pytest_asyncio.fixture
async def stub(monkeypatch: pytest.MonkeyPatch) -> AsyncGenerator[_Stub, None]:
    """Stand in for the API server the MCP tools call."""
    state = _Stub(
        search_requests=[],
        agents=[
            {"id": 7, "name": "Support", "description": "Customer support"},
            {"id": 9, "name": "Engineering Wiki", "description": "Eng docs"},
        ],
        sources=["github"],
    )

    def _handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/manage/indexed-sources"):
            return httpx.Response(200, json={"sources": state.sources})
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
async def test_agent_with_document_sets_is_rejected(stub: _Stub) -> None:
    """Explicit sets replace an agent's scope downstream, so both is refused."""
    payload = await search_module.search_indexed_documents(
        query="anything", agent="Support", document_set_names=["Engineering Wiki"]
    )

    assert payload["results"] == []
    assert "not both" in payload["error"]
    assert stub.search_requests == []


@pytest.mark.asyncio
async def test_agent_search_runs_without_connector_sources(
    stub: _Stub, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An agent can carry attached documents, so the no-sources guard, which
    only counts connector sources, must not block an agent-scoped search."""
    monkeypatch.setattr(
        search_module,
        "get_indexed_sources",
        _unreachable_indexed_sources,
    )

    payload = await search_module.search_indexed_documents(
        query="anything", agent="Support"
    )

    assert "error" not in payload
    assert stub.search_requests[0]["persona_id"] == 7


@pytest.mark.asyncio
async def test_unknown_agent_error_survives_empty_source_list(stub: _Stub) -> None:
    """The agent error is more actionable than the generic no-sources message."""
    stub.sources = []

    payload = await search_module.search_indexed_documents(
        query="anything", agent="no-such-agent"
    )

    assert "no-such-agent" in payload["error"]
    assert "Support" in payload["error"]


@pytest.mark.asyncio
async def test_ambiguous_agent_name_errors(stub: _Stub) -> None:
    stub.agents.append({"id": 11, "name": "support", "description": "same name"})

    payload = await search_module.search_indexed_documents(
        query="anything", agent="SUPPORT"
    )

    assert payload["results"] == []
    assert "ambiguous" in payload["error"]
    assert stub.search_requests == []
