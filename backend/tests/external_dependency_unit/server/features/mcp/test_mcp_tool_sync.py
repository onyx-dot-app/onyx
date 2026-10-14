"""Tool sync for an MCP server (`_sync_mcp_server_tools`) against a real DB.

Regression coverage for onyx-dot-app/onyx#14346: one OAuth connect fired two
concurrent tool refreshes and every tool was stored twice."""

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from mcp.types import Tool as MCPLibTool
from sqlalchemy.orm import Session

from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import (
    MCPAuthenticationPerformer,
    MCPAuthenticationType,
    MCPTransport,
)
from onyx.db.mcp import create_mcp_server__no_commit
from onyx.db.models import MCPServer, Tool
from onyx.db.tools import get_tools_by_mcp_server_id
from onyx.server.features.mcp import api as mcp_api
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR


def _make_server(db_session: Session) -> MCPServer:
    server = create_mcp_server__no_commit(
        owner_email="admin@example.com",
        name=f"sync-{uuid4().hex[:8]}",
        description=None,
        server_url=f"https://sync-{uuid4().hex[:8]}.example.com/mcp",
        auth_type=MCPAuthenticationType.API_TOKEN,
        transport=MCPTransport.STREAMABLE_HTTP,
        auth_performer=MCPAuthenticationPerformer.ADMIN,
        db_session=db_session,
    )
    db_session.commit()
    return server


def _discovered(names: list[str]) -> list[MCPLibTool]:
    return [
        MCPLibTool(name=name, description=f"{name} desc", inputSchema={})
        for name in names
    ]


def _names(db_session: Session, server_id: int) -> list[str]:
    db_session.expire_all()
    return sorted(t.name for t in get_tools_by_mcp_server_id(server_id, db_session))


def test_concurrent_syncs_store_each_tool_once(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = _make_server(db_session)
    names = [f"tool_{i}" for i in range(54)]

    # Mirror the production race: both callers read the tool table before
    # either writes. A short pause after the read widens that window.
    real_get_tools = mcp_api.get_tools_by_mcp_server_id

    def slow_get_tools(
        mcp_server_id: int,
        db_session: Session,
        *,
        only_enabled: bool = False,
        order_by_id: bool = False,
    ) -> list[Tool]:
        rows = real_get_tools(
            mcp_server_id,
            db_session,
            only_enabled=only_enabled,
            order_by_id=order_by_id,
        )
        time.sleep(0.5)
        return rows

    monkeypatch.setattr(mcp_api, "get_tools_by_mcp_server_id", slow_get_tools)

    start = threading.Barrier(2)

    def run_sync() -> None:
        CURRENT_TENANT_ID_CONTEXTVAR.set(POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE)
        with get_session_with_current_tenant() as session:
            start.wait(timeout=10)
            mcp_api._sync_mcp_server_tools(server.id, _discovered(names), session)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(run_sync) for _ in range(2)]
        for future in futures:
            future.result(timeout=30)

    assert _names(db_session, server.id) == sorted(names)


def test_repeated_name_in_one_discovery_is_stored_once(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    server = _make_server(db_session)

    mcp_api._sync_mcp_server_tools(
        server.id, _discovered(["dup", "dup", "other"]), db_session
    )

    assert _names(db_session, server.id) == ["dup", "other"]


def test_sync_collapses_existing_duplicates_and_drops_stale_tools(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    server = _make_server(db_session)
    for name in ("keep", "keep", "stale"):
        db_session.add(Tool(name=name, description="", mcp_server_id=server.id))
    db_session.commit()
    keeper_id = min(
        t.id
        for t in get_tools_by_mcp_server_id(server.id, db_session)
        if t.name == "keep"
    )

    mcp_api._sync_mcp_server_tools(server.id, _discovered(["keep"]), db_session)

    remaining = get_tools_by_mcp_server_id(server.id, db_session)
    assert [(t.id, t.name) for t in remaining] == [(keeper_id, "keep")]
