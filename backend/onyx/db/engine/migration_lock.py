"""Advisory lock that makes concurrent `alembic upgrade` runs on one schema take turns.

Keyed per schema so parallel runs over different tenant ranges do not block each other.
"""

import asyncio
import zlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
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
    # Transaction-scoped so PgBouncer transaction pooling pins the lock to its holder.
    # Waiters poll: a blocked lock call holds a snapshot that CREATE INDEX
    # CONCURRENTLY in the holder's migration would wait on forever.
    params = {
        "namespace": MIGRATION_LOCK_NAMESPACE,
        "key": migration_lock_key(schema_name),
    }
    async with engine.connect() as connection:
        logged_wait = False
        while True:
            transaction = await connection.begin()
            acquired = (
                await connection.execute(
                    text("SELECT pg_try_advisory_xact_lock(:namespace, :key)"),
                    params,
                )
            ).scalar_one()
            if acquired:
                # Stops a timeout kill from silently dropping the lock. As a
                # snapshot-free statement, it also replaces the SELECT's open
                # portal, which would otherwise pin a snapshot for the whole hold.
                await connection.execute(
                    text("SET LOCAL idle_in_transaction_session_timeout = 0")
                )
                break
            await transaction.rollback()
            if not logged_wait:
                logger.info(
                    "Waiting for another migration run on schema %s to finish",
                    schema_name,
                )
                logged_wait = True
            await asyncio.sleep(poll_interval_seconds)

        try:
            yield
        except BaseException:
            with suppress(Exception):
                await transaction.rollback()
            raise

        try:
            await transaction.commit()
        except DBAPIError as e:
            raise RuntimeError(
                f"Lost the migration lock connection for schema {schema_name}; "
                "another run may have migrated it concurrently"
            ) from e
