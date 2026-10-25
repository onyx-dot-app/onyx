"""MCP discovery includes searchable sources hidden from the connector UI."""

import json
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from typing import Any, cast

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI, Request
from fastapi.routing import APIRoute
from fastmcp.server.auth.auth import AccessToken
from sqlalchemy import Column, Enum, MetaData, Table, create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import onyx.mcp_server.resources.indexed_sources as resource_module
import onyx.mcp_server.tools.search as search_module
import onyx.mcp_server.utils as utils_module
from onyx.configs.constants import DocumentSource
from onyx.db.engine.sql_engine import get_session
from onyx.db.models import User
from onyx.server.documents.connector import get_indexed_sources

_TOKEN = AccessToken(token="test-token", client_id="test", scopes=[])


@dataclass
class _SourceAPI:
    source: DocumentSource
    client: httpx.AsyncClient
    requests: list[dict[str, Any]] = field(default_factory=list)


@pytest_asyncio.fixture(
    params=[DocumentSource.INGESTION_API, DocumentSource.CRAFT_FILE]
)
async def source_api(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> AsyncGenerator[_SourceAPI, None]:
    source = cast(DocumentSource, request.param)
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    # The discovery query reads only this column. Keep its real SQLAlchemy enum
    # mapping without creating unrelated PostgreSQL tables in the unit test.
    table = Table(
        "connector",
        MetaData(),
        Column("source", Enum(DocumentSource, native_enum=False)),
    )
    table.create(engine)
    with engine.begin() as connection:
        connection.execute(table.insert(), [{"source": source}, {"source": source}])

    app = FastAPI()
    app.add_api_route("/manage/indexed-sources", get_indexed_sources)
    route = app.routes[-1]
    assert isinstance(route, APIRoute)

    with Session(engine) as session:
        for dependency in route.dependant.dependencies:
            if dependency.call is get_session:
                app.dependency_overrides[get_session] = lambda: session
            elif dependency.name == "_":
                # Authentication is external to this inventory contract.
                assert dependency.call is not None
                app.dependency_overrides[dependency.call] = lambda: User(
                    email="test@example.com"
                )

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            state = _SourceAPI(source=source, client=client)

            @app.post("/search")
            async def search(request: Request) -> dict[str, Any]:
                assert request.headers["Authorization"] == f"Bearer {_TOKEN.token}"
                state.requests.append(await request.json())
                return {
                    "results": [
                        {
                            "citation_id": 1,
                            "title": "Existing document",
                            "content": "Indexed content",
                            "link": None,
                            "source_type": source.value,
                            "updated_at": None,
                        }
                    ]
                }

            monkeypatch.setattr(utils_module, "_http_client", client)
            monkeypatch.setattr(search_module, "require_access_token", lambda: _TOKEN)
            monkeypatch.setattr(resource_module, "require_access_token", lambda: _TOKEN)
            yield state
    engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("explicit_filter", [False, True])
async def test_internal_documents_are_searchable(
    source_api: _SourceAPI, explicit_filter: bool
) -> None:
    sources = [source_api.source.value] if explicit_filter else None

    result = await search_module.search_indexed_documents(
        query="Indexed content", source_types=sources
    )

    assert "error" not in result
    assert result["results"][0]["content"] == "Indexed content"
    assert source_api.requests[0].get("sources") == sources
    assert source_api.requests[0].get("persona_id") is None


@pytest.mark.asyncio
async def test_internal_sources_remain_hidden_by_default(
    source_api: _SourceAPI,
) -> None:
    response = await source_api.client.get("/manage/indexed-sources")

    assert response.status_code == 200
    assert response.json() == {"sources": []}


@pytest.mark.asyncio
async def test_opt_in_lists_each_internal_source_once(source_api: _SourceAPI) -> None:
    response = await source_api.client.get(
        "/manage/indexed-sources", params={"include_internal": "true"}
    )

    assert response.status_code == 200
    assert response.json() == {"sources": [source_api.source.value]}


@pytest.mark.asyncio
@pytest.mark.parametrize("source_api", [DocumentSource.GITHUB], indirect=True)
async def test_regular_sources_are_preserved(source_api: _SourceAPI) -> None:
    default = await source_api.client.get("/manage/indexed-sources")
    inclusive = await source_api.client.get(
        "/manage/indexed-sources", params={"include_internal": "true"}
    )

    assert default.json() == inclusive.json() == {"sources": ["github"]}


@pytest.mark.asyncio
async def test_resource_lists_internal_sources(source_api: _SourceAPI) -> None:
    result = await resource_module.indexed_sources_resource()

    assert json.loads(result) == [source_api.source.value]


@pytest.mark.asyncio
async def test_unknown_source_does_not_widen_search(source_api: _SourceAPI) -> None:
    result = await search_module.search_indexed_documents(
        query="Indexed content", source_types=["unknown-source"]
    )

    assert "unknown-source" in result["error"]
    assert source_api.requests == []
