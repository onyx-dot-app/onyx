import logging
import os
import time
from types import SimpleNamespace

import psycopg2
import requests

from alembic import command
from alembic.config import Config
from onyx.configs.app_configs import POSTGRES_HOST
from onyx.configs.app_configs import POSTGRES_PASSWORD
from onyx.configs.app_configs import POSTGRES_PORT
from onyx.configs.app_configs import POSTGRES_USER
from onyx.db.engine.sql_engine import build_connection_string
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.engine.sql_engine import SYNC_DB_API
from onyx.db.engine.tenant_utils import get_all_tenant_ids
from onyx.db.search_settings import get_current_search_settings
from onyx.db.swap_index import check_and_perform_index_swap
from onyx.document_index.document_index_utils import get_multipass_config
from onyx.document_index.vespa.index import DOCUMENT_ID_ENDPOINT
from onyx.document_index.vespa.index import VespaIndex
from onyx.file_store.file_store import get_default_file_store
from onyx.indexing.models import IndexingSetting
from onyx.setup import setup_postgres
from onyx.setup import setup_vespa
from onyx.utils.logger import setup_logger
from tests.integration.common_utils.timeout import run_with_timeout_multiproc

logger = setup_logger()


def _run_migrations(
    database_url: str,
    config_name: str,
    direction: str = "upgrade",
    revision: str = "head",
    schema: str = "public",
) -> None:
    # hide info logs emitted during migration
    logging.getLogger("alembic").setLevel(logging.CRITICAL)

    # Create an Alembic configuration object
    alembic_cfg = Config("alembic.ini")
    alembic_cfg.set_section_option("logger_alembic", "level", "WARN")
    alembic_cfg.attributes["configure_logger"] = False
    alembic_cfg.config_ini_section = config_name

    alembic_cfg.cmd_opts = SimpleNamespace()  # type: ignore
    alembic_cfg.cmd_opts.x = [f"schema={schema}"]  # type: ignore

    # Set the SQLAlchemy URL in the Alembic configuration
    alembic_cfg.set_main_option("sqlalchemy.url", database_url)

    # Run the migration
    if direction == "upgrade":
        command.upgrade(alembic_cfg, revision)
    elif direction == "downgrade":
        command.downgrade(alembic_cfg, revision)
    else:
        raise ValueError(
            f"Invalid direction: {direction}. Must be 'upgrade' or 'downgrade'."
        )

    logging.getLogger("alembic").setLevel(logging.INFO)


def downgrade_postgres(
    database: str = "postgres",
    schema: str = "public",
    config_name: str = "alembic",
    revision: str = "base",
    clear_data: bool = False,
) -> None:
    """Downgrade Postgres database to base state."""
    if clear_data:
        if revision != "base":
            raise ValueError("Clearing data without rolling back to base state")

        conn = psycopg2.connect(
            dbname=database,
            user=POSTGRES_USER,
            password=POSTGRES_PASSWORD,
            host=POSTGRES_HOST,
            port=POSTGRES_PORT,
            application_name="downgrade_postgres",
        )
        conn.autocommit = True  # Need autocommit for dropping schema
        cur = conn.cursor()

        # Close any existing connections to the schema before dropping
        cur.execute(
            f"""
            SELECT pg_terminate_backend(pg_stat_activity.pid)
            FROM pg_stat_activity
            WHERE pg_stat_activity.datname = '{database}'
            AND pg_stat_activity.state = 'idle in transaction'
            AND pid <> pg_backend_pid();
        """
        )

        # Drop and recreate the public schema - this removes ALL objects
        cur.execute(f"DROP SCHEMA {schema} CASCADE;")
        cur.execute(f"CREATE SCHEMA {schema};")

        # Restore default privileges
        cur.execute(f"GRANT ALL ON SCHEMA {schema} TO postgres;")
        cur.execute(f"GRANT ALL ON SCHEMA {schema} TO public;")

        cur.close()
        conn.close()

        return

    # Downgrade to base
    conn_str = build_connection_string(
        db=database,
        user=POSTGRES_USER,
        password=POSTGRES_PASSWORD,
        host=POSTGRES_HOST,
        port=POSTGRES_PORT,
        db_api=SYNC_DB_API,
    )
    _run_migrations(
        conn_str,
        config_name,
        direction="downgrade",
        revision=revision,
    )


