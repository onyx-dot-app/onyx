"""Verify that all Postgres connection pools are disposed on app shutdown.

Regression test for an observed leak under ``uvicorn --reload``: each worker
restart spawned new pools without disposing the prior worker's pools, so
Postgres held the orphaned connections until its server-side timeouts kicked
them out. After a handful of reload cycles, ``max_connections`` was exhausted
and the api server hung.

These tests exercise each disposal function directly. A higher-level
integration check would re-run the FastAPI lifespan, but the lifespan touches
auth, telemetry, vespa, and the file store — far more scaffolding than the
behavior we care about here, which is that ``dispose()`` is in fact called and
the cached engine references are released.
"""

from __future__ import annotations

from contextlib import ExitStack
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

import onyx.db.engine.async_sql_engine as async_sql_engine
from onyx.db.engine.async_sql_engine import reset_sqlalchemy_async_engine
from onyx.db.engine.sql_engine import SqlEngine


def test_reset_engine_disposes_and_clears_sync_engine() -> None:
    fake_engine = MagicMock()
    SqlEngine._engine = fake_engine
    try:
        SqlEngine.reset_engine()
        fake_engine.dispose.assert_called_once_with()
        assert SqlEngine._engine is None
    finally:
        SqlEngine._engine = None


def test_reset_engine_is_a_noop_when_uninitialized() -> None:
    # Make sure the test is starting from a clean slate.
    SqlEngine._engine = None
    SqlEngine.reset_engine()  # should not raise
    assert SqlEngine._engine is None


def test_reset_readonly_engine_disposes_and_clears() -> None:
    fake_readonly = MagicMock()
    SqlEngine._readonly_engine = fake_readonly
    try:
        SqlEngine.reset_readonly_engine()
        fake_readonly.dispose.assert_called_once_with()
        assert SqlEngine._readonly_engine is None
    finally:
        SqlEngine._readonly_engine = None


def test_reset_readonly_engine_is_a_noop_when_uninitialized() -> None:
    SqlEngine._readonly_engine = None
    SqlEngine.reset_readonly_engine()  # should not raise
    assert SqlEngine._readonly_engine is None


@pytest.mark.asyncio
async def test_reset_async_engine_disposes_and_clears() -> None:
    fake_async = MagicMock()
    fake_async.dispose = AsyncMock()
    async_sql_engine._ASYNC_ENGINE = fake_async
    try:
        await reset_sqlalchemy_async_engine()
        fake_async.dispose.assert_awaited_once_with()
        assert async_sql_engine._ASYNC_ENGINE is None
    finally:
        async_sql_engine._ASYNC_ENGINE = None


@pytest.mark.asyncio
async def test_reset_async_engine_is_a_noop_when_uninitialized() -> None:
    async_sql_engine._ASYNC_ENGINE = None
    await reset_sqlalchemy_async_engine()  # should not raise
    assert async_sql_engine._ASYNC_ENGINE is None


@pytest.mark.asyncio
async def test_lifespan_shutdown_disposes_all_three_engines() -> None:
    """End-to-end check: the FastAPI lifespan's shutdown phase must dispose
    each engine. The lifespan touches a lot of other startup machinery; we
    patch it out so this test is hermetic and only asserts the disposal calls.
    """
    from onyx import main as onyx_main

    sync_engine = MagicMock()
    readonly_engine = MagicMock()
    async_engine_mock = MagicMock()
    async_engine_mock.dispose = AsyncMock()

    # Replace the engines with mocks and stub out every other startup side
    # effect so we can reach the shutdown phase quickly.
    with ExitStack() as stack:
        stack.enter_context(patch.object(SqlEngine, "set_app_name"))
        stack.enter_context(patch.object(SqlEngine, "init_engine"))
        stack.enter_context(patch.object(SqlEngine, "init_readonly_engine"))
        stack.enter_context(
            patch.object(SqlEngine, "get_engine", return_value=sync_engine)
        )
        stack.enter_context(
            patch.object(SqlEngine, "get_readonly_engine", return_value=readonly_engine)
        )
        reset_sync = stack.enter_context(patch.object(SqlEngine, "reset_engine"))
        reset_ro = stack.enter_context(patch.object(SqlEngine, "reset_readonly_engine"))
        reset_async = stack.enter_context(
            patch.object(onyx_main, "reset_sqlalchemy_async_engine", new=AsyncMock())
        )
        stack.enter_context(
            patch.object(
                onyx_main,
                "get_sqlalchemy_async_engine",
                return_value=async_engine_mock,
            )
        )
        stack.enter_context(
            patch.object(onyx_main, "setup_postgres_connection_pool_metrics")
        )
        stack.enter_context(patch.object(onyx_main, "validate_no_vector_db_settings"))
        stack.enter_context(patch.object(onyx_main, "validate_cache_backend_settings"))
        stack.enter_context(patch.object(onyx_main, "validate_registry"))
        stack.enter_context(
            patch.object(
                onyx_main,
                "fetch_versioned_implementation",
                return_value=lambda: None,
            )
        )
        stack.enter_context(patch.object(onyx_main, "setup_tracing"))
        stack.enter_context(
            patch.object(onyx_main, "warm_up_connections", new=AsyncMock())
        )
        stack.enter_context(patch.object(onyx_main, "get_session_with_current_tenant"))
        stack.enter_context(patch.object(onyx_main, "setup_onyx"))
        stack.enter_context(patch.object(onyx_main, "get_default_file_store"))
        stack.enter_context(patch.object(onyx_main, "get_or_generate_uuid"))
        stack.enter_context(patch.object(onyx_main, "optional_telemetry"))
        stack.enter_context(patch.object(onyx_main, "MULTI_TENANT", False))
        stack.enter_context(
            patch.object(onyx_main, "AUTH_RATE_LIMITING_ENABLED", False)
        )
        stack.enter_context(patch.object(onyx_main, "DISABLE_VECTOR_DB", False))
        stack.enter_context(patch.object(onyx_main, "OAUTH_CLIENT_ID", ""))
        stack.enter_context(patch.object(onyx_main, "OAUTH_CLIENT_SECRET", ""))
        stack.enter_context(patch.object(onyx_main, "SYSTEM_RECURSION_LIMIT", None))

        async with onyx_main.lifespan(MagicMock()):
            # Inside the lifespan body: startup ran, shutdown not yet.
            reset_sync.assert_not_called()
            reset_ro.assert_not_called()
            reset_async.assert_not_called()

        # After exiting the context manager: shutdown ran.
        reset_async.assert_awaited_once_with()
        reset_sync.assert_called_once_with()
        reset_ro.assert_called_once_with()
