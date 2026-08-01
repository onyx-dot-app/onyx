"""Tenant enumeration across shards, exercised against two real databases.

Enumeration is what tells beat which tenants to schedule and tells the migration
runner which schemas to upgrade. Reading it from a single database silently drops
every tenant that has been moved off that database: no error, they just stop being
given work. These tests put schemas on two databases and check nothing is lost.

A second database on the same server stands in for a second instance — the seam
routes per-DSN, not per-host.
"""

from collections.abc import Generator
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

from onyx.configs.app_configs import POSTGRES_DB
from onyx.db.engine import shard_registry, tenant_utils
from onyx.db.engine.shard_registry import get_engine_for_shard
from onyx.db.engine.sql_engine import (
    SYNC_DB_API,
    SqlEngine,
    build_connection_string,
)
from onyx.db.engine.tenant_utils import (
    get_all_tenant_ids,
    get_schemas_needing_migration,
    get_tenant_ids_by_shard,
)

DEFAULT_SHARD = "default"
SECOND_SHARD = "shard-enum-b"


class _CapturedAlembicURL(Exception):
    """Aborts a migration run once the database it targets is known."""

    def __init__(self, url: str) -> None:
        super().__init__(url)
        self.url = url


def _admin_engine() -> Engine:
    """Engine on the `postgres` maintenance DB, for CREATE/DROP DATABASE."""
    from sqlalchemy import create_engine

    return create_engine(
        build_connection_string(db_api=SYNC_DB_API, db="postgres"),
        isolation_level="AUTOCOMMIT",
    )


def _create_schema(engine: Engine, schema: str) -> None:
    with engine.connect() as conn:
        conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
        conn.commit()


def _drop_schema(engine: Engine, schema: str) -> None:
    with engine.connect() as conn:
        conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        conn.commit()


def _stamp_alembic_version(engine: Engine, schema: str, revision: str) -> None:
    """Mark a schema as sitting at `revision`, as a completed migration would."""
    with engine.connect() as conn:
        conn.execute(
            text(
                f'CREATE TABLE IF NOT EXISTS "{schema}".alembic_version '
                "(version_num VARCHAR(32) NOT NULL PRIMARY KEY)"
            )
        )
        conn.execute(text(f'DELETE FROM "{schema}".alembic_version'))
        conn.execute(
            text(f'INSERT INTO "{schema}".alembic_version VALUES (:rev)'),
            {"rev": revision},
        )
        conn.commit()


@pytest.fixture(scope="module")
def second_database() -> Generator[str, None, None]:
    """Create a throwaway second database for the duration of the module."""
    db_name = f"onyx_enum_test_{uuid4().hex[:8]}"
    admin = _admin_engine()
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
        admin.dispose()


@pytest.fixture(scope="function")
def two_shards(
    second_database: str, monkeypatch: pytest.MonkeyPatch
) -> Generator[dict[str, Any], None, None]:
    """Two shards with one tenant schema on each.

    Yields the tenant ids plus the name of the second database.
    """
    SqlEngine.init_engine(pool_size=5, max_overflow=2)

    monkeypatch.setattr(
        shard_registry,
        "ONYX_DB_SHARDS_JSON",
        f'{{"{SECOND_SHARD}": {{"db": "{second_database}"}}}}',
    )
    monkeypatch.setattr(shard_registry, "ONYX_DB_DEFAULT_SHARD", DEFAULT_SHARD)
    monkeypatch.setattr(shard_registry, "ONYX_DB_CATALOG_SHARD", DEFAULT_SHARD)
    # Enumeration short-circuits to the default schema outside multi-tenant mode.
    monkeypatch.setattr(tenant_utils, "MULTI_TENANT", True)
    shard_registry.reset_shard_specs()

    tenant_a = f"tenant_{uuid4()}"
    tenant_b = f"tenant_{uuid4()}"

    _create_schema(get_engine_for_shard(DEFAULT_SHARD), tenant_a)
    _create_schema(get_engine_for_shard(SECOND_SHARD), tenant_b)

    yield {"tenant_a": tenant_a, "tenant_b": tenant_b, "second_db": second_database}

    _drop_schema(get_engine_for_shard(DEFAULT_SHARD), tenant_a)
    _drop_schema(get_engine_for_shard(SECOND_SHARD), tenant_b)
    shard_registry.reset_shard_specs()


@pytest.fixture(scope="function")
def one_shard(monkeypatch: pytest.MonkeyPatch) -> Generator[str, None, None]:
    """No `ONYX_DB_SHARDS`, i.e. every deployment that exists today."""
    SqlEngine.init_engine(pool_size=5, max_overflow=2)

    monkeypatch.setattr(shard_registry, "ONYX_DB_SHARDS_JSON", "")
    monkeypatch.setattr(shard_registry, "ONYX_DB_DEFAULT_SHARD", DEFAULT_SHARD)
    monkeypatch.setattr(shard_registry, "ONYX_DB_CATALOG_SHARD", DEFAULT_SHARD)
    monkeypatch.setattr(tenant_utils, "MULTI_TENANT", True)
    shard_registry.reset_shard_specs()

    tenant_id = f"tenant_{uuid4()}"
    _create_schema(get_engine_for_shard(DEFAULT_SHARD), tenant_id)

    yield tenant_id

    _drop_schema(get_engine_for_shard(DEFAULT_SHARD), tenant_id)
    shard_registry.reset_shard_specs()


