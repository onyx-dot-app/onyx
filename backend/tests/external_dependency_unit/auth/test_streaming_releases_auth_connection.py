"""End-to-end proof that a streaming response holds no auth DB connection.

Runs the real optional_user dependency chain against real Postgres, streams a
response, and reads the connection pool's checked-out count from inside the
stream. Before the fix, the auth session's open read transaction kept one
connection checked out until the stream ended.
"""

import uuid
from collections.abc import Generator
from typing import Any

import pytest
from fastapi import Depends, FastAPI
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.pool import QueuePool

import onyx.db.engine.async_sql_engine as async_sql_engine
from onyx.auth import users
from onyx.auth.users import (
    get_user_manager,
    optional_fastapi_current_user,
    optional_user,
)
from onyx.db.engine.async_sql_engine import (
    get_async_session,
    get_sqlalchemy_async_engine,
)
from tests.external_dependency_unit.async_client_utils import (
    dispose_async_clients_lifespan,
)


@pytest.fixture
def pooled_async_engine(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    # The directory conftest forces NullPool, which has no checkout counter.
    # This test measures pool checkouts, so it needs the real queue pool.
    monkeypatch.setattr(async_sql_engine, "POSTGRES_USE_NULL_POOL", False)
    async_sql_engine.abandon_async_engines()
    yield
    # The app lifespan disposes the queue-pooled engine on the portal loop.
    # If the test failed before shutdown ran, the loop is gone, so only drop
    # the reference.
    async_sql_engine.abandon_async_engines()


@pytest.mark.usefixtures("pooled_async_engine")
def test_no_auth_connection_checked_out_mid_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def skip_refresh(*_: Any) -> None:
        return None

    monkeypatch.setattr(users, "_maybe_refresh_oauth_tokens", skip_refresh)

    class _FakeUser:
        id = uuid.uuid4()
        email = "stream-test@example.com"

    # Stand-in for fastapi-users' user lookup: query on the same request-scoped
    # session so the auth read transaction opens exactly as in production.
    async def fake_auth(
        session: AsyncSession = Depends(get_async_session),
    ) -> _FakeUser:
        await session.execute(text("SELECT 1"))
        return _FakeUser()

    app = FastAPI(lifespan=dispose_async_clients_lifespan)
    app.dependency_overrides[optional_fastapi_current_user] = fake_auth
    app.dependency_overrides[get_user_manager] = lambda: object()

    checked_out_mid_stream: list[int] = []

    @app.post("/stream")
    def stream_ep(_user: Any = Depends(optional_user)) -> StreamingResponse:
        def gen() -> Generator[str, None, None]:
            pool = get_sqlalchemy_async_engine().sync_engine.pool
            assert isinstance(pool, QueuePool)
            checked_out_mid_stream.append(pool.checkedout())
            yield "chunk\n"

        return StreamingResponse(gen(), media_type="text/plain")

    with TestClient(app) as client:
        resp = client.post("/stream")

    assert resp.status_code == 200
    assert checked_out_mid_stream == [0]