def upgrade_postgres(
    database: str = "postgres", config_name: str = "alembic", revision: str = "head"
) -> None:
    """Upgrade Postgres database to latest version."""
    conn_str = build_connection_string(
        db=database,
        user=POSTGRES_USER,
        password=POSTGRES_PASSWORD,
        host=POSTGRES_HOST,
        port=POSTGRES_PORT,
        db_api=SYNC_DB_API,
        app_name="upgrade_postgres",
    )
    _run_migrations(
        conn_str,
        config_name,
        direction="upgrade",
        revision=revision,
    )


def drop_multitenant_postgres(
    database: str = "postgres",
) -> None:
    """Reset the Postgres database."""
    # this seems to hang due to locking issues, so run with a timeout with a few retries
    NUM_TRIES = 10
    TIMEOUT = 40
    success = False
    for _ in range(NUM_TRIES):
        logger.info(f"drop_multitenant_postgres_task starting... ({_ + 1}/{NUM_TRIES})")
        try:
            run_with_timeout_multiproc(
                drop_multitenant_postgres_task,
                TIMEOUT,
                kwargs={
                    "dbname": database,
                },
            )
            success = True
            break
        except TimeoutError:
            logger.warning(
                f"drop_multitenant_postgres_task timed out, retrying... ({_ + 1}/{NUM_TRIES})"
            )
        except RuntimeError:
            logger.warning(
                f"drop_multitenant_postgres_task exceptioned, retrying... ({_ + 1}/{NUM_TRIES})"
            )

    if not success:
        raise RuntimeError("drop_multitenant_postgres_task failed after 10 timeouts.")


def drop_multitenant_postgres_task(dbname: str) -> None:
    conn = psycopg2.connect(
        dbname=dbname,
        user=POSTGRES_USER,
        password=POSTGRES_PASSWORD,
        host=POSTGRES_HOST,
        port=POSTGRES_PORT,
        connect_timeout=10,
        application_name="drop_multitenant_postgres_task",
    )

    conn.autocommit = True
    cur = conn.cursor()

    logger.info("Selecting tenant schemas.")
    # Get all tenant schemas
    cur.execute(
        """
        SELECT schema_name
        FROM information_schema.schemata
        WHERE schema_name LIKE 'tenant_%'
        """
    )
    tenant_schemas = cur.fetchall()

    # Drop all tenant schemas
    logger.info("Dropping all tenant schemas.")
    for schema in tenant_schemas:
        # Close any existing connections to the schema before dropping
        cur.execute(
            """
            SELECT pg_terminate_backend(pg_stat_activity.pid)
            FROM pg_stat_activity
            WHERE pg_stat_activity.datname = 'postgres'
            AND pg_stat_activity.state = 'idle in transaction'
            AND pid <> pg_backend_pid();
        """
        )

        schema_name = schema[0]
        cur.execute(f'DROP SCHEMA "{schema_name}" CASCADE')

    # Drop tables in the public schema
    logger.info("Selecting public schema tables.")
    cur.execute(
        """
        SELECT tablename FROM pg_tables
        WHERE schemaname = 'public'
        """
    )
    public_tables = cur.fetchall()

    logger.info("Dropping public schema tables.")
    for table in public_tables:
        table_name = table[0]
        cur.execute(f'DROP TABLE IF EXISTS public."{table_name}" CASCADE')

    cur.close()
    conn.close()


def reset_postgres(
    database: str = "postgres",
    config_name: str = "alembic",
    setup_onyx: bool = True,
) -> None:
    """Reset the Postgres database."""
    # this seems to hang due to locking issues, so run with a timeout with a few retries
    NUM_TRIES = 10
    TIMEOUT = 40
    success = False
    for _ in range(NUM_TRIES):
        logger.info(f"Downgrading Postgres... ({_ + 1}/{NUM_TRIES})")
        try:
            run_with_timeout_multiproc(
                downgrade_postgres,
                TIMEOUT,
                kwargs={
                    "database": database,
                    "config_name": config_name,
                    "revision": "base",
                    "clear_data": True,
                },
            )
            success = True
            break
        except TimeoutError:
            logger.warning(
                f"Postgres downgrade timed out, retrying... ({_ + 1}/{NUM_TRIES})"
            )
        except RuntimeError:
            logger.warning(
                f"Postgres downgrade exceptioned, retrying... ({_ + 1}/{NUM_TRIES})"
            )

    if not success:
        raise RuntimeError("Postgres downgrade failed after 10 timeouts.")

    logger.info("Upgrading Postgres...")
    upgrade_postgres(database=database, config_name=config_name, revision="head")
    if setup_onyx:
        logger.info("Setting up Postgres...")
        with get_session_with_current_tenant() as db_session:
            setup_postgres(db_session)


