"""Shared helpers for the shard suites.

All of them need the same thing: a real second database on the same server. The seam
routes per-DSN rather than per-host, so a second database is a faithful stand-in for a
second instance and keeps the tests self-contained.
"""

from collections.abc import Generator
from uuid import uuid4

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from onyx.db.engine.sql_engine import SYNC_DB_API, build_connection_string

# Must match ONYX_DB_DEFAULT_SHARD, which each suite's fixture pins.
DEFAULT_SHARD = "default"


def admin_engine() -> Engine:
    """Engine on the `postgres` maintenance DB, for CREATE/DROP DATABASE."""
    return create_engine(
        build_connection_string(db_api=SYNC_DB_API, db="postgres"),
        isolation_level="AUTOCOMMIT",
    )


def temporary_database(prefix: str) -> Generator[str, None, None]:
    """Yield a throwaway database, dropping it afterwards.

    Connections are terminated first: a pooled engine still holding one blocks
    DROP DATABASE and leaks the database into the next run.
    """
    db_name = f"{prefix}_{uuid4().hex[:8]}"
    admin = admin_engine()
    # dispose() is in its own finally so it runs even when CREATE DATABASE fails or
    # the drop below raises. A leaked admin pool holds a connection that blocks a
    # later DROP DATABASE — the exact failure this function exists to avoid.
    try:
        with admin.connect() as conn:
            conn.execute(text(f'CREATE DATABASE "{db_name}"'))
        try:
            yield db_name
        finally:
            with admin.connect() as conn:
                conn.execute(
                    text(
                        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                        "WHERE datname = :db AND pid <> pg_backend_pid()"
                    ),
                    {"db": db_name},
                )
                conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}"'))
    finally:
        admin.dispose()


def create_schema(engine: Engine, schema: str) -> None:
    with engine.connect() as conn:
        conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
        conn.commit()


def drop_schema(engine: Engine, schema: str) -> None:
    with engine.connect() as conn:
        conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        conn.commit()


def schema_exists(engine: Engine, schema: str) -> bool:
    with engine.connect() as conn:
        return (
            conn.execute(
                text("SELECT 1 FROM pg_namespace WHERE nspname = :n"),
                {"n": schema},
            ).first()
            is not None
        )
