from typing import Any, Literal
from onyx.db.engine.iam_auth import get_iam_auth_token
from onyx.configs.app_configs import USE_IAM_AUTH
from onyx.configs.app_configs import POSTGRES_HOST
from onyx.configs.app_configs import POSTGRES_PORT
from onyx.configs.app_configs import POSTGRES_USER
from onyx.configs.app_configs import AWS_REGION_NAME
from onyx.db.engine.sql_engine import build_connection_string
from onyx.db.engine.tenant_utils import get_all_tenant_ids
from sqlalchemy import event
from sqlalchemy import pool
from sqlalchemy import text
from sqlalchemy.engine.base import Connection
import os
import ssl
import asyncio
import logging
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.sql.schema import SchemaItem
from onyx.configs.constants import SSL_CERT_FILE
from shared_configs.configs import (
    MULTI_TENANT,
    POSTGRES_DEFAULT_SCHEMA,
    TENANT_ID_PREFIX,
)
from onyx.db.models import Base
from celery.backends.database.session import ResultModelBase  # type: ignore
from onyx.db.engine.sql_engine import SqlEngine

# Make sure in alembic.ini [logger_root] level=INFO is set or most logging will be
# hidden! (defaults to level=WARN)

# Alembic Config object
config = context.config

if config.config_file_name is not None and config.attributes.get(
    "configure_logger", True
):
    fileConfig(config.config_file_name)

target_metadata = [Base.metadata, ResultModelBase.metadata]

EXCLUDE_TABLES = {"kombu_queue", "kombu_message"}

logger = logging.getLogger(__name__)

ssl_context: ssl.SSLContext | None = None
if USE_IAM_AUTH:
    if not os.path.exists(SSL_CERT_FILE):
        raise FileNotFoundError(f"Expected {SSL_CERT_FILE} when USE_IAM_AUTH is true.")
    ssl_context = ssl.create_default_context(cafile=SSL_CERT_FILE)


def include_object(
    object: SchemaItem,
    name: str | None,
    type_: Literal[
        "schema",
        "table",
        "column",
        "index",
        "unique_constraint",
        "foreign_key_constraint",
    ],
    reflected: bool,
    compare_to: SchemaItem | None,
) -> bool:
    if type_ == "table" and name in EXCLUDE_TABLES:
        return False
    return True


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
    filtered_tenants = []
    for tenant_id in tenant_ids:
        if tenant_id in filtered_tenant_schemas or tenant_id in non_tenant_schemas:
            filtered_tenants.append(tenant_id)

    return filtered_tenants


def get_schema_options() -> (
    tuple[bool, bool, bool, int | None, int | None, list[str] | None]
):
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
                logger.info(f"Specific schema names specified: {schemas}")

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

    return (
        create_schema,
        upgrade_all_tenants,
        continue_on_error,
        tenant_range_start,
        tenant_range_end,
        schemas,
    )


def do_run_migrations(
    connection: Connection, schema_name: str, create_schema: bool
) -> None:
    if create_schema:
        connection.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema_name}"'))
        connection.execute(text("COMMIT"))

    connection.execute(text(f'SET search_path TO "{schema_name}"'))

    context.configure(
        connection=connection,
        target_metadata=target_metadata,  # type: ignore
        include_object=include_object,
        version_table_schema=schema_name,
        include_schemas=True,
        compare_type=True,
        compare_server_default=True,
        script_location=config.get_main_option("script_location"),
    )

    with context.begin_transaction():
        context.run_migrations()


def provide_iam_token_for_alembic(
    dialect: Any, conn_rec: Any, cargs: Any, cparams: Any
) -> None:
    if USE_IAM_AUTH:
        # Database connection settings
        region = AWS_REGION_NAME
        host = POSTGRES_HOST
        port = POSTGRES_PORT
        user = POSTGRES_USER

        # Get IAM authentication token
        token = get_iam_auth_token(host, port, user, region)

        # For Alembic / SQLAlchemy in this context, set SSL and password
        cparams["password"] = token
        cparams["ssl"] = ssl_context


