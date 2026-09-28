"""Tenant provisioning migrations honor POSTGRES_MIGRATION_HOST, so a deployment
whose app traffic goes through a transaction-pooling proxy can still run
alembic against the database directly."""

from unittest.mock import patch

from ee.onyx.server.tenants import schema_management
from onyx.db.engine.shard_registry import ONYX_DB_DEFAULT_SHARD, ShardSpec

_DEFAULT: ShardSpec = ShardSpec(
    name=ONYX_DB_DEFAULT_SHARD,
    host="pgbouncer-service",
    port="5432",
    db="postgres",
    user="postgres",
    password="secret",
)


def test_migration_host_overrides_the_default_shard() -> None:
    with (
        patch.object(
            schema_management, "get_shard_for_tenant", return_value=_DEFAULT.name
        ),
        patch.object(schema_management, "get_shard_spec", return_value=_DEFAULT),
        patch.object(
            schema_management, "POSTGRES_MIGRATION_HOST", "writer.rds.internal"
        ),
        patch.object(schema_management, "POSTGRES_MIGRATION_PORT", "5433"),
    ):
        url: str = schema_management._tenant_connection_string("tenant_x")
    assert "@writer.rds.internal:5433/postgres" in url


def test_without_override_the_shard_host_is_used() -> None:
    with (
        patch.object(
            schema_management, "get_shard_for_tenant", return_value=_DEFAULT.name
        ),
        patch.object(schema_management, "get_shard_spec", return_value=_DEFAULT),
        patch.object(schema_management, "POSTGRES_MIGRATION_HOST", None),
    ):
        url: str = schema_management._tenant_connection_string("tenant_x")
    assert "@pgbouncer-service:5432/postgres" in url
