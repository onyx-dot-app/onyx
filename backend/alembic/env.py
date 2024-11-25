from sqlalchemy.engine.base import Connection
from typing import Any
import asyncio
from logging.config import fileConfig
import logging

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.sql import text

from shared_configs.configs import MULTI_TENANT
from danswer.db.engine import build_connection_string
from danswer.db.models import Base
from celery.backends.database.session import ResultModelBase  # type: ignore
from danswer.db.engine import get_all_tenant_ids
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA

# Alembic Config object
config = context.config

# Interpret the config file for Python logging.
if config.config_file_name is not None and config.attributes.get(
    "configure_logger", True
):
    fileConfig(config.config_file_name)

# Add your model's MetaData object here for 'autogenerate' support
target_metadata = [Base.metadata, ResultModelBase.metadata]

EXCLUDE_TABLES = {"kombu_queue", "kombu_message"}

# Set up logging
logger = logging.getLogger(__name__)


def include_object(
    object: Any, name: str, type_: str, reflected: bool, compare_to: Any
) -> bool:
    """
    Determines whether a database object should be included in migrations.
    Excludes specified tables from migrations.
    """
    if type_ == "table" and name in EXCLUDE_TABLES:
        return False
    return True


def get_schema_options() -> tuple[str, bool, bool]:
    """
    Parses command-line options passed via '-x' in Alembic commands.
    Recognizes 'schema', 'create_schema', and 'upgrade_all_tenants' options.
    """
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

    if (
        MULTI_TENANT
        and schema_name == POSTGRES_DEFAULT_SCHEMA
        and not upgrade_all_tenants
    ):
        raise ValueError(
            "Cannot run default migrations in public schema when multi-tenancy is enabled. "
            "Please specify a tenant-specific schema."
        )

    return schema_name, create_schema, upgrade_all_tenants


def do_run_migrations(
    connection: Connection, schema_name: str, create_schema: bool
) -> None:
    """
    Executes migrations in the specified schema.
    """
    logger.info(f"About to migrate schema: {schema_name}")

    if create_schema:
        connection.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema_name}"'))
        connection.execute(text("COMMIT"))

    # Set search_path to the target schema
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


async def run_async_migrations() -> None:
    """
    Determines whether to run migrations for a single schema or all schemas,
    and executes migrations accordingly.
    """
    schema_name, create_schema, upgrade_all_tenants = get_schema_options()

    engine = create_async_engine(
        build_connection_string(),
        poolclass=pool.NullPool,
    )

    if upgrade_all_tenants:
        # Run migrations for all tenant schemas sequentially
        tenant_schemas = get_all_tenant_ids()

        for schema in tenant_schemas:
            try:
                logger.info(f"Migrating schema: {schema}")
                async with engine.connect() as connection:
                    await connection.run_sync(
                        do_run_migrations,
                        schema_name=schema,
                        create_schema=create_schema,
                    )
            except Exception as e:
                logger.error(f"Error migrating schema {schema}: {e}")
                raise
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
    Run migrations in 'offline' mode.
    """
    schema_name, _, upgrade_all_tenants = get_schema_options()
    url = build_connection_string()

    if upgrade_all_tenants:
        # Run offline migrations for all tenant schemas
        engine = create_async_engine(url)
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
    """
    Runs migrations in 'online' mode using an asynchronous engine.
    """
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
