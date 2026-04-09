import asyncio
import logging
from logging.config import fileConfig
from typing import Any

from sqlalchemy import event
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import context
from onyx.configs.app_configs import AWS_REGION_NAME
from onyx.configs.app_configs import POSTGRES_HOST
from onyx.configs.app_configs import POSTGRES_PORT
from onyx.configs.app_configs import POSTGRES_REQUIRE_SSL
from onyx.configs.app_configs import POSTGRES_USER
from onyx.configs.app_configs import USE_IAM_AUTH
from onyx.db.engine.iam_auth import get_iam_auth_token
from onyx.db.engine.rds_ssl import get_rds_ssl_context_or_require
from onyx.db.engine.sql_engine import build_connection_string
from onyx.db.models import PublicBase

logger = logging.getLogger(__name__)

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None and config.attributes.get(
    "configure_logger", True
):
    # disable_existing_loggers=False prevents breaking pytest's caplog fixture
    # See: https://pytest-alembic.readthedocs.io/en/latest/setup.html#caplog-issues
    fileConfig(config.config_file_name, disable_existing_loggers=False)

# add your model's MetaData object here
# for 'autogenerate' support
# from myapp import mymodel
# target_metadata = mymodel.Base.metadata
target_metadata = [PublicBase.metadata]

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = build_connection_string()
    context.configure(
        url=url,
        target_metadata=target_metadata,  # type: ignore
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,  # type: ignore[arg-type]
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """In this scenario we need to create an Engine
    and associate a connection with the context.

    """

    connect_args: dict[str, Any] = {}

    # Configure SSL if required
    # IAM auth always requires SSL, or can be explicitly enabled via POSTGRES_REQUIRE_SSL
    if USE_IAM_AUTH or POSTGRES_REQUIRE_SSL:
        ssl_context = get_rds_ssl_context_or_require()
        connect_args["ssl"] = ssl_context
        logger.info(f"Alembic tenants: SSL configured for asyncpg: ssl={ssl_context}")
    else:
        logger.warning(
            "Alembic tenants: SSL NOT configured - USE_IAM_AUTH and POSTGRES_REQUIRE_SSL are both False"
        )

    connectable = create_async_engine(
        build_connection_string(),
        poolclass=pool.NullPool,
        connect_args=connect_args,
    )

    # For IAM auth, set up event listener to generate fresh tokens
    if USE_IAM_AUTH:
        logger.info("Alembic tenants: Setting up IAM auth event listener")

        @event.listens_for(connectable.sync_engine, "do_connect")
        def provide_iam_token_alembic_tenants(
            dialect: Any,  # noqa: ARG001
            conn_rec: Any,  # noqa: ARG001
            cargs: Any,  # noqa: ARG001
            cparams: Any,
        ) -> None:
            logger.info("Alembic tenants: IAM auth event listener TRIGGERED")
            logger.info(f"Alembic tenants: cparams keys before: {list(cparams.keys())}")
            try:
                token = get_iam_auth_token(
                    POSTGRES_HOST, POSTGRES_PORT, POSTGRES_USER, AWS_REGION_NAME
                )
                if not token:
                    raise RuntimeError("IAM token is None after generation")

                cparams["password"] = token
                logger.info(
                    f"Alembic tenants: Set IAM token as password (length={len(token)})"
                )

                # ALWAYS set SSL for IAM auth (required)
                # connect_args may not propagate to cparams, so we must set it here
                cparams["ssl"] = get_rds_ssl_context_or_require()
                logger.info(
                    f"Alembic tenants: Set ssl={cparams['ssl']} for "
                    f"{POSTGRES_HOST}:{POSTGRES_PORT}"
                )
                logger.info(
                    f"Alembic tenants: cparams keys after: {list(cparams.keys())}"
                )

            except Exception as e:
                logger.error(
                    f"Alembic tenants: Failed to configure IAM auth: {e}",
                    exc_info=True,
                )
                raise

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


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
        with connectable.connect() as connection:
            do_run_migrations(connection)
            # Commit to ensure changes are visible to next migration
            connection.commit()
    else:
        # Normal operation - use async migrations
        asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
