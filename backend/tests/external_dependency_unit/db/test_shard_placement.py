"""Placement of *new* tenants onto a configured shard, against two real databases.

Routing (`test_shard_routing.py`) answers where an existing tenant lives. This suite
covers the step before that: deciding where a tenant that has no schema yet should be
created, and proving the schema physically lands there.

The invariant under test is an ordering one — the shard mapping has to be written
before the schema is created, because every subsequent provisioning step resolves the
tenant's database through the catalog. So the tests assert on which database the schema
actually appears in, not on what a helper returned.
"""

from collections.abc import Generator
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

from ee.onyx.server.tenants.schema_management import create_schema_if_not_exists
from onyx.db.engine import shard_registry, shard_routing
from onyx.db.engine.shard_registry import (
    ShardConfigurationError,
    get_catalog_engine,
    get_engine_for_shard,
)
from onyx.db.engine.shard_routing import (
    get_shard_for_new_tenant,
    invalidate_shard_cache,
)
from onyx.db.engine.shard_version import reset_shard_map_version_poller
from onyx.db.engine.sql_engine import SYNC_DB_API, SqlEngine, build_connection_string
from onyx.db.models import PublicBase, TenantShard
from onyx.db.tenant_shard import clear_tenant_placement, record_tenant_placement

DEFAULT_SHARD = "default"
SECOND_SHARD = "shard-test-b"


def _admin_engine() -> Engine:
    """Engine on the `postgres` maintenance DB, for CREATE/DROP DATABASE."""
    from sqlalchemy import create_engine

    return create_engine(
        build_connection_string(db_api=SYNC_DB_API, db="postgres"),
        isolation_level="AUTOCOMMIT",
    )


def _schema_exists(engine: Engine, tenant_id: str) -> bool:
    with engine.connect() as conn:
        return (
            conn.execute(
                text("SELECT 1 FROM pg_namespace WHERE nspname = :n"),
                {"n": tenant_id},
            ).first()
            is not None
        )


def _mapped_shard(tenant_id: str) -> str | None:
    with get_catalog_engine().connect() as conn:
        row = conn.execute(
            text("SELECT shard_name FROM public.tenant_shard WHERE tenant_id = :t"),
            {"t": tenant_id},
        ).first()
    return None if row is None else str(row[0])


def _drop_schema(engine: Engine, tenant_id: str) -> None:
    with engine.connect() as conn:
        conn.execute(text(f'DROP SCHEMA IF EXISTS "{tenant_id}" CASCADE'))
        conn.commit()


@pytest.fixture(scope="module")
def second_database() -> Generator[str, None, None]:
    db_name = f"onyx_place_test_{uuid4().hex[:8]}"
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
def placement_on_second_shard(
    second_database: str, monkeypatch: pytest.MonkeyPatch
) -> Generator[dict[str, Any], None, None]:
    """Two shards configured, with new tenants targeted at the second one."""
    SqlEngine.init_engine(pool_size=5, max_overflow=2)

    shards_json = f'{{"{SECOND_SHARD}": {{"db": "{second_database}"}}}}'
    monkeypatch.setattr(shard_registry, "ONYX_DB_SHARDS_JSON", shards_json)
    monkeypatch.setattr(shard_registry, "ONYX_DB_DEFAULT_SHARD", DEFAULT_SHARD)
    monkeypatch.setattr(shard_registry, "ONYX_DB_CATALOG_SHARD", DEFAULT_SHARD)
    monkeypatch.setattr(shard_registry, "ONYX_DB_NEW_TENANT_SHARD", SECOND_SHARD)
    # Routing short-circuits to the default shard outside multi-tenant mode.
    monkeypatch.setattr(shard_routing, "MULTI_TENANT", True)
    monkeypatch.setattr(shard_routing, "ONYX_DB_SHARD_OVERRIDES_JSON", "")

    shard_registry.reset_shard_specs()
    shard_routing.reset_shard_overrides()
    invalidate_shard_cache()
    reset_shard_map_version_poller()

    # `tenant_shard` normally arrives via the `schema_private` Alembic tree, which this
    # lane does not run. Only that table, so unrelated models can't break this suite.
    PublicBase.metadata.create_all(
        get_catalog_engine(),
        tables=[PublicBase.metadata.tables[f"public.{TenantShard.__tablename__}"]],
        checkfirst=True,
    )

    created: list[str] = []
    yield {"second_db": second_database, "created": created}

    for tenant_id in created:
        _drop_schema(get_engine_for_shard(DEFAULT_SHARD), tenant_id)
        _drop_schema(get_engine_for_shard(SECOND_SHARD), tenant_id)
        clear_tenant_placement(tenant_id)
    shard_registry.reset_shard_specs()
    invalidate_shard_cache()
    reset_shard_map_version_poller()


