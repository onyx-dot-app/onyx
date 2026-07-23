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
from sqlalchemy.exc import OperationalError, ProgrammingError

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


def _set_tenant_shard(tenant_id: str, shard_name: str) -> None:
    """Map a tenant to a shard, as a migrator's flip would."""
    with get_catalog_engine().connect() as conn:
        conn.execute(
            text(
                "INSERT INTO public.tenant_shard (tenant_id, shard_name) "
                "VALUES (:t, :s) ON CONFLICT (tenant_id) DO UPDATE SET shard_name = :s"
            ),
            {"t": tenant_id, "s": shard_name},
        )
        conn.commit()


def _clear_tenant_shard(tenant_id: str) -> None:
    with get_catalog_engine().connect() as conn:
        conn.execute(
            text("DELETE FROM public.tenant_shard WHERE tenant_id = :t"),
            {"t": tenant_id},
        )
        conn.commit()


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

    _set_tenant_shard(tenant_b, SECOND_SHARD)
    invalidate_shard_cache()

    yield {"tenant_a": tenant_a, "tenant_b": tenant_b, "second_db": second_database}

    for tenant_id, engine in (
        (tenant_a, get_engine_for_tenant(tenant_a)),
        (tenant_b, shard_registry.get_engine_for_shard(SECOND_SHARD)),
    ):
        with engine.connect() as conn:
            conn.execute(text(f'DROP SCHEMA IF EXISTS "{tenant_id}" CASCADE'))
            conn.commit()
    _clear_tenant_shard(tenant_b)
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

    _set_tenant_shard(tenant_a, SECOND_SHARD)

    # Still cached from the assertion above.
    assert get_shard_for_tenant(tenant_a) == "default"

    invalidate_shard_cache(tenant_a)
    assert get_shard_for_tenant(tenant_a) == SECOND_SHARD

    _clear_tenant_shard(tenant_a)
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


def test_unknown_shard_in_map_raises_rather_than_falling_back(
    two_shards: dict[str, Any],
) -> None:
    """A dangling mapping must fail closed, not silently resolve to default.

    Falling back here is worse than erroring: the tenant named a shard, so it has
    plausibly been migrated, and routing it to `default` would put its writes on the
    database it was moved off.
    """
    tenant_a = two_shards["tenant_a"]
    _set_tenant_shard(tenant_a, "shard-that-does-not-exist")
    invalidate_shard_cache(tenant_a)

    try:
        with pytest.raises(ShardConfigurationError):
            get_shard_for_tenant(tenant_a)
    finally:
        _clear_tenant_shard(tenant_a)
        invalidate_shard_cache(tenant_a)


def test_requesting_an_unconfigured_shard_raises(two_shards: dict[str, Any]) -> None:  # noqa: ARG001
    with pytest.raises(ShardConfigurationError):
        shard_registry.get_engine_for_shard("no-such-shard")


def test_pool_budget_is_divided_not_multiplied(two_shards: dict[str, Any]) -> None:  # noqa: ARG001
    """Adding a shard must not multiply the connection load on the database."""
    assert len(get_shard_specs()) == 2
    assert shard_registry.is_sharded()

    pool_size, max_overflow = shard_registry.divide_pool_budget(20, 10)
    assert (pool_size, max_overflow) == (10, 5)

    # An explicit zero-overflow budget (celery beat) must survive the division.
    assert shard_registry.divide_pool_budget(20, 0) == (10, 0)


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

    _set_tenant_shard(tenant_a, SECOND_SHARD)

    bump_shard_map_version()

    assert get_shard_for_tenant(tenant_a) == SECOND_SHARD

    _clear_tenant_shard(tenant_a)
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


def _schema_exists(engine: Engine, schema: str) -> bool:
    with engine.connect() as conn:
        return (
            conn.execute(
                text(
                    "SELECT 1 FROM information_schema.schemata WHERE schema_name = :s"
                ),
                {"s": schema},
            ).scalar()
            is not None
        )


def test_schema_creation_follows_the_shard_map(
    two_shards: dict[str, Any],  # noqa: ARG001
) -> None:
    """DDL must land in the same database the tenant's data sessions route to.

    Without this, `setup_tenant` creates the schema on the default shard and then
    seeds it through a shard-routed session — writing into a schema that does not
    exist on that database.
    """
    from ee.onyx.server.tenants.schema_management import create_schema_if_not_exists

    tenant_id = f"tenant_{uuid4()}"
    _set_tenant_shard(tenant_id, SECOND_SHARD)
    invalidate_shard_cache()

    default_engine = shard_registry.get_engine_for_shard("default")
    second_engine = shard_registry.get_engine_for_shard(SECOND_SHARD)
    try:
        create_schema_if_not_exists(tenant_id)

        assert _schema_exists(second_engine, tenant_id)
        assert not _schema_exists(default_engine, tenant_id)
    finally:
        with second_engine.connect() as conn:
            conn.execute(text(f'DROP SCHEMA IF EXISTS "{tenant_id}" CASCADE'))
            conn.commit()
        _clear_tenant_shard(tenant_id)


