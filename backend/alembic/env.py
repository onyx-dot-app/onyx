from onyx.db.engine.iam_auth import make_provide_iam_token_async
from onyx.db.engine.pg_ssl import create_pg_ssl_context
from onyx.configs.app_configs import USE_IAM_AUTH
from onyx.configs.app_configs import POSTGRES_HOST
from onyx.configs.app_configs import POSTGRES_PORT
from onyx.configs.app_configs import POSTGRES_USER
from onyx.db.engine.shard_registry import ALEMBIC_TARGET_URL_ATTRIBUTE
from onyx.db.engine.shard_registry import get_shard_spec
from onyx.db.engine.shard_registry import validate_shard_name
from onyx.db.engine.shard_registry import is_sharded
from onyx.db.engine.sql_engine import build_connection_string
from onyx.db.engine.tenant_utils import get_tenant_ids_by_shard
from sqlalchemy import event
from sqlalchemy import pool
from sqlalchemy import text
from sqlalchemy.engine.url import make_url
from sqlalchemy.engine.base import Connection
import os
from itertools import chain
import asyncio
import logging
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.ext.asyncio import create_async_engine
from onyx.configs.constants import SSL_CERT_FILE
from shared_configs.configs import (
    MULTI_TENANT,
    POSTGRES_DEFAULT_SCHEMA,
    TENANT_ID_PREFIX,
)
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR
from onyx.db.models import Base
from celery.backends.database.session import (
    ResultModelBase,  # ty: ignore[unresolved-import]
)
from onyx.db.engine.sql_engine import SqlEngine
from onyx.utils.variable_functionality import set_is_ee_based_on_env_variable

# Match the app processes' edition so migrations that use versioned
# implementations (e.g. encrypt_string_to_bytes) resolve the EE variants.
set_is_ee_based_on_env_variable()

# Make sure in alembic.ini [logger_root] level=INFO is set or most logging will be
# hidden! (defaults to level=WARN)

# Alembic Config object
config = context.config

if config.config_file_name is not None and config.attributes.get(
    "configure_logger", True
):
    # disable_existing_loggers=False prevents breaking pytest's caplog fixture
    # See: https://pytest-alembic.readthedocs.io/en/latest/setup.html#caplog-issues
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = [Base.metadata, ResultModelBase.metadata]

logger = logging.getLogger(__name__)


def connection_url(shard_name: str | None = None) -> str:
    """Database URL for this migration run.

    In precedence order: a caller that has already decided which database to target
    (per-tenant migrations, via `ALEMBIC_TARGET_URL_ATTRIBUTE`), then an explicit
    shard, then the process-wide POSTGRES_* settings.
    """
    configured = config.attributes.get(ALEMBIC_TARGET_URL_ATTRIBUTE)
    if configured:
        return configured

    if shard_name is None:
        return build_connection_string()

    spec = get_shard_spec(shard_name)
    return build_connection_string(
        user=spec.user,
        password=spec.password,
        host=spec.host,
        port=spec.port,
        db=spec.db,
    )


# Fail at import rather than on the first connection. The context itself is built by
# `create_pg_ssl_context`, which both the engine and the IAM listener use.
if USE_IAM_AUTH and not os.path.exists(SSL_CERT_FILE):
    raise FileNotFoundError(f"Expected {SSL_CERT_FILE} when USE_IAM_AUTH is true.")


def filter_tenants_by_range(
    tenant_ids: list[str], start_range: int | None = None, end_range: int | None = None
) -> list[str]:
    """
    Filter tenant IDs by alphabetical position range.

    Args:
        tenant_ids: List of tenant IDs to filter
        start_range: Starting position in alphabetically sorted list (1-based, inclusive)
        end_range: Ending position in alphabetically sorted list (1-based, inclusive)

    Returns:
        Filtered list of tenant IDs in their original order
    """
    if start_range is None and end_range is None:
        return tenant_ids

    # Separate tenant IDs from non-tenant schemas
    tenant_schemas = [tid for tid in tenant_ids if tid.startswith(TENANT_ID_PREFIX)]
    non_tenant_schemas = [
        tid for tid in tenant_ids if not tid.startswith(TENANT_ID_PREFIX)
    ]

    # Sort tenant schemas alphabetically.
    # NOTE: can cause missed schemas if a schema is created in between workers
    # fetching of all tenant IDs. We accept this risk for now. Just re-running
    # the migration will fix the issue.
    sorted_tenant_schemas = sorted(tenant_schemas)

    # Apply range filtering (0-based indexing)
    start_idx = start_range if start_range is not None else 0
    end_idx = end_range if end_range is not None else len(sorted_tenant_schemas)

    # Ensure indices are within bounds
    start_idx = max(0, start_idx)
    end_idx = min(len(sorted_tenant_schemas), end_idx)

    # Get the filtered tenant schemas
    filtered_tenant_schemas = sorted_tenant_schemas[start_idx:end_idx]

    # Combine with non-tenant schemas and preserve original order
    filtered_tenants = [
        tenant_id
        for tenant_id in tenant_ids
        if tenant_id in filtered_tenant_schemas or tenant_id in non_tenant_schemas
    ]

    return filtered_tenants


