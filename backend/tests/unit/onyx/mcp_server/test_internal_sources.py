"""MCP source discovery counts documents pushed through the Ingestion API.

The default Ingestion API connector always exists, so its source is listed only
once an Ingestion API connector holds documents. Craft files are never listed.
"""

import json
from collections.abc import AsyncGenerator, Awaitable, Callable
from typing import Any

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI, Request
from fastapi.routing import APIRoute
from fastmcp.server.auth.auth import AccessToken
from sqlalchemy import Column, Enum, Integer, MetaData, String, Table, create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import onyx.mcp_server.resources.indexed_sources as resource_module
import onyx.mcp_server.tools.search as search_module
import onyx.mcp_server.utils as utils_module
from onyx.configs.constants import DocumentSource
from onyx.db.engine.sql_engine import get_session
from onyx.db.models import User
from onyx.server.documents.connector import get_indexed_sources
from tests.unit.onyx.mcp_server.tool_result import tool_payload

_TOKEN = AccessToken(token="test-token", client_id="test", scopes=[])
_DEFAULT_INGESTION = (0, DocumentSource.INGESTION_API)

# Connector rows as (id, source), and the connector ids that hold a document.
_Seed = Callable[
    [list[tuple[int, DocumentSource]], list[int]], Awaitable[httpx.AsyncClient]
]


@pytest_asyncio.fixture
async def seed(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncGenerator[tuple[_Seed, list[dict[str, Any]]], None]:
    """Serve /manage/indexed-sources from a seeded SQLite DB, and stub /search."""
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    # Only the columns the discovery queries read, to avoid PostgreSQL types.
    metadata = MetaData()
    connector = Table(
        "connector",
        metadata,
        Column("id", Integer),
        Column("source", Enum(DocumentSource, native_enum=False)),
    )
    doc_link = Table(
        "document_by_connector_credential_pair",
        metadata,
        Column("id", String),
        Column("connector_id", Integer),
    )
    metadata.create_all(engine)
    search_requests: list[dict[str, Any]] = []
    session = Session(engine)
    clients: list[httpx.AsyncClient] = []

    app = FastAPI()
    app.add_api_route("/manage/indexed-sources", get_indexed_sources)
    route = app.routes[-1]
    assert isinstance(route, APIRoute)
    for dependency in route.dependant.dependencies:
        if dependency.call is get_session:
            app.dependency_overrides[get_session] = lambda: session
        elif dependency.name == "_":
            assert dependency.call is not None
            app.dependency_overrides[dependency.call] = lambda: User(
                email="test@example.com"
            )

    @app.post("/search")
    async def search(request: Request) -> dict[str, Any]:
        search_requests.append(await request.json())
        return {"results": []}

    async def _seed(
        connectors: list[tuple[int, DocumentSource]], docs_on: list[int]
    ) -> httpx.AsyncClient:
        with engine.begin() as connection:
            connection.execute(
                connector.insert(),
                [{"id": cid, "source": source} for cid, source in connectors],
            )
            if docs_on:
                connection.execute(
                    doc_link.insert(),
                    [{"id": f"doc-{cid}", "connector_id": cid} for cid in docs_on],
                )
        client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        )
        clients.append(client)
        monkeypatch.setattr(utils_module, "_http_client", client)
        monkeypatch.setattr(search_module, "require_access_token", lambda: _TOKEN)
        monkeypatch.setattr(resource_module, "require_access_token", lambda: _TOKEN)
        return client

    yield _seed, search_requests
    for client in clients:
        await client.aclose()
    session.close()
    engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("source_types", [None, ["ingestion_api"]])
async def test_ingested_documents_are_searchable(
    seed: tuple[_Seed, list[dict[str, Any]]], source_types: list[str] | None
) -> None:
    seed_db, search_requests = seed
    await seed_db([_DEFAULT_INGESTION, (5, DocumentSource.INGESTION_API)], [5])

    payload = tool_payload(
        await search_module.search_indexed_documents(
            query="ingested", source_types=source_types
        )
    )

    assert "error" not in payload
    assert len(search_requests) == 1
    assert search_requests[0].get("sources") == source_types
    assert json.loads(await resource_module.indexed_sources_resource()) == [
        "ingestion_api"
    ]


@pytest.mark.asyncio
async def test_empty_default_ingestion_connector_is_not_a_source(
    seed: tuple[_Seed, list[dict[str, Any]]],
) -> None:
    seed_db, search_requests = seed
    await seed_db([_DEFAULT_INGESTION], [])

    payload = tool_payload(
        await search_module.search_indexed_documents(query="anything")
    )

    assert "No document sources are indexed" in payload["error"]
    assert search_requests == []


@pytest.mark.asyncio
async def test_inventory_default_and_craft_files_are_unchanged(
    seed: tuple[_Seed, list[dict[str, Any]]],
) -> None:
    seed_db, _ = seed
    client = await seed_db(
        [
            _DEFAULT_INGESTION,
            (1, DocumentSource.GITHUB),
            (2, DocumentSource.CRAFT_FILE),
        ],
        [0, 1, 2],
    )

    default = await client.get("/manage/indexed-sources")
    with_ingestion = await client.get(
        "/manage/indexed-sources", params={"include_ingestion_api": "true"}
    )

    assert default.json() == {"sources": ["github"]}
    assert with_ingestion.json() == {"sources": ["github", "ingestion_api"]}
