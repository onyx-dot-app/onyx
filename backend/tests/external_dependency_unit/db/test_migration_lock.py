"""schema_migration_lock against a real Postgres, as used by alembic/env.py."""

import asyncio
from collections.abc import AsyncGenerator
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import pool, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from onyx.db.engine.migration_lock import (
    MIGRATION_LOCK_NAMESPACE,
    migration_lock_key,
    schema_migration_lock,
)
from onyx.db.engine.sql_engine import build_connection_string


@pytest_asyncio.fixture
async def engine() -> AsyncGenerator[AsyncEngine, None]:
    engine = create_async_engine(build_connection_string(), poolclass=pool.NullPool)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def version_table(engine: AsyncEngine) -> AsyncGenerator[str, None]:
    """Stand-in for alembic_version: one row holding the current revision."""
    table_name = f"migration_lock_probe_{uuid4().hex[:12]}"
    async with engine.begin() as connection:
        await connection.execute(text(f"CREATE TABLE {table_name} (revision TEXT)"))
        await connection.execute(text(f"INSERT INTO {table_name} VALUES ('base')"))
    yield table_name
    async with engine.begin() as connection:
        await connection.execute(text(f"DROP TABLE {table_name}"))


async def _upgrade_to_head(engine: AsyncEngine, schema_name: str, table: str) -> bool:
    """Mimics `alembic upgrade head`: read the revision, migrate, commit.

    Returns True if this run applied the migration, False if it was a no-op.
    """
    async with schema_migration_lock(engine, schema_name, poll_interval_seconds=0.05):
        async with engine.connect() as connection:
            revision = (
                await connection.execute(text(f"SELECT revision FROM {table}"))
            ).scalar_one()
            if revision == "head":
                return False
            # Widens the race window so an unserialized second run would read 'base'.
            await asyncio.sleep(0.5)
            await connection.execute(text(f"UPDATE {table} SET revision = 'head'"))
            await connection.commit()
            return True


async def _lock_is_free(engine: AsyncEngine, schema_name: str) -> bool:
    params = {
        "namespace": MIGRATION_LOCK_NAMESPACE,
        "key": migration_lock_key(schema_name),
    }
    async with engine.connect() as connection:
        acquired = (
            await connection.execute(
                text("SELECT pg_try_advisory_lock(:namespace, :key)"), params
            )
        ).scalar_one()
        if acquired:
            await connection.execute(
                text("SELECT pg_advisory_unlock(:namespace, :key)"), params
            )
        return bool(acquired)


@pytest.mark.asyncio
async def test_concurrent_upgrades_serialize_and_later_runs_are_noops(
    engine: AsyncEngine, version_table: str
) -> None:
    schema_name = f"lock_test_{uuid4().hex}"

    results = await asyncio.gather(
        *(_upgrade_to_head(engine, schema_name, version_table) for _ in range(3))
    )

    assert sorted(results) == [False, False, True]
    assert await _lock_is_free(engine, schema_name)


@pytest.mark.asyncio
async def test_lock_is_released_when_the_migration_fails(engine: AsyncEngine) -> None:
    schema_name = f"lock_test_{uuid4().hex}"

    with pytest.raises(RuntimeError):
        async with schema_migration_lock(engine, schema_name):
            assert not await _lock_is_free(engine, schema_name)
            raise RuntimeError("migration failed")

    assert await _lock_is_free(engine, schema_name)


@pytest.mark.asyncio
async def test_different_schemas_do_not_block_each_other(engine: AsyncEngine) -> None:
    async with schema_migration_lock(engine, f"lock_test_{uuid4().hex}"):
        async with asyncio.timeout(5):
            async with schema_migration_lock(engine, f"lock_test_{uuid4().hex}"):
                pass


@pytest.mark.asyncio
async def test_waiting_run_does_not_block_create_index_concurrently(
    engine: AsyncEngine, version_table: str
) -> None:
    """Migrations such as e0ea2ae62e51 build indexes CONCURRENTLY while holding the lock."""
    schema_name = f"lock_test_{uuid4().hex}"
    holder_has_lock = asyncio.Event()

    async def waiting_run() -> None:
        await holder_has_lock.wait()
        async with schema_migration_lock(
            engine, schema_name, poll_interval_seconds=0.05
        ):
            pass

    async with schema_migration_lock(engine, schema_name):
        waiter = asyncio.create_task(waiting_run())
        holder_has_lock.set()
        await asyncio.sleep(0.2)
        async with engine.connect() as connection:
            connection = await connection.execution_options(
                isolation_level="AUTOCOMMIT"
            )
            await connection.execute(text("SET statement_timeout = '10s'"))
            await connection.execute(
                text(
                    f"CREATE INDEX CONCURRENTLY ix_{version_table} "
                    f"ON {version_table} (revision)"
                )
            )
    await asyncio.wait_for(waiter, timeout=5)
