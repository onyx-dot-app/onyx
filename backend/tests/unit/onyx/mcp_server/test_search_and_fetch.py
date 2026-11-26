"""Mapping and error cases of `search` and `fetch`, and the time_cutoff check."""

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
_WEB_DOMAIN = "https://onyx.example"


@dataclass
class _Stub:
    """What the API server returns, plus the paths the tools called."""

    paths: list[str] = field(default_factory=list)
    bodies: list[dict[str, Any]] = field(default_factory=list)
    search_results: list[dict[str, Any]] = field(default_factory=list)
    content_status: int = 200
    content_body: dict[str, Any] = field(default_factory=dict)


@pytest_asyncio.fixture
async def stub(monkeypatch: pytest.MonkeyPatch) -> AsyncGenerator[_Stub, None]:
    state = _Stub()

    def _handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        state.paths.append(path)
        if request.content:
            state.bodies.append(json.loads(request.content))
        if path.endswith("/manage/indexed-sources"):
            return httpx.Response(200, json={"sources": ["github"]})
        if path.endswith(("/search", "/search/raw")):
            return httpx.Response(200, json={"results": state.search_results})
        if path.endswith("/document/content"):
            return httpx.Response(state.content_status, json=state.content_body)
        return httpx.Response(404, json={"detail": f"unexpected path {path}"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(_handler))
    monkeypatch.setattr(utils_module, "_http_client", client)
    monkeypatch.setattr(search_module, "require_access_token", lambda: _TOKEN)
    monkeypatch.setattr(search_module, "WEB_DOMAIN", _WEB_DOMAIN)
    yield state
    await client.aclose()


def _result(document_id: str | None, link: str | None = None) -> dict[str, Any]:
    return {
        "citation_id": 1,
        "document_id": document_id,
        "title": f"Title of {document_id}",
        "content": "text",
        "link": link,
        "source_type": "jira",
        "updated_at": None,
    }


@pytest.mark.asyncio
async def test_malformed_time_cutoff_fails_before_any_api_call(stub: _Stub) -> None:
    with pytest.raises(ToolError) as exc:
        await search_module.search_indexed_documents(
            query="anything", time_cutoff="last tuesday"
        )

    payload = error_payload(exc.value)
    assert "time_cutoff" in payload["error"]
    assert payload["results"] == []
    assert stub.paths == []


@pytest.mark.asyncio
@pytest.mark.parametrize("time_cutoff", ["", "  "])
async def test_blank_time_cutoff_means_no_filter(stub: _Stub, time_cutoff: str) -> None:
    stub.search_results = [_result("doc")]

    await search_module.search_indexed_documents(
        query="anything", time_cutoff=time_cutoff
    )

    assert any(path.endswith("/search") for path in stub.paths)


@pytest.mark.asyncio
async def test_search_dedupes_by_document_and_builds_urls(stub: _Stub) -> None:
    stub.search_results = [
        _result("a/b?c d"),
        _result("a/b?c d"),
        _result(None),
        _result("with-link", "https://jira.example/PROJ-1"),
        _result("bare", "test-doc-123"),
        _result("ftp", "ftp://files.example/x"),
        _result("rel", "/relative/path"),
        _result("malformed", "http://[not-a-host"),
    ]

    output = await search_module.search("anything")

    assert [(hit.id, hit.url) for hit in output.results] == [
        ("a/b?c d", f"{_WEB_DOMAIN}/app/document?id=a%2Fb%3Fc%20d"),
        ("with-link", "https://jira.example/PROJ-1"),
        ("bare", f"{_WEB_DOMAIN}/app/document?id=bare"),
        ("ftp", f"{_WEB_DOMAIN}/app/document?id=ftp"),
        ("rel", f"{_WEB_DOMAIN}/app/document?id=rel"),
        ("malformed", f"{_WEB_DOMAIN}/app/document?id=malformed"),
    ]
    assert stub.bodies[-1]["skip_federated_search"] is True


@pytest.mark.asyncio
async def test_fetch_maps_not_found_and_backend_failures(stub: _Stub) -> None:
    stub.content_status = 404
    stub.content_body = {"error_code": "DOCUMENT_NOT_FOUND", "detail": "gone"}
    with pytest.raises(ToolError) as missing:
        await search_module.fetch("doc-1")
    assert "not found or is not accessible" in error_payload(missing.value)["error"]

    stub.content_status = 413
    stub.content_body = {"detail": "Document is larger than the read limit."}
    with pytest.raises(ToolError) as too_large:
        await search_module.fetch("doc-1")
    assert (
        error_payload(too_large.value)["error"]
        == "Document is larger than the read limit."
    )
