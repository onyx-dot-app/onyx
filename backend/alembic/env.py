import asyncio
import logging
import os
import ssl
from logging.config import fileConfig
from typing import Any, Literal

from celery.backends.database.session import ResultModelBase  # type: ignore
from sqlalchemy import event, pool, text
from sqlalchemy.engine.base import Connection
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.sql.schema import SchemaItem

from alembic import context
from onyx.configs.app_configs import (
    AWS_REGION_NAME,
    POSTGRES_HOST,
    POSTGRES_PORT,
    POSTGRES_USER,
    USE_IAM_AUTH,
)
from onyx.configs.constants import SSL_CERT_FILE
from onyx.db.engine import (
    SqlEngine,
    build_connection_string,
    get_all_tenant_ids,
    get_iam_auth_token,
)
from onyx.db.models import Base
from shared_configs.configs import MULTI_TENANT, POSTGRES_DEFAULT_SCHEMA

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


def get_schema_options() -> tuple[str, bool, bool, bool]:
    x_args_raw = context.get_x_argument()
    x_args = {}
    for arg in x_args_raw:
        for pair in arg.split(","):
            if "=" in pair:
                key, value = pair.split("=", 1)
                x_args[key.strip()] = value.strip()
    schema_name = x_args.get("schema", POSTGRES_DEFAULT_SCHEMA)
    create_schema = x_args.get("create_schema", "true").lower() == "true"
    upgrade_all_tenants = x_args.get("upgrade_all_tenants", "false").lower() == "true"

    # continue on error with individual tenant
    # only applies to online migrations
    continue_on_error = x_args.get("continue", "false").lower() == "true"

    if (
        MULTI_TENANT
        and schema_name == POSTGRES_DEFAULT_SCHEMA
        and not upgrade_all_tenants
    ):
        raise ValueError(
            "Cannot run default migrations in public schema when multi-tenancy is enabled. "
            "Please specify a tenant-specific schema."
        )

    return schema_name, create_schema, upgrade_all_tenants, continue_on_error


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
        schema_name,
        create_schema,
        upgrade_all_tenants,
        continue_on_error,
    ) = get_schema_options()

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

    if upgrade_all_tenants:
        tenant_schemas = get_all_tenant_ids()

        i_tenant = 0
        num_tenants = len(tenant_schemas)
        for schema in tenant_schemas:
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
        try:
            logger.info(f"Migrating schema: {schema_name}")
            async with engine.connect() as connection:
                await connection.run_sync(
                    do_run_migrations,
                    schema_name=schema_name,
                    create_schema=create_schema,
                )
        except Exception as e:
            logger.error(f"Error migrating schema {schema_name}: {e}")
            raise

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

    schema_name, _, upgrade_all_tenants, continue_on_error = get_schema_options()
    url = build_connection_string()

    if upgrade_all_tenants:
        engine = create_async_engine(url)

        if USE_IAM_AUTH:

            @event.listens_for(engine.sync_engine, "do_connect")
            def event_provide_iam_token_for_alembic_offline(
                dialect: Any, conn_rec: Any, cargs: Any, cparams: Any
            ) -> None:
                provide_iam_token_for_alembic(dialect, conn_rec, cargs, cparams)

        tenant_schemas = get_all_tenant_ids()
        engine.sync_engine.dispose()

        for schema in tenant_schemas:
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
        logger.info(f"Migrating schema: {schema_name}")
        context.configure(
            url=url,
            target_metadata=target_metadata,  # type: ignore
            literal_binds=True,
            include_object=include_object,
            version_table_schema=schema_name,
            include_schemas=True,
            script_location=config.get_main_option("script_location"),
            dialect_opts={"paramstyle": "named"},
        )

        with context.begin_transaction():
            context.run_migrations()


def run_migrations_online() -> None:
    logger.info("run_migrations_online starting.")
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