def test_drop_schema_follows_the_shard_map(two_shards: dict[str, Any]) -> None:
    """Dropping must target the shard that actually holds the schema.

    A default-pinned drop would silently no-op, leaving the real schema behind.
    """
    from ee.onyx.server.tenants.schema_management import drop_schema

    tenant_b = two_shards["tenant_b"]
    second_engine = shard_registry.get_engine_for_shard(SECOND_SHARD)
    assert _schema_exists(second_engine, tenant_b)

    drop_schema(tenant_b)

    assert not _schema_exists(second_engine, tenant_b)


def test_alembic_url_targets_the_tenants_shard(two_shards: dict[str, Any]) -> None:
    """The migration runner must be pointed at the tenant's database.

    Checked at the URL level because running the full tree per test is far too slow.
    """
    from ee.onyx.server.tenants.schema_management import _tenant_connection_string

    url_a = _tenant_connection_string(two_shards["tenant_a"])
    url_b = _tenant_connection_string(two_shards["tenant_b"])

    assert url_a.endswith(f"/{POSTGRES_DB}")
    assert url_b.endswith(f"/{two_shards['second_db']}")
    # Byte-identical to the historical call for the default shard.
    assert url_a == build_connection_string()


def test_catalog_failure_raises_instead_of_routing_to_default(
    two_shards: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unreachable catalog must not be read as "tenant is on the default shard".

    The two are indistinguishable at the return-value level, which is what made the
    original `except -> None -> default` path dangerous: a transient catalog blip
    would pin a migrated tenant to its old database for a full TTL.
    """
    tenant_b = two_shards["tenant_b"]
    invalidate_shard_cache()

    real_get_catalog_engine = shard_routing.get_catalog_engine
    failing = {"on": True}

    def _maybe_explode(*args: Any, **kwargs: Any) -> Any:
        if failing["on"]:
            raise OperationalError("SELECT 1", {}, Exception("catalog unreachable"))
        return real_get_catalog_engine(*args, **kwargs)

    monkeypatch.setattr(shard_routing, "get_catalog_engine", _maybe_explode)

    try:
        with pytest.raises(shard_routing.ShardLookupError):
            get_shard_for_tenant(tenant_b)
    finally:
        # Restore before fixture teardown, which itself resolves shards.
        failing["on"] = False


def test_catalog_failure_does_not_poison_the_cache(
    two_shards: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """After a failed lookup, recovery must produce the correct shard immediately.

    The old code cached the default-shard guess, so a momentary catalog blip pinned
    a migrated tenant to the wrong database for a full TTL even once it recovered.
    """
    tenant_b = two_shards["tenant_b"]
    invalidate_shard_cache()

    real_get_catalog_engine = shard_routing.get_catalog_engine
    failing = {"on": True}

    def _maybe_explode(*args: Any, **kwargs: Any) -> Any:
        if failing["on"]:
            raise OperationalError("SELECT 1", {}, Exception("catalog unreachable"))
        return real_get_catalog_engine(*args, **kwargs)

    monkeypatch.setattr(shard_routing, "get_catalog_engine", _maybe_explode)

    with pytest.raises(shard_routing.ShardLookupError):
        get_shard_for_tenant(tenant_b)

    # Catalog recovers; no invalidation call in between.
    failing["on"] = False
    assert get_shard_for_tenant(tenant_b) == SECOND_SHARD


def test_missing_catalog_table_still_falls_back_to_default(
    two_shards: dict[str, Any],  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A not-yet-migrated deployment is the one safe case for the default fallback.

    If `tenant_shard` does not exist, no tenant can be mapped anywhere, so `default`
    is not a guess.
    """
    tenant_id = f"tenant_{uuid4()}"
    invalidate_shard_cache()

    def _undefined_table() -> Any:
        raise _make_undefined_table_error()

    monkeypatch.setattr(shard_routing, "get_catalog_engine", _undefined_table)
    assert get_shard_for_tenant(tenant_id) == "default"


def _make_undefined_table_error() -> ProgrammingError:
    orig = Exception('relation "public.tenant_shard" does not exist')
    orig.pgcode = "42P01"  # ty: ignore[unresolved-attribute]
    return ProgrammingError("SELECT 1", {}, orig)


def test_stale_lookup_cannot_repopulate_cache_after_invalidation(
    two_shards: dict[str, Any],
) -> None:
    """A read in flight during a flip must not install its stale answer.

    Without generation tracking the racing reader wins and the tenant stays routable
    to its old database for a full TTL after the migrator unfroze it.
    """
    tenant_b = two_shards["tenant_b"]
    invalidate_shard_cache()

    generation = shard_routing._ShardCache.generation()
    # Simulate a flip landing while a lookup was in flight.
    invalidate_shard_cache()
    shard_routing._ShardCache.put(tenant_b, "default", generation)

    assert shard_routing._ShardCache.get(tenant_b) is None
    assert get_shard_for_tenant(tenant_b) == SECOND_SHARD


def test_freeze_window_outlasts_the_ttl(two_shards: dict[str, Any]) -> None:  # noqa: ARG001
    """A Redis-partitioned pod only recovers via the TTL, so the freeze must cover it.

    `bump_shard_map_version()` proves the *migrator* reached Redis, not that every
    serving process did.
    """
    assert shard_map_propagation_seconds() > float(
        shard_version.ONYX_DB_SHARD_MAP_TTL_SECONDS
    )


def test_default_shard_cannot_be_redefined(
    second_database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Overriding the default shard would split sessions from migrations."""
    monkeypatch.setattr(
        shard_registry,
        "ONYX_DB_SHARDS_JSON",
        f'{{"default": {{"db": "{second_database}"}}}}',
    )
    monkeypatch.setattr(shard_registry, "ONYX_DB_DEFAULT_SHARD", "default")
    shard_registry.reset_shard_specs()

    with pytest.raises(ShardConfigurationError):
        get_shard_specs()

    shard_registry.reset_shard_specs()


def test_shard_password_is_url_encoded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A password with URL-reserved characters must not corrupt the DSN.

    POSTGRES_PASSWORD is percent-encoded at config load, so an explicit shard
    override has to be treated the same way.
    """
    monkeypatch.setattr(
        shard_registry,
        "ONYX_DB_SHARDS_JSON",
        '{"pw-shard": {"password": "p@ss:w/rd"}}',
    )
    monkeypatch.setattr(shard_registry, "ONYX_DB_DEFAULT_SHARD", "default")
    monkeypatch.setattr(shard_registry, "ONYX_DB_CATALOG_SHARD", "default")
    shard_registry.reset_shard_specs()

    spec = shard_registry.get_shard_spec("pw-shard")
    assert spec.password == "p%40ss%3Aw%2Frd"
    assert "@ss" not in spec.password

    shard_registry.reset_shard_specs()


def test_catalog_shard_is_validated_without_shard_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Naming a catalog shard that does not exist must fail at startup, not at request time."""
    monkeypatch.setattr(shard_registry, "ONYX_DB_SHARDS_JSON", "")
    monkeypatch.setattr(shard_registry, "ONYX_DB_DEFAULT_SHARD", "default")
    monkeypatch.setattr(shard_registry, "ONYX_DB_CATALOG_SHARD", "nonexistent-catalog")
    shard_registry.reset_shard_specs()

    with pytest.raises(ShardConfigurationError):
        get_shard_specs()

    shard_registry.reset_shard_specs()


class _CapturedAlembicURL(Exception):
    """Sentinel to abort a migration run once the target URL is known."""

    def __init__(self, url: str) -> None:
        super().__init__(url)
        self.url = url


def test_run_alembic_migrations_targets_the_tenants_shard(
    two_shards: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The migration runner must actually connect to the tenant's database.

    Asserting on the generated URL alone is not enough: `alembic/env.py` builds its
    own engine, and previously ignored the URL the caller configured, so migrations
    silently ran against the default database while the URL looked correct. This
    intercepts `create_async_engine` inside the real
    `run_alembic_migrations` -> alembic -> `env.py` path and aborts once the target
    is known, so the full 400-migration tree never has to run.
    """
    import sqlalchemy.ext.asyncio as sa_asyncio

    from ee.onyx.server.tenants.schema_management import run_alembic_migrations

    def _capture(url: Any, *_: Any, **__: Any) -> Any:
        raise _CapturedAlembicURL(str(url))

    # env.py does `from sqlalchemy.ext.asyncio import create_async_engine` at import
    # time, and alembic re-executes env.py per run, so patching the source module
    # attribute is picked up by the real code path.
    monkeypatch.setattr(sa_asyncio, "create_async_engine", _capture)

    for tenant_key, expected_db in (
        ("tenant_a", POSTGRES_DB),
        ("tenant_b", two_shards["second_db"]),
    ):
        captured: str | None = None
        try:
            run_alembic_migrations(two_shards[tenant_key])
        except _CapturedAlembicURL as e:
            captured = e.url
        except Exception as e:  # pragma: no cover - surfaces wiring breakage
            cause = e
            while cause is not None:
                if isinstance(cause, _CapturedAlembicURL):
                    captured = cause.url
                    break
                cause = cause.__cause__ or cause.__context__

        assert captured is not None, f"never reached engine creation for {tenant_key}"
        assert captured.endswith(f"/{expected_db}"), (
            f"{tenant_key} migrations target {captured}, expected database {expected_db}"
        )


def test_sqlalchemy_url_option_is_still_ignored_by_env_py(
    two_shards: dict[str, Any],  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Setting `sqlalchemy.url` must not redirect a migration run.

    The integration-test reset helpers set that option to a *sync* driver URL and
    rely on env.py ignoring it. Honoring it there routes a psycopg2 URL into
    `create_async_engine`, which fails with "the asyncio extension requires an async
    driver" — so shard targeting has to travel on its own channel.
    """
    import os
    from types import SimpleNamespace

    import sqlalchemy.ext.asyncio as sa_asyncio
    from alembic import command
    from alembic.config import Config

    def _capture(url: Any, *_: Any, **__: Any) -> Any:
        raise _CapturedAlembicURL(str(url))

    monkeypatch.setattr(sa_asyncio, "create_async_engine", _capture)

    root_dir = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..")
    )
    alembic_cfg = Config(os.path.join(root_dir, "alembic.ini"))
    alembic_cfg.set_main_option("script_location", os.path.join(root_dir, "alembic"))
    alembic_cfg.attributes["configure_logger"] = False
    alembic_cfg.cmd_opts = SimpleNamespace()  # ty: ignore[invalid-assignment]
    alembic_cfg.cmd_opts.x = ["schemas=public"]  # ty: ignore[invalid-assignment]

    sync_url = build_connection_string(db_api=SYNC_DB_API)
    alembic_cfg.set_main_option("sqlalchemy.url", sync_url)

    captured: str | None = None
    try:
        command.upgrade(alembic_cfg, "head")
    except _CapturedAlembicURL as e:
        captured = e.url
    except Exception as e:
        cause: BaseException | None = e
        while cause is not None:
            if isinstance(cause, _CapturedAlembicURL):
                captured = cause.url
                break
            cause = cause.__cause__ or cause.__context__

    assert captured is not None, "never reached engine creation"
    assert "psycopg2" not in captured, (
        f"env.py used the caller's sync URL ({captured}); async engine creation "
        "would fail"
    )


@pytest.mark.asyncio
async def test_async_sessions_reach_different_physical_databases(
    two_shards: dict[str, Any],
) -> None:
    """Async sessions must route by shard, not just by schema.

    The async path was previously pinned to the default engine, so authentication,
    PAT, SAML, and token-refresh work for a migrated tenant would read a stale
    schema on the old database and write to an abandoned copy.
    """
    from onyx.db.engine.async_sql_engine import (
        get_async_session_context_manager,
        reset_sqlalchemy_async_engine,
    )

    try:
        async with get_async_session_context_manager(two_shards["tenant_a"]) as session:
            db_a = str(
                (await session.execute(text("SELECT current_database()"))).scalar()
            )
        async with get_async_session_context_manager(two_shards["tenant_b"]) as session:
            db_b = str(
                (await session.execute(text("SELECT current_database()"))).scalar()
            )

        assert db_a == POSTGRES_DB
        assert db_b == two_shards["second_db"]
        assert db_a != db_b
    finally:
        # Async pools are bound to this test's event loop; leaving them open leaks
        # connections and makes a later test fail depending on selection order.
        await reset_sqlalchemy_async_engine()


@pytest.mark.asyncio
async def test_async_engine_is_reused_per_shard(two_shards: dict[str, Any]) -> None:
    """One engine per shard, not one per call — pools must not multiply."""
    from onyx.db.engine.async_sql_engine import (
        get_async_engine_for_tenant,
        reset_sqlalchemy_async_engine,
    )

    try:
        first = await get_async_engine_for_tenant(two_shards["tenant_b"])
        second = await get_async_engine_for_tenant(two_shards["tenant_b"])
        assert first is second
        assert first is not await get_async_engine_for_tenant(two_shards["tenant_a"])
    finally:
        await reset_sqlalchemy_async_engine()
