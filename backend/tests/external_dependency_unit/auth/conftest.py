from collections.abc import Generator

import pytest

import onyx.db.engine.async_sql_engine as async_sql_engine


@pytest.fixture(autouse=True)
def null_pool_async_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[None, None, None]:
    # Pooled asyncpg connections bind to the creating loop; NullPool keeps the
    # engine usable across pytest-asyncio's per-test loops.
    monkeypatch.setattr(async_sql_engine, "POSTGRES_USE_NULL_POOL", True)
    async_sql_engine._ASYNC_ENGINE = None
    yield
    async_sql_engine._ASYNC_ENGINE = None