def get_schema_options() -> tuple[
    bool, bool, bool, int | None, int | None, list[str] | None, str | None
]:
    x_args_raw = context.get_x_argument()
    x_args = {}
    for arg in x_args_raw:
        if "=" in arg:
            key, value = arg.split("=", 1)
            x_args[key.strip()] = value.strip()
        else:
            raise ValueError(f"Invalid argument: {arg}")

    create_schema = x_args.get("create_schema", "true").lower() == "true"
    upgrade_all_tenants = x_args.get("upgrade_all_tenants", "false").lower() == "true"

    # continue on error with individual tenant
    # only applies to online migrations
    continue_on_error = x_args.get("continue", "false").lower() == "true"

    # Tenant range filtering
    tenant_range_start = None
    tenant_range_end = None

    if "tenant_range_start" in x_args:
        try:
            tenant_range_start = int(x_args["tenant_range_start"])
        except ValueError:
            raise ValueError(
                f"Invalid tenant_range_start value: {x_args['tenant_range_start']}. Must be an integer."
            )

    if "tenant_range_end" in x_args:
        try:
            tenant_range_end = int(x_args["tenant_range_end"])
        except ValueError:
            raise ValueError(
                f"Invalid tenant_range_end value: {x_args['tenant_range_end']}. Must be an integer."
            )

    # Validate range
    if tenant_range_start is not None and tenant_range_end is not None:
        if tenant_range_start > tenant_range_end:
            raise ValueError(
                f"tenant_range_start ({tenant_range_start}) cannot be greater than tenant_range_end ({tenant_range_end})"
            )

    # Specific schema names filtering (replaces both schema_name and the old tenant_ids approach)
    schemas = None
    if "schemas" in x_args:
        schema_names_str = x_args["schemas"].strip()
        if schema_names_str:
            # Split by comma and strip whitespace
            schemas = [
                name.strip() for name in schema_names_str.split(",") if name.strip()
            ]
            if schemas:
                logger.info("Specific schema names specified: %s", schemas)

    # Validate that only one method is used at a time
    range_filtering = tenant_range_start is not None or tenant_range_end is not None
    specific_filtering = schemas is not None and len(schemas) > 0

    if range_filtering and specific_filtering:
        raise ValueError(
            "Cannot use both tenant range filtering (tenant_range_start/tenant_range_end) "
            "and specific schema filtering (schemas) at the same time. "
            "Please use only one filtering method."
        )

    if upgrade_all_tenants and specific_filtering:
        raise ValueError(
            "Cannot use both upgrade_all_tenants=true and schemas at the same time. "
            "Use either upgrade_all_tenants=true for all tenants, or schemas for specific schemas."
        )

    # If any filtering parameters are specified, we're not doing the default single schema migration
    if range_filtering:
        upgrade_all_tenants = True

    # Validate multi-tenant requirements
    if MULTI_TENANT and not upgrade_all_tenants and not specific_filtering:
        raise ValueError(
            "In multi-tenant mode, you must specify either upgrade_all_tenants=true "
            "or provide schemas. Cannot run default migration."
        )

    # Pins the run to one physical database. Omitted means the default shard for a
    # named-schema run, and every shard for upgrade_all_tenants.
    shard = x_args.get("shard") or None
    if shard is not None:
        # Fails here rather than after connecting to the wrong database.
        validate_shard_name(shard)

    return (
        create_schema,
        upgrade_all_tenants,
        continue_on_error,
        tenant_range_start,
        tenant_range_end,
        schemas,
        shard,
    )


