"""Tenant -> database routing seam, exercised against two real databases.

The point of these tests is the thing that cannot be checked with mocks: that a
session for tenant A physically talks to a different Postgres database than a
session for tenant B, and that neither can see the other's rows.

A second database is created on the same server as the test database. The seam
routes per-DSN, not per-host, so a second database is a faithful stand-in for a
second instance and keeps the tests self-contained.
"""

from collections.abc import Generator
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import Column, Integer, MetaData, String, Table, select, text
from sqlalchemy.engine import Engine

from onyx.configs.app_configs import POSTGRES_DB
from onyx.db.engine import shard_registry, shard_routing, shard_version
from onyx.db.engine.shard_registry import (
    ShardConfigurationError,
    get_catalog_engine,
    get_shard_specs,
)
from onyx.db.engine.shard_routing import (
    get_engine_for_tenant,
    get_shard_for_tenant,
    invalidate_shard_cache,
)
from onyx.db.engine.shard_version import (
    bump_shard_map_version,
    poll_shard_map_version,
    reset_shard_map_version_poller,
    shard_map_propagation_seconds,
)
from onyx.db.engine.sql_engine import (
    SYNC_DB_API,
    SqlEngine,
    build_connection_string,
    get_catalog_session,
    get_session_with_tenant,
)
from onyx.db.models import PublicBase

SECOND_SHARD = "shard-test-b"

# Standalone probe table. `schema=None` so `schema_translate_map` rewrites it to
# whichever tenant schema the session is bound to — the same mechanism the real
# per-tenant models rely on, without pulling in their dependencies.
_probe_metadata = MetaData()
SHARD_PROBE = Table(
    "shard_probe",
    _probe_metadata,
    Column("id", Integer, primary_key=True),
    Column("marker", String, nullable=False),
)


def _admin_engine() -> Engine:
    """Engine on the `postgres` maintenance DB, for CREATE/DROP DATABASE."""
    from sqlalchemy import create_engine

    return create_engine(
        build_connection_string(db_api=SYNC_DB_API, db="postgres"),
        isolation_level="AUTOCOMMIT",
    )


@pytest.fixture(scope="module")
def second_database() -> Generator[str, None, None]:
    """Create a throwaway second database for the duration of the module."""
    db_name = f"onyx_shard_test_{uuid4().hex[:8]}"
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
    """Configure two shards and a tenant schema on each.

    Yields the two tenant ids plus the shard each is expected to resolve to.
    """
    SqlEngine.init_engine(pool_size=5, max_overflow=2)

    shards_json = f'{{"{SECOND_SHARD}": {{"db": "{second_database}"}}}}'
    monkeypatch.setattr(shard_registry, "ONYX_DB_SHARDS_JSON", shards_json)
    monkeypatch.setattr(shard_registry, "ONYX_DB_DEFAULT_SHARD", "default")
    monkeypatch.setattr(shard_registry, "ONYX_DB_CATALOG_SHARD", "default")
    # Routing short-circuits to the default shard outside multi-tenant mode.
    monkeypatch.setattr(shard_routing, "MULTI_TENANT", True)
    monkeypatch.setattr(shard_routing, "ONYX_DB_SHARD_OVERRIDES_JSON", "")

    shard_registry.reset_shard_specs()
    shard_routing.reset_shard_overrides()
    invalidate_shard_cache()
    reset_shard_map_version_poller()

    tenant_a = f"tenant_{uuid4()}"
    tenant_b = f"tenant_{uuid4()}"

    # The catalog table normally arrives via the `schema_private` Alembic tree, which
    # the external-dependency-unit lane does not run. Create it on demand.
    catalog_engine = get_catalog_engine()
    PublicBase.metadata.create_all(catalog_engine, checkfirst=True)

    # Tenant A on the default shard, tenant B on the second one.
    for tenant_id, engine in (
        (tenant_a, get_engine_for_tenant(tenant_a)),
        (tenant_b, shard_registry.get_engine_for_shard(SECOND_SHARD)),
    ):
        with engine.connect() as conn:
            conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{tenant_id}"'))
            conn.commit()
        with conn_with_schema(engine, tenant_id) as conn:
            _probe_metadata.create_all(conn)
            conn.commit()

    with catalog_engine.connect() as conn:
        conn.execute(
            text(
                "INSERT INTO public.tenant_shard (tenant_id, shard_name) "
                "VALUES (:t, :s) ON CONFLICT (tenant_id) DO UPDATE SET shard_name = :s"
            ),
            {"t": tenant_b, "s": SECOND_SHARD},
        )
        conn.commit()
    invalidate_shard_cache()

    yield {"tenant_a": tenant_a, "tenant_b": tenant_b, "second_db": second_database}

    for tenant_id, engine in (
        (tenant_a, get_engine_for_tenant(tenant_a)),
        (tenant_b, shard_registry.get_engine_for_shard(SECOND_SHARD)),
    ):
        with engine.connect() as conn:
            conn.execute(text(f'DROP SCHEMA IF EXISTS "{tenant_id}" CASCADE'))
            conn.commit()
    with catalog_engine.connect() as conn:
        conn.execute(
            text("DELETE FROM public.tenant_shard WHERE tenant_id = :t"),
            {"t": tenant_b},
        )
        conn.commit()
    shard_registry.reset_shard_specs()
    invalidate_shard_cache()
    reset_shard_map_version_poller()