def reset_vespa() -> None:
    """Wipe all data from the Vespa index."""

    with get_session_with_current_tenant() as db_session:
        # swap to the correct default model
        check_and_perform_index_swap(db_session)

        search_settings = get_current_search_settings(db_session)
        multipass_config = get_multipass_config(search_settings)
        index_name = search_settings.index_name

    success = setup_vespa(
        document_index=VespaIndex(
            index_name=index_name,
            secondary_index_name=None,
            large_chunks_enabled=multipass_config.enable_large_chunks,
            secondary_large_chunks_enabled=None,
        ),
        index_setting=IndexingSetting.from_db_model(search_settings),
        secondary_index_setting=None,
    )
    if not success:
        raise RuntimeError("Could not connect to Vespa within the specified timeout.")

    for _ in range(5):
        try:
            continuation = None
            should_continue = True
            while should_continue:
                params = {"selection": "true", "cluster": "danswer_index"}
                if continuation:
                    params = {**params, "continuation": continuation}
                response = requests.delete(
                    DOCUMENT_ID_ENDPOINT.format(index_name=index_name), params=params
                )
                response.raise_for_status()

                response_json = response.json()

                continuation = response_json.get("continuation")
                should_continue = bool(continuation)

            break
        except Exception as e:
            print(f"Error deleting documents: {e}")
            time.sleep(5)


def reset_postgres_multitenant() -> None:
    """Reset the Postgres database for all tenants in a multitenant setup."""

    drop_multitenant_postgres()
    reset_postgres(config_name="schema_private", setup_onyx=False)


def reset_vespa_multitenant() -> None:
    """Wipe all data from the Vespa index for all tenants."""

    for tenant_id in get_all_tenant_ids():
        with get_session_with_tenant(tenant_id=tenant_id) as db_session:
            # swap to the correct default model for each tenant
            check_and_perform_index_swap(db_session)

            search_settings = get_current_search_settings(db_session)
            multipass_config = get_multipass_config(search_settings)
            index_name = search_settings.index_name

        success = setup_vespa(
            document_index=VespaIndex(
                index_name=index_name,
                secondary_index_name=None,
                large_chunks_enabled=multipass_config.enable_large_chunks,
                secondary_large_chunks_enabled=None,
            ),
            index_setting=IndexingSetting.from_db_model(search_settings),
            secondary_index_setting=None,
        )

        if not success:
            raise RuntimeError(
                f"Could not connect to Vespa for tenant {tenant_id} within the specified timeout."
            )

        for _ in range(5):
            try:
                continuation = None
                should_continue = True
                while should_continue:
                    params = {"selection": "true", "cluster": "danswer_index"}
                    if continuation:
                        params = {**params, "continuation": continuation}
                    response = requests.delete(
                        DOCUMENT_ID_ENDPOINT.format(index_name=index_name),
                        params=params,
                    )
                    response.raise_for_status()

                    response_json = response.json()

                    continuation = response_json.get("continuation")
                    should_continue = bool(continuation)

                break
            except Exception as e:
                print(f"Error deleting documents for tenant {tenant_id}: {e}")
                time.sleep(5)


def reset_file_store() -> None:
    """Reset the FileStore."""
    filestore = get_default_file_store()
    for file_record in filestore.list_files_by_prefix(""):
        filestore.delete_file(file_record.file_id)


def reset_all() -> None:
    if os.environ.get("SKIP_RESET", "").lower() == "true":
        logger.info("Skipping reset.")
        return

    logger.info("Resetting Postgres...")
    reset_postgres()
    logger.info("Resetting Vespa...")
    reset_vespa()
    logger.info("Resetting FileStore...")
    reset_file_store()


def reset_all_multitenant() -> None:
    """Reset both Postgres and Vespa for all tenants.

    Honors SKIP_RESET env var to allow callers (e.g., CI) to disable
    heavy resets entirely for faster end-to-end runs.
    """
    if os.environ.get("SKIP_RESET", "").lower() == "true":
        logger.info("SKIPPING multitenant reset due to SKIP_RESET=true")
        return

    logger.info("Resetting Postgres for all tenants...")
    reset_postgres_multitenant()
    logger.info("Resetting Vespa for all tenants...")
    reset_vespa_multitenant()
    logger.info("Finished resetting all.")
