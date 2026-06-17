import logging
import os
from types import SimpleNamespace

import psycopg2
from alembic import command
from alembic.config import Config
from sqlalchemy.orm import Session

from onyx.configs.app_configs import POSTGRES_HOST
from onyx.configs.app_configs import POSTGRES_PASSWORD
from onyx.configs.app_configs import POSTGRES_PORT
from onyx.configs.app_configs import POSTGRES_USER
from onyx.db.engine.sql_engine import build_connection_string
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.engine.sql_engine import SYNC_DB_API
from onyx.db.swap_index import check_and_perform_index_swap
from onyx.file_store.file_store import get_default_file_store
from onyx.setup import setup_postgres
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

    alembic_cfg.cmd_opts = SimpleNamespace()  # ty: ignore[invalid-assignment]
    alembic_cfg.cmd_opts.x = [f"schema={schema}"]  # ty: ignore[invalid-assignment]

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
        cur.execute(f"""
            SELECT pg_terminate_backend(pg_stat_activity.pid)
            FROM pg_stat_activity
            WHERE pg_stat_activity.datname = '{database}'
            AND pg_stat_activity.state = 'idle in transaction'
            AND pid <> pg_backend_pid();
        """)

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
        logger.info(
            "drop_multitenant_postgres_task starting... (%s/%s)", _ + 1, NUM_TRIES
        )
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
                "drop_multitenant_postgres_task timed out, retrying... (%s/%s)",
                _ + 1,
                NUM_TRIES,
            )
        except RuntimeError:
            logger.warning(
                "drop_multitenant_postgres_task exceptioned, retrying... (%s/%s)",
                _ + 1,
                NUM_TRIES,
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
    cur.execute("""
        SELECT schema_name
        FROM information_schema.schemata
        WHERE schema_name LIKE 'tenant_%'
        """)
    tenant_schemas = cur.fetchall()

    # Drop all tenant schemas
    logger.info("Dropping all tenant schemas.")
    for schema in tenant_schemas:
        # Close any existing connections to the schema before dropping
        cur.execute("""
            SELECT pg_terminate_backend(pg_stat_activity.pid)
            FROM pg_stat_activity
            WHERE pg_stat_activity.datname = 'postgres'
            AND pg_stat_activity.state = 'idle in transaction'
            AND pid <> pg_backend_pid();
        """)

        schema_name = schema[0]
        cur.execute(f'DROP SCHEMA "{schema_name}" CASCADE')

    # Drop tables in the public schema
    logger.info("Selecting public schema tables.")
    cur.execute("""
        SELECT tablename FROM pg_tables
        WHERE schemaname = 'public'
        """)
    public_tables = cur.fetchall()

    logger.info("Dropping public schema tables.")
    for table in public_tables:
        table_name = table[0]
        cur.execute(f'DROP TABLE IF EXISTS public."{table_name}" CASCADE')

    cur.close()
    conn.close()


def reset_postgres(
    config_name: str = "alembic",
    setup_onyx: bool = True,
) -> None:
    """Reset the Postgres database.

    The target database name is read from the POSTGRES_DB env var. If
    POSTGRES_DB is unset or empty this function raises rather than silently
    falling back to a default.
    """
    database = os.environ.get("POSTGRES_DB", "").strip()
    if not database:
        raise RuntimeError(
            "reset_postgres requires POSTGRES_DB to be set. Refusing to "
            "operate without an explicit target database to avoid wiping "
            "shared infrastructure."
        )
    # this seems to hang due to locking issues, so run with a timeout with a few retries
    NUM_TRIES = 10
    TIMEOUT = 40
    success = False
    for _ in range(NUM_TRIES):
        logger.info("Downgrading Postgres... (%s/%s)", _ + 1, NUM_TRIES)
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
                "Postgres downgrade timed out, retrying... (%s/%s)", _ + 1, NUM_TRIES
            )
        except RuntimeError:
            logger.warning(
                "Postgres downgrade exceptioned, retrying... (%s/%s)", _ + 1, NUM_TRIES
            )

    if not success:
        raise RuntimeError("Postgres downgrade failed after 10 timeouts.")

    logger.info("Upgrading Postgres...")
    upgrade_postgres(database=database, config_name=config_name, revision="head")
    if setup_onyx:
        logger.info("Setting up Postgres...")
        with get_session_with_current_tenant() as db_session:
            setup_postgres(db_session)
            _seed_dev_license_if_set(db_session)
            # Promote the FUTURE search-settings row (danswer_chunk_<model>) to
            # PRESENT so secondary_search_settings is None and the api_server
            # doesn't have to perform the swap mid-request. Previously this
            # lived in reset_vespa(); when Vespa was deprecated the swap call
            # needs to stay.
            check_and_perform_index_swap(db_session)


_PEM_BEGIN = "-----BEGIN ONYX LICENSE-----"
_PEM_END = "-----END ONYX LICENSE-----"


def _seed_dev_license_if_set(db_session: Session) -> None:
    """Seed the ONYX_DEV_LICENSE blob into the License table.

    Called after every Postgres reset so EE-gated routes don't return 402
    after the License row is wiped by alembic downgrade. No-ops when the
    env var is unset.
    """
    blob = os.environ.get("ONYX_DEV_LICENSE", "").strip()
    if not blob:
        return

    if blob.startswith(_PEM_BEGIN) and blob.endswith(_PEM_END):
        blob = "\n".join(blob.split("\n")[1:-1]).strip()

    from ee.onyx.db.license import upsert_license
    from ee.onyx.utils.license import verify_license_signature

    verify_license_signature(blob)
    upsert_license(db_session, blob)
    logger.info("Dev license seeded after Postgres reset")


def reset_postgres_multitenant() -> None:
    """Reset the Postgres database for all tenants in a multitenant setup."""

    drop_multitenant_postgres()
    reset_postgres(config_name="schema_private", setup_onyx=False)


def reset_file_store() -> None:
    """Reset the FileStore."""
    filestore = get_default_file_store()
    for file_record in filestore.list_files_by_prefix(""):
        filestore.delete_file(file_record.file_id)


def reset_all() -> None:
    """Reset state that persists across tests.

    OpenSearch is intentionally NOT reset between tests — tests are expected to
    use unique document IDs (e.g. uuid-based) so they don't collide on shared
    index state, and CI runners are ephemeral so accumulated docs don't leak
    across runs.
    """
    if os.environ.get("SKIP_RESET", "").lower() == "true":
        logger.info("Skipping reset.")
        return

    logger.info("Resetting Postgres...")
    reset_postgres()
    logger.info("Resetting FileStore...")
    reset_file_store()


def reset_all_multitenant() -> None:
    """Reset Postgres for all tenants.

    OpenSearch is intentionally NOT reset; see reset_all() for rationale.
    Honors SKIP_RESET env var to allow callers (e.g., CI) to disable
    heavy resets entirely for faster end-to-end runs.
    """
    if os.environ.get("SKIP_RESET", "").lower() == "true":
        logger.info("SKIPPING multitenant reset due to SKIP_RESET=true")
        return

    logger.info("Resetting Postgres for all tenants...")
    reset_postgres_multitenant()
    logger.info("Finished resetting all.")
