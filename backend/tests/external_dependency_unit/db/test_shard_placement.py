"""Placement of *new* tenants onto a configured shard, against two real databases.

The invariant is an ordering one — the mapping must be written before the schema is
created — so these assert on which database the schema physically lands in, not on
what a helper returned.
"""

import asyncio
from collections.abc import Generator
from typing import Any
from uuid import uuid4

import pytest
from scripts.tenant_cleanup.on_pod_scripts.cleanup_tenant_schema import (
    drop_data_plane_schema,
)
from sqlalchemy import text
from sqlalchemy.exc import OperationalError, ProgrammingError

from ee.onyx.server.tenants.schema_management import create_schema_if_not_exists
from onyx.db import tenant_shard as tenant_shard_module
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
from onyx.db.engine.sql_engine import SqlEngine
from onyx.db.models import PublicBase, TenantShard, UserTenantMapping
from onyx.db.tenant_shard import clear_tenant_placement, record_tenant_placement
from tests.external_dependency_unit.db.shard_test_utils import (
    DEFAULT_SHARD,
    create_schema,
    drop_schema,
    schema_exists,
)

SECOND_SHARD = "shard-test-b"


def _mapped_shard(tenant_id: str) -> str | None:
    with get_catalog_engine().connect() as conn:
        row = conn.execute(
            text("SELECT shard_name FROM public.tenant_shard WHERE tenant_id = :t"),
            {"t": tenant_id},
        ).first()
    return None if row is None else str(row[0])


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

    # These arrive via the `schema_private` Alembic tree, which this lane does not run.
    # `user_tenant_mapping` is here because the cleanup script deletes from it too.
    # Named explicitly so unrelated models can't break this suite.
    PublicBase.metadata.create_all(
        get_catalog_engine(),
        tables=[
            PublicBase.metadata.tables[f"public.{model.__tablename__}"]
            for model in (TenantShard, UserTenantMapping)
        ],
        checkfirst=True,
    )

    created: list[str] = []
    yield {"second_db": second_database, "created": created}

    for tenant_id in created:
        drop_schema(get_engine_for_shard(DEFAULT_SHARD), tenant_id)
        drop_schema(get_engine_for_shard(SECOND_SHARD), tenant_id)
        clear_tenant_placement(tenant_id)
    shard_registry.reset_shard_specs()
    invalidate_shard_cache()
    reset_shard_map_version_poller()


def test_new_tenants_target_the_configured_shard(
    placement_on_second_shard: dict[str, Any],  # noqa: ARG001
) -> None:
    assert get_shard_for_new_tenant() == SECOND_SHARD