def test_new_tenants_target_the_configured_shard(
    placement_on_second_shard: dict[str, Any],  # noqa: ARG001
) -> None:
    assert get_shard_for_new_tenant() == SECOND_SHARD


def test_unknown_target_shard_raises_rather_than_using_default(
    placement_on_second_shard: dict[str, Any],  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fail closed. Falling back to default is the silent misplacement to avoid."""
    monkeypatch.setattr(shard_registry, "ONYX_DB_NEW_TENANT_SHARD", "no-such-shard")
    with pytest.raises(ShardConfigurationError):
        get_shard_for_new_tenant()


def test_recorded_placement_puts_the_schema_on_the_target_shard(
    placement_on_second_shard: dict[str, Any],
) -> None:
    """The whole point: recording placement first makes schema creation follow.

    The unplaced tenant in the same test is the control — it proves the assertion
    discriminates, rather than the second shard simply receiving everything.
    """
    placed = f"tenant_{uuid4()}"
    unplaced = f"tenant_{uuid4()}"
    placement_on_second_shard["created"].extend([placed, unplaced])

    record_tenant_placement(placed, get_shard_for_new_tenant())
    create_schema_if_not_exists(placed)
    create_schema_if_not_exists(unplaced)

    assert _schema_exists(get_engine_for_shard(SECOND_SHARD), placed)
    assert not _schema_exists(get_engine_for_shard(DEFAULT_SHARD), placed)

    assert _schema_exists(get_engine_for_shard(DEFAULT_SHARD), unplaced)
    assert not _schema_exists(get_engine_for_shard(SECOND_SHARD), unplaced)


def test_default_placement_writes_no_mapping_row(
    placement_on_second_shard: dict[str, Any],
) -> None:
    """Absence of a row already means "default"; keep new tenants on that same rule."""
    tenant_id = f"tenant_{uuid4()}"
    placement_on_second_shard["created"].append(tenant_id)

    record_tenant_placement(tenant_id, DEFAULT_SHARD)

    assert _mapped_shard(tenant_id) is None


def test_placement_is_recorded_and_cleared(
    placement_on_second_shard: dict[str, Any],
) -> None:
    tenant_id = f"tenant_{uuid4()}"
    placement_on_second_shard["created"].append(tenant_id)

    record_tenant_placement(tenant_id, SECOND_SHARD)
    assert _mapped_shard(tenant_id) == SECOND_SHARD

    clear_tenant_placement(tenant_id)
    assert _mapped_shard(tenant_id) is None


def test_placement_overrides_a_stale_cached_resolution(
    placement_on_second_shard: dict[str, Any],
) -> None:
    """Resolving before placement must not pin the tenant to the default shard.

    `get_shard_for_tenant` caches the "no row, so default" answer for a full TTL, which
    would send the schema to the wrong database.
    """
    tenant_id = f"tenant_{uuid4()}"
    placement_on_second_shard["created"].append(tenant_id)

    assert shard_routing.get_shard_for_tenant(tenant_id) == DEFAULT_SHARD

    record_tenant_placement(tenant_id, SECOND_SHARD)
    create_schema_if_not_exists(tenant_id)

    assert _schema_exists(get_engine_for_shard(SECOND_SHARD), tenant_id)
    assert not _schema_exists(get_engine_for_shard(DEFAULT_SHARD), tenant_id)


def test_cleanup_drops_the_schema_from_the_tenants_own_shard(
    placement_on_second_shard: dict[str, Any],
) -> None:
    """The on-pod cleanup script previously dropped against the catalog database.

    For a tenant on another shard that reports `not_found` and silently leaves the
    schema in place, which matters because tenant cleanup is how database-1 is meant
    to shrink.
    """
    from scripts.tenant_cleanup.on_pod_scripts.cleanup_tenant_schema import (
        drop_data_plane_schema,
    )

    tenant_id = f"tenant_{uuid4()}"
    placement_on_second_shard["created"].append(tenant_id)

    record_tenant_placement(tenant_id, SECOND_SHARD)
    create_schema_if_not_exists(tenant_id)
    assert _schema_exists(get_engine_for_shard(SECOND_SHARD), tenant_id)

    result = drop_data_plane_schema(tenant_id)

    assert result["status"] == "success"
    assert not _schema_exists(get_engine_for_shard(SECOND_SHARD), tenant_id)
    assert _mapped_shard(tenant_id) is None