def do_run_migrations(
    connection: Connection, schema_name: str, create_schema: bool
) -> None:
    if create_schema:
        connection.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema_name}"'))

    connection.execute(text(f'SET search_path TO "{schema_name}"'))

    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        version_table_schema=schema_name,
        include_schemas=True,
        compare_type=True,
        compare_server_default=True,
        script_location=config.get_main_option("script_location"),
    )

    # Migrations may call into code that reads CURRENT_TENANT_ID_CONTEXTVAR
    # (e.g. get_kv_store().load() in 4ee1287bd26a). search_path alone is not
    # enough — set the Python contextvar to match.
    token = CURRENT_TENANT_ID_CONTEXTVAR.set(schema_name)
    try:
        with context.begin_transaction():
            context.run_migrations()
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(token)


def create_migration_engine(target_url: str) -> AsyncEngine:
    """Async engine for one database, with IAM bound to that database.

    An RDS IAM token is only valid for the host/port/user it was minted for, so the
    listener is built from the URL this engine connects to rather than from the
    process-wide POSTGRES_* settings.
    """
    engine = create_async_engine(
        target_url,
        poolclass=pool.NullPool,
        connect_args={"ssl": create_pg_ssl_context()},
    )
    if USE_IAM_AUTH:
        url = make_url(target_url)
        event.listen(
            engine.sync_engine,
            "do_connect",
            make_provide_iam_token_async(
                url.host or POSTGRES_HOST,
                str(url.port) if url.port else POSTGRES_PORT,
                url.username or POSTGRES_USER,
            ),
        )
    return engine


async def _migrate_schemas(
    engine: AsyncEngine,
    schemas: list[str],
    create_schema: bool,
    continue_on_error: bool,
    label: str,
) -> None:
    """Run migrations for a list of schemas against one database."""
    num_schemas = len(schemas)
    for i_schema, schema in enumerate(schemas, start=1):
        logger.info(
            "Migrating schema: index=%s num_%s=%s schema=%s",
            i_schema,
            label,
            num_schemas,
            schema,
        )
        try:
            async with engine.connect() as connection:
                await connection.run_sync(
                    do_run_migrations,
                    schema_name=schema,
                    create_schema=create_schema,
                )
                await connection.commit()
        except Exception as e:
            logger.error("Error migrating schema %s: %s", schema, e)
            if not continue_on_error:
                logger.error("--continue=true is not set, raising exception!")
                raise

            logger.warning("--continue=true is set, continuing to next schema.")


def _tenants_to_migrate(
    shard: str | None,
    tenant_range_start: int | None,
    tenant_range_end: int | None,
) -> dict[str, list[str]]:
    """Tenants needing migration, grouped by the shard that physically holds them."""
    tenants_by_shard = get_tenant_ids_by_shard()
    if shard is not None:
        tenants_by_shard = {shard: tenants_by_shard.get(shard, [])}

    if tenant_range_start is None and tenant_range_end is None:
        return tenants_by_shard

    # The range is positional over *all* tenants, so it has to be applied before
    # partitioning — filtering per shard would select the range N times over.
    all_tenants = sorted(set(chain.from_iterable(tenants_by_shard.values())))
    selected = set(
        filter_tenants_by_range(all_tenants, tenant_range_start, tenant_range_end)
    )
    logger.info(
        "Filtering tenants by range: start=%s, end=%s. Total tenants: %s, Filtered tenants: %s",
        tenant_range_start,
        tenant_range_end,
        len(all_tenants),
        len(selected),
    )
    return {
        shard_name: [t for t in tenants if t in selected]
        for shard_name, tenants in tenants_by_shard.items()
    }


async def run_async_migrations() -> None:
    (
        create_schema,
        upgrade_all_tenants,
        continue_on_error,
        tenant_range_start,
        tenant_range_end,
        schemas,
        shard,
    ) = get_schema_options()

    if not schemas and not MULTI_TENANT:
        schemas = [POSTGRES_DEFAULT_SCHEMA]

    # without init_engine, subsequent engine calls fail hard intentionally
    SqlEngine.init_engine(pool_size=20, max_overflow=5)

    if schemas:
        # Use specific schema names directly without fetching all tenants
        logger.info("Migrating specific schema names: %s", schemas)

        engine = create_migration_engine(connection_url(shard))
        try:
            await _migrate_schemas(
                engine, schemas, create_schema, continue_on_error, "schemas"
            )
        finally:
            await engine.dispose()

    elif upgrade_all_tenants:
        # One engine per shard: a tenant's schema only exists on the database holding
        # it, so migrating every tenant against a single engine would skip every
        # tenant that has been moved off it.
        for shard_name, tenants in sorted(
            _tenants_to_migrate(shard, tenant_range_start, tenant_range_end).items()
        ):
            if not tenants:
                continue
            logger.info("Migrating %s tenant(s) on shard %s", len(tenants), shard_name)
            engine = create_migration_engine(connection_url(shard_name))
            try:
                await _migrate_schemas(
                    engine, tenants, create_schema, continue_on_error, "tenants"
                )
            finally:
                await engine.dispose()

    else:
        # This should not happen in the new design since we require either
        # upgrade_all_tenants=true or schemas in multi-tenant mode
        # and for non-multi-tenant mode, we should use schemas with the default schema
        raise ValueError(
            "No migration target specified. Use either upgrade_all_tenants=true for all tenants or schemas for specific schemas."
        )


