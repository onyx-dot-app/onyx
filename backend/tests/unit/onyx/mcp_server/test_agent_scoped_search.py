"""Filter resolution in the MCP document-search tool.

`agent`, `source_types` and `document_set_names` all resolve on the search call
itself, so the happy path needs no discovery round trip. A value that does not
resolve must fail rather than be dropped, and the error teaches the caller
without dumping the whole inventory.
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
from onyx.mcp_server.tools.search import _MAX_SUGGESTIONS

_TOKEN = AccessToken(token="test-token", client_id="test", scopes=[])


@dataclass
class _Stub:
    """Bodies the tool sent to /search, plus what the API server returns."""

    search_requests: list[dict[str, Any]]
    agents: list[dict[str, Any]]
    sources: list[str]
    document_sets: list[dict[str, Any]]
    # Stands in for a scoped PAT, which cannot hold BASIC_ACCESS.
    forbid_inventory: bool = False
    inventory_status: int | None = None


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
        document_sets=[
            {"name": "Engineering Wiki", "description": "eng"},
            {"name": "Sales Playbook", "description": "sales"},
        ],
    )

    def _handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        is_inventory = path.endswith("/manage/indexed-sources") or path.endswith(
            "/manage/document-set"
        )
        if is_inventory and state.inventory_status is not None:
            return httpx.Response(state.inventory_status, json={"detail": "boom"})
        if is_inventory and state.forbid_inventory:
            return httpx.Response(403, json={"detail": "insufficient permissions"})
        if path.endswith("/manage/indexed-sources"):
            return httpx.Response(200, json={"sources": state.sources})
        if path.endswith("/manage/document-set"):
            return httpx.Response(200, json=state.document_sets)
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
async def test_unknown_agent_errors_without_searching(stub: _Stub) -> None:
    payload = await search_module.search_indexed_documents(
        query="anything", agent="no-such-agent"
    )

    assert payload["results"] == []
    assert "no-such-agent" in payload["error"]
    # The wrong scope returned as if it were right is worse than an error, so
    # the tool must not fall back to an unscoped search.
    assert stub.search_requests == []


@pytest.mark.asyncio
@pytest.mark.usefixtures("stub")
async def test_near_miss_agent_name_is_suggested() -> None:
    """A stale or colloquial name is the common failure, so suggest the fix."""
    payload = await search_module.search_indexed_documents(
        query="anything", agent="Enginering Wiki"
    )

    assert "Did you mean" in payload["error"]
    assert "Engineering Wiki" in payload["error"]


@pytest.mark.asyncio
async def test_unknown_agent_error_stays_small_for_large_tenants(
    stub: _Stub,
) -> None:
    """Listing every agent duplicates the resource and costs tokens per call."""
    stub.agents = [
        {"id": i, "name": f"Team {i} Knowledge", "description": "d"} for i in range(40)
    ]

    payload = await search_module.search_indexed_documents(
        query="anything", agent="totally-unrelated"
    )

    assert "renamed or removed" in payload["error"]
    assert "agents" in payload["error"]
    assert payload["error"].count(",") <= _MAX_SUGGESTIONS


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
async def test_valid_filters_pass_through(stub: _Stub) -> None:
    await search_module.search_indexed_documents(
        query="anything",
        source_types=["github"],
        document_set_names=["Engineering Wiki"],
    )

    sent = stub.search_requests[0]
    assert sent["sources"] == ["github"]
    assert sent["document_sets"] == ["Engineering Wiki"]


@pytest.mark.asyncio
async def test_unindexed_source_type_errors_instead_of_being_dropped(
    stub: _Stub,
) -> None:
    """Silently skipping the filter returns a wider result set as if scoped."""
    payload = await search_module.search_indexed_documents(
        query="anything", source_types=["confluence"]
    )

    assert payload["results"] == []
    assert "confluence" in payload["error"]
    assert "github" in payload["error"]
    assert stub.search_requests == []


@pytest.mark.asyncio
async def test_unknown_document_set_errors_with_a_suggestion(stub: _Stub) -> None:
    payload = await search_module.search_indexed_documents(
        query="anything", document_set_names=["Enginering Wiki"]
    )

    assert payload["results"] == []
    assert "Did you mean" in payload["error"]
    assert "Engineering Wiki" in payload["error"]
    assert stub.search_requests == []


@pytest.mark.asyncio
async def test_search_survives_a_token_that_cannot_list_inventory(
    stub: _Stub,
) -> None:
    """No PAT scope grants BASIC_ACCESS, so the inventory endpoints 403 for
    every scoped token. Validation is a convenience and must not block a search
    the token is allowed to run."""
    stub.forbid_inventory = True

    payload = await search_module.search_indexed_documents(
        query="anything",
        source_types=["github"],
        document_set_names=["Engineering Wiki"],
    )

    assert "error" not in payload
    sent = stub.search_requests[0]
    assert sent["sources"] == ["github"]
    assert sent["document_sets"] == ["Engineering Wiki"]


@pytest.mark.asyncio
async def test_inventory_failure_that_is_not_permissions_still_errors(
    stub: _Stub,
) -> None:
    """A 500 is real trouble, not a scope limitation — keep failing loudly."""
    stub.inventory_status = 500

    payload = await search_module.search_indexed_documents(
        query="anything", source_types=["github"]
    )

    assert payload["results"] == []
    assert "Failed to check indexed sources" in payload["error"]
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
