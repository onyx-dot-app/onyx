"""get_async_session must yield engine-bound sessions, never connection-bound.

Engine-bound sessions release their pooled connection when each transaction
ends. A connection-bound session holds one connection for the dependency's
whole lifetime — on streaming endpoints, the entire response.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from onyx.db.engine.async_sql_engine import get_async_session


async def _assert_engine_bound(tenant_id: str | None) -> None:
    dep = get_async_session(tenant_id)
    session = await anext(dep)
    try:
        assert isinstance(session.bind, AsyncEngine)
        result = await session.execute(text("SELECT 1"))
        assert result.scalar() == 1
        await session.commit()
        assert not session.in_transaction()
    finally:
        await dep.aclose()


@pytest.mark.asyncio
async def test_default_schema_session_is_engine_bound() -> None:
    await _assert_engine_bound(None)


@pytest.mark.asyncio
async def test_tenant_schema_session_is_engine_bound() -> None:
    # Any non-default tenant id takes the schema-translation path. SELECT 1
    # references no schema, so the schema does not need to exist.
    await _assert_engine_bound("tenant_connection_release_check")
