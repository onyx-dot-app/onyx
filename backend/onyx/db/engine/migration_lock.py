"""Advisory lock that makes concurrent `alembic upgrade` runs on one schema take turns.

Keyed per schema so parallel runs over different tenant ranges do not block each other.
"""

import asyncio
import zlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from onyx.utils.logger import setup_logger

logger = setup_logger()

# Two-int advisory keys do not collide with the single-bigint keys used elsewhere.
MIGRATION_LOCK_NAMESPACE = 0x4F4E5958
MIGRATION_LOCK_POLL_INTERVAL_SECONDS = 2.0


def migration_lock_key(schema_name: str) -> int:
    """Stable signed int4 key for a schema name."""
    unsigned_key = zlib.crc32(schema_name.encode("utf-8"))
    return unsigned_key - (1 << 32) if unsigned_key >= (1 << 31) else unsigned_key


@asynccontextmanager
async def schema_migration_lock(
    engine: AsyncEngine,
    schema_name: str,
    poll_interval_seconds: float = MIGRATION_LOCK_POLL_INTERVAL_SECONDS,
) -> AsyncIterator[None]:
    params = {
        "namespace": MIGRATION_LOCK_NAMESPACE,
        "key": migration_lock_key(schema_name),
    }
    async with engine.connect() as connection:
        connection = await connection.execution_options(isolation_level="AUTOCOMMIT")
        # Poll rather than block: a blocked pg_advisory_lock holds a snapshot, and
        # the holder's CREATE INDEX CONCURRENTLY would wait on it forever.
        logged_wait = False
        while not (
            await connection.execute(
                text("SELECT pg_try_advisory_lock(:namespace, :key)"), params
            )
        ).scalar_one():
            if not logged_wait:
                logger.info(
                    "Waiting for another migration run on schema %s to finish",
                    schema_name,
                )
                logged_wait = True
            await asyncio.sleep(poll_interval_seconds)

        try:
            yield
        finally:
            try:
                await connection.execute(
                    text("SELECT pg_advisory_unlock(:namespace, :key)"), params
                )
            except Exception:
                # Postgres releases the lock when this connection closes.
                logger.warning(
                    "Could not release migration lock for schema %s",
                    schema_name,
                    exc_info=True,
                )