def conn_with_schema(engine: Engine, tenant_id: str) -> Any:
    return engine.connect().execution_options(schema_translate_map={None: tenant_id})


def _current_database(session: Any) -> str:
    return str(session.execute(text("SELECT current_database()")).scalar())


def test_tenants_resolve_to_their_configured_shards(two_shards: dict[str, Any]) -> None:
    assert get_shard_for_tenant(two_shards["tenant_a"]) == "default"
    assert get_shard_for_tenant(two_shards["tenant_b"]) == SECOND_SHARD


def test_unmapped_tenant_falls_back_to_default_shard(
    two_shards: dict[str, Any],  # noqa: ARG001
) -> None:
    """A tenant with no `tenant_shard` row must land on the default shard.

    This is what lets the mapping table stay empty until tenants are migrated.
    """
    assert get_shard_for_tenant(f"tenant_{uuid4()}") == "default"


def test_sessions_reach_different_physical_databases(
    two_shards: dict[str, Any],
) -> None:
    with get_session_with_tenant(tenant_id=two_shards["tenant_a"]) as session:
        db_a = _current_database(session)
    with get_session_with_tenant(tenant_id=two_shards["tenant_b"]) as session:
        db_b = _current_database(session)

    assert db_a == POSTGRES_DB
    assert db_b == two_shards["second_db"]
    assert db_a != db_b


def test_tenant_data_is_isolated_across_shards(two_shards: dict[str, Any]) -> None:
    """The core property: neither tenant can observe the other's rows."""
    for tenant_key, marker in (("tenant_a", "ON-SHARD-A"), ("tenant_b", "ON-SHARD-B")):
        with get_session_with_tenant(tenant_id=two_shards[tenant_key]) as session:
            session.execute(SHARD_PROBE.insert().values(marker=marker))
            session.commit()

    for tenant_key, expected in (
        ("tenant_a", "ON-SHARD-A"),
        ("tenant_b", "ON-SHARD-B"),
    ):
        with get_session_with_tenant(tenant_id=two_shards[tenant_key]) as session:
            markers = session.execute(select(SHARD_PROBE.c.marker)).scalars().all()
        # Reading only its own marker proves both the schema and the database are right.
        assert markers == [expected]


def test_catalog_session_ignores_the_current_tenant(two_shards: dict[str, Any]) -> None:
    """The catalog must be reachable from a tenant on any shard, at the same place."""
    with get_session_with_tenant(tenant_id=two_shards["tenant_b"]):
        with get_catalog_session() as catalog:
            assert _current_database(catalog) == POSTGRES_DB
            rows = (
                catalog.execute(
                    text(
                        "SELECT shard_name FROM public.tenant_shard WHERE tenant_id = :t"
                    ),
                    {"t": two_shards["tenant_b"]},
                )
                .scalars()
                .all()
            )
    assert rows == [SECOND_SHARD]


def test_flipping_the_map_reroutes_after_invalidation(
    two_shards: dict[str, Any],
) -> None:
    """A migrator flip plus cache invalidation must take effect immediately."""
    tenant_a = two_shards["tenant_a"]
    assert get_shard_for_tenant(tenant_a) == "default"

    with get_catalog_engine().connect() as conn:
        conn.execute(
            text(
                "INSERT INTO public.tenant_shard (tenant_id, shard_name) VALUES (:t, :s) "
                "ON CONFLICT (tenant_id) DO UPDATE SET shard_name = :s"
            ),
            {"t": tenant_a, "s": SECOND_SHARD},
        )
        conn.commit()

    # Still cached from the assertion above.
    assert get_shard_for_tenant(tenant_a) == "default"

    invalidate_shard_cache(tenant_a)
    assert get_shard_for_tenant(tenant_a) == SECOND_SHARD

    with get_catalog_engine().connect() as conn:
        conn.execute(
            text("DELETE FROM public.tenant_shard WHERE tenant_id = :t"),
            {"t": tenant_a},
        )
        conn.commit()
    invalidate_shard_cache(tenant_a)


