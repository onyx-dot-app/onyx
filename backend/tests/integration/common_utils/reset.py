import logging
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
from onyx.db.engine import build_connection_string
from onyx.db.engine import get_all_tenant_ids
from onyx.db.engine import get_session_context_manager
from onyx.db.engine import get_session_with_tenant
from onyx.db.engine import SYNC_DB_API
from onyx.db.search_settings import get_current_search_settings
from onyx.db.swap_index import check_index_swap
from onyx.document_index.vespa.index import DOCUMENT_ID_ENDPOINT
from onyx.document_index.vespa.index import VespaIndex
from onyx.indexing.models import IndexingSetting
from onyx.setup import setup_postgres
from onyx.setup import setup_vespa
from onyx.utils.logger import setup_logger

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
    config_name: str = "alembic",
    revision: str = "base",
    clear_data: bool = False,
) -> None:
    """Downgrade Postgres database to base state."""
    if clear_data:
        if revision != "base":
            logger.warning("Clearing data without rolling back to base state")
        # Delete all rows to allow migrations to be rolled back
        conn = psycopg2.connect(
            dbname=database,
            user=POSTGRES_USER,
            password=POSTGRES_PASSWORD,
            host=POSTGRES_HOST,
            port=POSTGRES_PORT,
        )
        cur = conn.cursor()

        # Disable triggers to prevent foreign key constraints from being checked
        cur.execute("SET session_replication_role = 'replica';")

        # Fetch all table names in the current database
        cur.execute(
            """
            SELECT tablename
            FROM pg_tables
            WHERE schemaname = 'public'
        """
        )

        tables = cur.fetchall()

        for table in tables:
            table_name = table[0]

            # Don't touch migration history or Kombu
            if table_name in ("alembic_version", "kombu_message", "kombu_queue"):
                continue

            cur.execute(f'DELETE FROM "{table_name}"')

        # Re-enable triggers
        cur.execute("SET session_replication_role = 'origin';")

        conn.commit()
        cur.close()
        conn.close()

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
    )
    _run_migrations(
        conn_str,
        config_name,
        direction="upgrade",
        revision=revision,
    )


def reset_postgres(
    database: str = "postgres",
    config_name: str = "alembic",
    setup_onyx: bool = True,
) -> None:
    """Reset the Postgres database."""
    downgrade_postgres(
        database=database, config_name=config_name, revision="base", clear_data=True
    )
    upgrade_postgres(database=database, config_name=config_name, revision="head")
    if setup_onyx:
        with get_session_context_manager() as db_session:
            setup_postgres(db_session)


def reset_vespa(index_name: str | None = None) -> None:
    """Wipe all data from the Vespa index.

    Args:
        index_name: Optional index name for parallel test execution.
    """
    with get_session_context_manager() as db_session:
        # swap to the correct default model
        check_index_swap(db_session)

        # Get search settings first
        search_settings = get_current_search_settings(db_session)

        # Then handle index name
        if not index_name:
            index_name = str(search_settings.index_name)

    success = setup_vespa(
        document_index=VespaIndex(index_name=index_name, secondary_index_name=None),
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


def reset_postgres_multitenant(worker_id: str = "0") -> None:
    """Reset the Postgres database for all tenants in a multitenant setup.

    Args:
        worker_id: The worker ID for parallel test execution. Used to namespace schemas.
    """
    conn = psycopg2.connect(
        dbname="postgres",
        user=POSTGRES_USER,
        password=POSTGRES_PASSWORD,
        host=POSTGRES_HOST,
        port=POSTGRES_PORT,
    )
    conn.autocommit = True
    cur = conn.cursor()

    # Get all tenant schemas for this worker
    cur.execute(
        """
        SELECT schema_name
        FROM information_schema.schemata
        WHERE schema_name LIKE %s
        """,
        [f"tenant_%_{worker_id}"],
    )
    tenant_schemas = cur.fetchall()

    # Drop all tenant schemas for this worker
    for schema in tenant_schemas:
        schema_name = schema[0]
        cur.execute(f'DROP SCHEMA "{schema_name}" CASCADE')

    cur.close()
    conn.close()

    reset_postgres(config_name="schema_private", setup_onyx=False)


def reset_vespa_multitenant(worker_id: str = "0") -> None:
    """Wipe all data from the Vespa index for all tenants.

    Args:
        worker_id: The worker ID for parallel test execution. Used to namespace indices.
    """
    for tenant_id in get_all_tenant_ids():
        # Make tenant IDs unique per worker
        worker_tenant_id = f"{tenant_id}_{worker_id}"
        with get_session_with_tenant(tenant_id=worker_tenant_id) as db_session:
            # swap to the correct default model for each tenant
            check_index_swap(db_session)

            search_settings = get_current_search_settings(db_session)
            # Make index name worker-specific
            base_index_name = search_settings.index_name
            worker_index_name = f"{base_index_name}_{worker_id}"

        success = setup_vespa(
            document_index=VespaIndex(
                index_name=str(worker_index_name), secondary_index_name=None
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
                        DOCUMENT_ID_ENDPOINT.format(index_name=worker_index_name),
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


def reset_all(schema_name: str | None = None) -> None:
    """Reset both Postgres and Vespa.

    Args:
        schema_name: Optional schema name for parallel test execution.
    """
    logger.info(
        f"Resetting Postgres{f' for schema {schema_name}' if schema_name else ''}..."
    )
    reset_postgres(database="postgres", config_name="alembic", setup_onyx=True)
    logger.info("Resetting Vespa...")
    # Use schema_name as index suffix if provided
    if schema_name:
        with get_session_context_manager() as db_session:
            search_settings = get_current_search_settings(db_session)
            index_name = f"{search_settings.index_name}_{schema_name}"
            reset_vespa(index_name=index_name)
    else:
        reset_vespa()


def reset_all_multitenant(worker_id: str = "0") -> None:
    """Reset both Postgres and Vespa for all tenants.

    Args:
        worker_id: The worker ID for parallel test execution. Used to namespace schemas and indices.
    """
    logger.info(f"Resetting Postgres for all tenants (worker {worker_id})...")
    reset_postgres_multitenant(worker_id=worker_id)
    logger.info(f"Resetting Vespa for all tenants (worker {worker_id})...")
    reset_vespa_multitenant(worker_id=worker_id)
    logger.info("Finished resetting all.")