def test_enumeration_spans_every_shard(two_shards: dict[str, Any]) -> None:
    """The whole point: a tenant on the second database is still enumerated."""
    all_tenants = get_all_tenant_ids()

    assert two_shards["tenant_a"] in all_tenants
    assert two_shards["tenant_b"] in all_tenants


def test_grouping_reports_where_a_schema_physically_lives(
    two_shards: dict[str, Any],
) -> None:
    by_shard = get_tenant_ids_by_shard()

    assert set(by_shard) == {DEFAULT_SHARD, SECOND_SHARD}
    assert two_shards["tenant_a"] in by_shard[DEFAULT_SHARD]
    assert two_shards["tenant_a"] not in by_shard[SECOND_SHARD]
    assert two_shards["tenant_b"] in by_shard[SECOND_SHARD]
    assert two_shards["tenant_b"] not in by_shard[DEFAULT_SHARD]


def test_tenant_present_on_two_shards_is_enumerated_once(
    two_shards: dict[str, Any],
) -> None:
    """Mid-copy a schema exists on both its old and new shard. It is one tenant.

    Beat schedules one set of tasks per returned id, so a duplicate would double up
    every periodic task for that tenant.
    """
    tenant_a = two_shards["tenant_a"]
    _create_schema(get_engine_for_shard(SECOND_SHARD), tenant_a)
    try:
        by_shard = get_tenant_ids_by_shard()
        assert tenant_a in by_shard[DEFAULT_SHARD]
        assert tenant_a in by_shard[SECOND_SHARD]

        assert get_all_tenant_ids().count(tenant_a) == 1
    finally:
        _drop_schema(get_engine_for_shard(SECOND_SHARD), tenant_a)


def test_non_tenant_schemas_are_excluded(two_shards: dict[str, Any]) -> None:
    """Only schemas matching the tenant pattern count, on every shard."""
    engine = get_engine_for_shard(SECOND_SHARD)
    _create_schema(engine, "definitely_not_a_tenant")
    try:
        all_tenants = get_all_tenant_ids()
        assert "definitely_not_a_tenant" not in all_tenants
        assert "public" not in all_tenants
        # The real tenant on that same shard is still found.
        assert two_shards["tenant_b"] in all_tenants
        assert "definitely_not_a_tenant" not in get_tenant_ids_by_shard()[SECOND_SHARD]
    finally:
        _drop_schema(engine, "definitely_not_a_tenant")


def test_single_shard_enumeration_is_unchanged(one_shard: str) -> None:
    """With no sharding configured, enumeration is one query against one database."""
    by_shard = get_tenant_ids_by_shard()

    assert set(by_shard) == {DEFAULT_SHARD}
    assert one_shard in by_shard[DEFAULT_SHARD]
    assert get_all_tenant_ids() == sorted(by_shard[DEFAULT_SHARD])


def test_migration_check_reads_the_named_shard(two_shards: dict[str, Any]) -> None:
    """`get_schemas_needing_migration` must consult the shard holding the schema.

    It previously always used the default engine. A tenant already at head on another
    shard looks unmigrated from there — its schema isn't visible at all — so the
    runner would keep re-targeting it forever.
    """
    tenant_b = two_shards["tenant_b"]
    head = "abc123def456"
    _stamp_alembic_version(get_engine_for_shard(SECOND_SHARD), tenant_b, head)

    assert get_schemas_needing_migration([tenant_b], head, SECOND_SHARD) == []
    assert get_schemas_needing_migration([tenant_b], head, DEFAULT_SHARD) == [tenant_b]


def test_alembic_shard_option_selects_that_database(
    two_shards: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """`-x shard=<name>` must change the database alembic connects to.

    Asserting on a generated URL is not enough — env.py builds its own engine, and a
    previous version of this seam accepted a target it then ignored. This intercepts
    `create_async_engine` inside the real alembic -> env.py path and aborts as soon
    as the target is known, so the migration tree never has to run.
    """
    import os

    import sqlalchemy.ext.asyncio as sa_asyncio
    from alembic import command
    from alembic.config import Config

    def _capture(url: Any, *_: Any, **__: Any) -> Any:
        raise _CapturedAlembicURL(str(url))

    # env.py imports `create_async_engine` at module scope and alembic re-executes
    # env.py per run, so patching the source module is picked up by the real path.
    monkeypatch.setattr(sa_asyncio, "create_async_engine", _capture)

    root_dir = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..")
    )

    for shard_name, expected_db in (
        (DEFAULT_SHARD, POSTGRES_DB),
        (SECOND_SHARD, two_shards["second_db"]),
    ):
        cfg = Config(os.path.join(root_dir, "alembic.ini"))
        cfg.set_main_option("script_location", os.path.join(root_dir, "alembic"))
        cfg.attributes["configure_logger"] = False
        cfg.cmd_opts = _x_args(
            [f"schemas={two_shards['tenant_a']}", f"shard={shard_name}"]
        )

        captured: str | None = None
        try:
            command.upgrade(cfg, "head")
        except Exception as e:
            captured = _unwrap_captured_url(e)

        assert captured is not None, f"never reached engine creation for {shard_name}"
        assert captured.endswith(f"/{expected_db}"), (
            f"-x shard={shard_name} targeted {captured}, expected database {expected_db}"
        )


def _x_args(x: list[str]) -> Any:
    from types import SimpleNamespace

    return SimpleNamespace(x=x)


def _unwrap_captured_url(exc: BaseException) -> str | None:
    cause: BaseException | None = exc
    while cause is not None:
        if isinstance(cause, _CapturedAlembicURL):
            return cause.url
        cause = cause.__cause__ or cause.__context__
    return None