def test_unknown_target_shard_fails_when_configuration_is_parsed(
    placement_on_second_shard: dict[str, Any],  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A typo should stop the process, not fail every signup at request time."""
    monkeypatch.setattr(shard_registry, "ONYX_DB_NEW_TENANT_SHARD", "no-such-shard")
    shard_registry.reset_shard_specs()

    with pytest.raises(ShardConfigurationError, match="ONYX_DB_NEW_TENANT_SHARD"):
        shard_registry.get_shard_specs()


def test_unknown_target_shard_raises_at_placement_rather_than_using_default(
    placement_on_second_shard: dict[str, Any],  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Second line of defence. The shard table is read before the name is changed, so
    the config is already cached — forcing the check inside `get_shard_for_new_tenant`
    to be what catches this rather than revalidation."""
    assert get_shard_for_new_tenant() == SECOND_SHARD

    monkeypatch.setattr(shard_registry, "ONYX_DB_NEW_TENANT_SHARD", "no-such-shard")

    with pytest.raises(ShardConfigurationError, match="ONYX_DB_NEW_TENANT_SHARD"):
        get_shard_for_new_tenant()


def test_recorded_placement_puts_the_schema_on_the_target_shard(
    placement_on_second_shard: dict[str, Any],
) -> None:
    """The unplaced tenant is the control: it proves the assertion discriminates,
    rather than the second shard simply receiving everything."""
    placed = f"tenant_{uuid4()}"
    unplaced = f"tenant_{uuid4()}"
    placement_on_second_shard["created"].extend([placed, unplaced])

    record_tenant_placement(placed, get_shard_for_new_tenant())
    create_schema_if_not_exists(placed)
    create_schema_if_not_exists(unplaced)

    assert schema_exists(get_engine_for_shard(SECOND_SHARD), placed)
    assert not schema_exists(get_engine_for_shard(DEFAULT_SHARD), placed)

    assert schema_exists(get_engine_for_shard(DEFAULT_SHARD), unplaced)
    assert not schema_exists(get_engine_for_shard(SECOND_SHARD), unplaced)


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
    """`get_shard_for_tenant` caches the "no row, so default" answer for a full TTL,
    which would otherwise send the schema to the wrong database."""
    tenant_id = f"tenant_{uuid4()}"
    placement_on_second_shard["created"].append(tenant_id)

    assert shard_routing.get_shard_for_tenant(tenant_id) == DEFAULT_SHARD

    record_tenant_placement(tenant_id, SECOND_SHARD)
    create_schema_if_not_exists(tenant_id)

    assert schema_exists(get_engine_for_shard(SECOND_SHARD), tenant_id)
    assert not schema_exists(get_engine_for_shard(DEFAULT_SHARD), tenant_id)


def test_cleanup_drops_the_schema_from_the_tenants_own_shard(
    placement_on_second_shard: dict[str, Any],
) -> None:
    """The script previously dropped against the catalog database, which for a sharded
    tenant reports `not_found` and silently leaves the schema in place."""
    tenant_id = f"tenant_{uuid4()}"
    placement_on_second_shard["created"].append(tenant_id)

    record_tenant_placement(tenant_id, SECOND_SHARD)
    create_schema_if_not_exists(tenant_id)
    assert schema_exists(get_engine_for_shard(SECOND_SHARD), tenant_id)

    result = drop_data_plane_schema(tenant_id)

    assert result["status"] == "success"
    assert not schema_exists(get_engine_for_shard(SECOND_SHARD), tenant_id)
    assert _mapped_shard(tenant_id) is None


def test_clearing_placement_tolerates_a_missing_catalog_table(
    placement_on_second_shard: dict[str, Any],  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Teardown runs on deployments that have not applied the catalog migration, and
    nothing can be mapped there anyway. Matches the read path's fallback."""

    def _undefined_table() -> Any:
        orig = Exception('relation "public.tenant_shard" does not exist')
        orig.pgcode = "42P01"  # ty: ignore[unresolved-attribute]
        raise ProgrammingError("DELETE", {}, orig)

    monkeypatch.setattr(tenant_shard_module, "get_catalog_engine", _undefined_table)
    clear_tenant_placement(f"tenant_{uuid4()}")


def test_clearing_placement_still_raises_on_other_errors(
    placement_on_second_shard: dict[str, Any],  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only a missing table is benign; anything else means the delete may not have
    happened and must not be swallowed."""

    def _boom() -> Any:
        raise OperationalError("DELETE", {}, Exception("connection refused"))

    monkeypatch.setattr(tenant_shard_module, "get_catalog_engine", _boom)
    with pytest.raises(OperationalError):
        clear_tenant_placement(f"tenant_{uuid4()}")


def test_cleanup_sweeps_every_shard_not_just_the_mapped_one(
    placement_on_second_shard: dict[str, Any],
) -> None:
    """Cleanup deletes the mapping, so trusting it would strand a copy on the shard the
    mapping did not name — and a tenant mid-migration exists on two shards at once."""
    tenant_id = f"tenant_{uuid4()}"
    placement_on_second_shard["created"].append(tenant_id)

    # Schema on both shards, with the mapping naming only one of them.
    for shard in (DEFAULT_SHARD, SECOND_SHARD):
        with get_engine_for_shard(shard).connect() as conn:
            conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{tenant_id}"'))
            conn.commit()
    record_tenant_placement(tenant_id, SECOND_SHARD)

    result = drop_data_plane_schema(tenant_id)

    assert result["status"] == "success"
    assert not schema_exists(get_engine_for_shard(SECOND_SHARD), tenant_id)
    assert not schema_exists(get_engine_for_shard(DEFAULT_SHARD), tenant_id)
    assert _mapped_shard(tenant_id) is None


def test_cleanup_rejects_a_malformed_tenant_id_before_touching_any_database(
    placement_on_second_shard: dict[str, Any],
) -> None:
    """A schema name cannot be bound as a parameter, so it is interpolated into DDL.
    The argument comes from a human on the command line, and the drop now sweeps every
    configured shard rather than one.

    Reaching the DDL also requires a schema of that exact name to exist, so this is
    defence in depth rather than an open hole — but the guard is what makes that true
    by design instead of by accident of statement ordering.
    """
    canary = f"tenant_{uuid4()}"
    placement_on_second_shard["created"].append(canary)
    create_schema(get_engine_for_shard(DEFAULT_SHARD), canary)

    result = drop_data_plane_schema(f'x" CASCADE; DROP SCHEMA "{canary}')

    assert result["status"] == "error"
    assert "Invalid tenant_id" in result["message"]
    assert schema_exists(get_engine_for_shard(DEFAULT_SHARD), canary)


def test_rollback_keeps_the_mapping_when_the_schema_drop_fails(
    placement_on_second_shard: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The mapping is the only route to the schema. Clearing it after a failed drop
    strands the schema on a shard nothing can resolve."""
    import ee.onyx.server.tenants.provisioning as provisioning

    tenant_id = f"tenant_{uuid4()}"
    placement_on_second_shard["created"].append(tenant_id)
    record_tenant_placement(tenant_id, SECOND_SHARD)
    create_schema_if_not_exists(tenant_id)

    def _boom(_tenant_id: str) -> None:
        raise RuntimeError("shard unreachable")

    monkeypatch.setattr(provisioning, "drop_schema", _boom)
    asyncio.run(provisioning.rollback_tenant_provisioning(tenant_id))

    assert _mapped_shard(tenant_id) == SECOND_SHARD


def test_cleanup_clears_catalog_rows_when_the_schema_is_already_gone(
    placement_on_second_shard: dict[str, Any],
) -> None:
    """Otherwise a retry after a partial run repeats `not_found` forever and the tenant
    stays in shared catalog state indefinitely."""
    tenant_id = f"tenant_{uuid4()}"
    placement_on_second_shard["created"].append(tenant_id)

    # Mapped, but the schema was never created — the state a half-finished cleanup or
    # a failed provision leaves behind.
    record_tenant_placement(tenant_id, SECOND_SHARD)
    assert _mapped_shard(tenant_id) == SECOND_SHARD

    result = drop_data_plane_schema(tenant_id)

    assert result["status"] == "not_found"
    assert _mapped_shard(tenant_id) is None