def run_migrations_offline() -> None:
    """
    NOTE(rkuo): This generates a sql script that can be used to migrate the database ...
    instead of migrating the db live via an open connection

    Not clear on when this would be used by us or if it even works.

    If it is offline, then why are there calls to the db engine?

    This doesn't really get used when we migrate in the cloud."""

    logger.info("run_migrations_offline starting.")

    # without init_engine, subsequent engine calls fail hard intentionally
    SqlEngine.init_engine(pool_size=20, max_overflow=5)

    (
        create_schema,
        upgrade_all_tenants,
        continue_on_error,
        tenant_range_start,
        tenant_range_end,
        schemas,
        shard,
    ) = get_schema_options()

    # An offline run emits one SQL script, which can only be applied to one database.
    if shard is None and is_sharded():
        raise ValueError(
            "Offline migrations must target a single database. Pass -x shard=<name>."
        )

    url = connection_url(shard)

    if schemas:
        # Use specific schema names directly without fetching all tenants
        logger.info("Migrating specific schema names: %s", schemas)

        for schema in schemas:
            logger.info("Migrating schema: %s", schema)
            context.configure(
                url=url,
                target_metadata=target_metadata,
                literal_binds=True,
                version_table_schema=schema,
                include_schemas=True,
                script_location=config.get_main_option("script_location"),
                dialect_opts={"paramstyle": "named"},
            )

            with context.begin_transaction():
                context.run_migrations()

    elif upgrade_all_tenants:
        # Single shard, enforced above, so this is the only group.
        filtered_tenant_schemas = [
            schema
            for schemas_on_shard in _tenants_to_migrate(
                shard, tenant_range_start, tenant_range_end
            ).values()
            for schema in schemas_on_shard
        ]

        for schema in filtered_tenant_schemas:
            logger.info("Migrating schema: %s", schema)
            context.configure(
                url=url,
                target_metadata=target_metadata,
                literal_binds=True,
                version_table_schema=schema,
                include_schemas=True,
                script_location=config.get_main_option("script_location"),
                dialect_opts={"paramstyle": "named"},
            )

            with context.begin_transaction():
                context.run_migrations()
    else:
        # This should not happen in the new design
        raise ValueError(
            "No migration target specified. Use either upgrade_all_tenants=true for all tenants or schemas for specific schemas."
        )


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    Supports pytest-alembic by checking for a pre-configured connection
    in context.config.attributes["connection"]. If present, uses that
    connection/engine directly instead of creating a new async engine.
    """
    # Check if pytest-alembic is providing a connection/engine
    connectable = context.config.attributes.get("connection", None)

    if connectable is not None:
        # pytest-alembic is providing an engine - use it directly
        logger.debug("run_migrations_online starting (pytest-alembic mode).")

        # For pytest-alembic, we use the default schema (public)
        schema_name = context.config.attributes.get(
            "schema_name", POSTGRES_DEFAULT_SCHEMA
        )

        # pytest-alembic passes an Engine, we need to get a connection from it
        with connectable.connect() as connection:
            # Set search path for the schema
            connection.execute(text(f'SET search_path TO "{schema_name}"'))

            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                version_table_schema=schema_name,
                include_schemas=True,
                compare_type=True,
                compare_server_default=True,
                script_location=config.get_main_option("script_location"),
            )

            with context.begin_transaction():
                context.run_migrations()

            # Commit the transaction to ensure changes are visible to next migration
            connection.commit()
    else:
        # Normal operation - use async migrations
        logger.info("run_migrations_online starting.")
        asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