def test_static_override_wins_over_the_catalog(
    two_shards: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The operator escape hatch must not require the catalog to agree."""
    tenant_a = two_shards["tenant_a"]
    monkeypatch.setattr(
        shard_routing,
        "ONYX_DB_SHARD_OVERRIDES_JSON",
        f'{{"{tenant_a}": "{SECOND_SHARD}"}}',
    )
    shard_routing.reset_shard_overrides()
    invalidate_shard_cache()

    assert get_shard_for_tenant(tenant_a) == SECOND_SHARD

    shard_routing.reset_shard_overrides()
    invalidate_shard_cache()


def test_unknown_shard_in_map_falls_back_rather_than_failing(
    two_shards: dict[str, Any],
) -> None:
    """A dangling mapping must not take request handling down."""
    tenant_a = two_shards["tenant_a"]
    with get_catalog_engine().connect() as conn:
        conn.execute(
            text(
                "INSERT INTO public.tenant_shard (tenant_id, shard_name) VALUES (:t, :s) "
                "ON CONFLICT (tenant_id) DO UPDATE SET shard_name = :s"
            ),
            {"t": tenant_a, "s": "shard-that-does-not-exist"},
        )
        conn.commit()
    invalidate_shard_cache(tenant_a)

    assert get_shard_for_tenant(tenant_a) == "default"

    with get_catalog_engine().connect() as conn:
        conn.execute(
            text("DELETE FROM public.tenant_shard WHERE tenant_id = :t"),
            {"t": tenant_a},
        )
        conn.commit()
    invalidate_shard_cache(tenant_a)


def test_requesting_an_unconfigured_shard_raises(two_shards: dict[str, Any]) -> None:  # noqa: ARG001
    with pytest.raises(ShardConfigurationError):
        shard_registry.get_engine_for_shard("no-such-shard")


def test_pool_budget_is_divided_not_multiplied(two_shards: dict[str, Any]) -> None:  # noqa: ARG001
    """Adding a shard must not multiply the connection load on the database."""
    assert len(get_shard_specs()) == 2
    assert shard_registry.shard_pool_divisor() == 2


def _poll_immediately(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove the poll throttle so a version bump is observed without waiting."""
    monkeypatch.setattr(shard_version, "ONYX_DB_SHARD_MAP_VERSION_POLL_SECONDS", 0)


def test_version_bump_invalidates_without_a_local_invalidate_call(
    two_shards: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The cross-process path: a flip published via Redis must be picked up here.

    Nothing in this test calls `invalidate_shard_cache`, which is what makes it a
    stand-in for a migrator running in some other pod.
    """
    tenant_a = two_shards["tenant_a"]
    _poll_immediately(monkeypatch)

    # Prime the cache with the pre-flip answer.
    assert get_shard_for_tenant(tenant_a) == "default"

    with get_catalog_engine().connect() as conn:
        conn.execute(
            text(
                "INSERT INTO public.tenant_shard (tenant_id, shard_name) VALUES (:t, :s) "
                "ON CONFLICT (tenant_id) DO UPDATE SET shard_name = :s"
            ),
            {"t": tenant_a, "s": SECOND_SHARD},
        )
        conn.commit()

    bump_shard_map_version()

    assert get_shard_for_tenant(tenant_a) == SECOND_SHARD

    with get_catalog_engine().connect() as conn:
        conn.execute(
            text("DELETE FROM public.tenant_shard WHERE tenant_id = :t"),
            {"t": tenant_a},
        )
        conn.commit()
    bump_shard_map_version()


def test_poll_is_throttled_between_intervals(
    two_shards: dict[str, Any],  # noqa: ARG001
) -> None:
    """Without the interval elapsing, a bump must not cost a Redis read per call."""
    reset_shard_map_version_poller()
    # First poll establishes the baseline and reports no change.
    assert poll_shard_map_version() is False
    bump_shard_map_version()
    # The default interval has not elapsed, so the bump is not visible yet. This is
    # the behavior `shard_map_propagation_seconds` exists to account for.
    assert poll_shard_map_version() is False


def test_redis_failure_leaves_cached_routing_intact(
    two_shards: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A Redis outage must degrade to the TTL, not flush or fail the hot path."""
    tenant_b = two_shards["tenant_b"]
    _poll_immediately(monkeypatch)
    assert get_shard_for_tenant(tenant_b) == SECOND_SHARD

    def _explode() -> str:
        raise ConnectionError("redis is down")

    monkeypatch.setattr(shard_version._VersionPoller, "_read_version", _explode)

    # No raise, no invalidation — and routing still resolves.
    assert poll_shard_map_version() is False
    assert get_shard_for_tenant(tenant_b) == SECOND_SHARD


def test_propagation_window_exceeds_the_poll_interval(
    two_shards: dict[str, Any],  # noqa: ARG001
) -> None:
    """The migrator's post-flip freeze must outlast the worst-case poll."""
    assert (
        shard_map_propagation_seconds()
        > shard_version.ONYX_DB_SHARD_MAP_VERSION_POLL_SECONDS
    )