async def run_async_migrations() -> None:
    (
        create_schema,
        upgrade_all_tenants,
        continue_on_error,
        tenant_range_start,
        tenant_range_end,
        schemas,
    ) = get_schema_options()

    if not schemas and not MULTI_TENANT:
        schemas = [POSTGRES_DEFAULT_SCHEMA]

    # without init_engine, subsequent engine calls fail hard intentionally
    SqlEngine.init_engine(pool_size=20, max_overflow=5)

    engine = create_async_engine(
        build_connection_string(),
        poolclass=pool.NullPool,
    )

    if USE_IAM_AUTH:

        @event.listens_for(engine.sync_engine, "do_connect")
        def event_provide_iam_token_for_alembic(
            dialect: Any, conn_rec: Any, cargs: Any, cparams: Any
        ) -> None:
            provide_iam_token_for_alembic(dialect, conn_rec, cargs, cparams)

    if schemas:
        # Use specific schema names directly without fetching all tenants
        logger.info(f"Migrating specific schema names: {schemas}")

        i_schema = 0
        num_schemas = len(schemas)
        for schema in schemas:
            i_schema += 1
            logger.info(
                f"Migrating schema: index={i_schema} num_schemas={num_schemas} schema={schema}"
            )
            try:
                async with engine.connect() as connection:
                    await connection.run_sync(
                        do_run_migrations,
                        schema_name=schema,
                        create_schema=create_schema,
                    )
            except Exception as e:
                logger.error(f"Error migrating schema {schema}: {e}")
                if not continue_on_error:
                    logger.error("--continue=true is not set, raising exception!")
                    raise

                logger.warning("--continue=true is set, continuing to next schema.")

    elif upgrade_all_tenants:
        tenant_schemas = get_all_tenant_ids()

        filtered_tenant_schemas = filter_tenants_by_range(
            tenant_schemas, tenant_range_start, tenant_range_end
        )

        if tenant_range_start is not None or tenant_range_end is not None:
            logger.info(
                f"Filtering tenants by range: start={tenant_range_start}, end={tenant_range_end}"
            )
            logger.info(
                f"Total tenants: {len(tenant_schemas)}, Filtered tenants: {len(filtered_tenant_schemas)}"
            )

        i_tenant = 0
        num_tenants = len(filtered_tenant_schemas)
        for schema in filtered_tenant_schemas:
            i_tenant += 1
            logger.info(
                f"Migrating schema: index={i_tenant} num_tenants={num_tenants} schema={schema}"
            )
            try:
                async with engine.connect() as connection:
                    await connection.run_sync(
                        do_run_migrations,
                        schema_name=schema,
                        create_schema=create_schema,
                    )
            except Exception as e:
                logger.error(f"Error migrating schema {schema}: {e}")
                if not continue_on_error:
                    logger.error("--continue=true is not set, raising exception!")
                    raise

                logger.warning("--continue=true is set, continuing to next schema.")

    else:
        # This should not happen in the new design since we require either
        # upgrade_all_tenants=true or schemas in multi-tenant mode
        # and for non-multi-tenant mode, we should use schemas with the default schema
        raise ValueError(
            "No migration target specified. Use either upgrade_all_tenants=true for all tenants "
            "or schemas for specific schemas."
        )

    await engine.dispose()


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
    ) = get_schema_options()
    url = build_connection_string()

    if schemas:
        # Use specific schema names directly without fetching all tenants
        logger.info(f"Migrating specific schema names: {schemas}")

        for schema in schemas:
            logger.info(f"Migrating schema: {schema}")
            context.configure(
                url=url,
                target_metadata=target_metadata,  # type: ignore
                literal_binds=True,
                include_object=include_object,
                version_table_schema=schema,
                include_schemas=True,
                script_location=config.get_main_option("script_location"),
                dialect_opts={"paramstyle": "named"},
            )

            with context.begin_transaction():
                context.run_migrations()

    elif upgrade_all_tenants:
        engine = create_async_engine(url)

        if USE_IAM_AUTH:

            @event.listens_for(engine.sync_engine, "do_connect")
            def event_provide_iam_token_for_alembic_offline(
                dialect: Any, conn_rec: Any, cargs: Any, cparams: Any
            ) -> None:
                provide_iam_token_for_alembic(dialect, conn_rec, cargs, cparams)

        tenant_schemas = get_all_tenant_ids()
        engine.sync_engine.dispose()

        filtered_tenant_schemas = filter_tenants_by_range(
            tenant_schemas, tenant_range_start, tenant_range_end
        )

        if tenant_range_start is not None or tenant_range_end is not None:
            logger.info(
                f"Filtering tenants by range: start={tenant_range_start}, end={tenant_range_end}"
            )
            logger.info(
                f"Total tenants: {len(tenant_schemas)}, Filtered tenants: {len(filtered_tenant_schemas)}"
            )

        for schema in filtered_tenant_schemas:
            logger.info(f"Migrating schema: {schema}")
            context.configure(
                url=url,
                target_metadata=target_metadata,  # type: ignore
                literal_binds=True,
                include_object=include_object,
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
            "No migration target specified. Use either upgrade_all_tenants=true for all tenants "
            "or schemas for specific schemas."
        )


def run_migrations_online() -> None:
    logger.info("run_migrations_online starting.")
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
