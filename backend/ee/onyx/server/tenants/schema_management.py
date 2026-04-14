import logging
import os
import re
from types import SimpleNamespace

from sqlalchemy import text
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema

from alembic import command
from alembic.config import Config
from onyx.configs.app_configs import POSTGRES_HOSTS
from onyx.db.engine.sql_engine import build_connection_string
from onyx.db.engine.sql_engine import SqlEngine
from shared_configs.configs import TENANT_ID_PREFIX

logger = logging.getLogger(__name__)

TENANT_ID_PATTERN = re.compile(
    rf"^{re.escape(TENANT_ID_PREFIX)}("
    r"[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}"
    r"|i-[a-f0-9]+"
    r")$"
)


def validate_tenant_id(tenant_id: str) -> bool:
    """Validate that tenant_id matches expected format.

    This is important for SQL injection prevention since schema names
    cannot be parameterized in SQL and must be formatted directly.
    """
    return bool(TENANT_ID_PATTERN.match(tenant_id))


def run_alembic_migrations(schema_name: str, host_index: int = 0) -> None:
    logger.info(
        f"Starting Alembic migrations for schema: {schema_name} "
        f"on host_index={host_index}"
    )

    try:
        current_dir = os.path.dirname(os.path.abspath(__file__))
        root_dir = os.path.abspath(os.path.join(current_dir, "..", "..", "..", ".."))
        alembic_ini_path = os.path.join(root_dir, "alembic.ini")

        host = (
            POSTGRES_HOSTS[host_index]
            if host_index < len(POSTGRES_HOSTS)
            else POSTGRES_HOSTS[0]
        )
        alembic_cfg = Config(alembic_ini_path)
        alembic_cfg.set_main_option(
            "sqlalchemy.url", build_connection_string(host=host)
        )
        alembic_cfg.set_main_option(
            "script_location", os.path.join(root_dir, "alembic")
        )

        alembic_cfg.attributes["configure_logger"] = False

        alembic_cfg.cmd_opts = SimpleNamespace()  # type: ignore
        alembic_cfg.cmd_opts.x = [f"schemas={schema_name}"]  # type: ignore

        command.upgrade(alembic_cfg, "head")

        logger.info(
            f"Alembic migrations completed successfully for schema: {schema_name}"
        )

    except Exception as e:
        logger.exception(f"Alembic migration failed for schema {schema_name}: {str(e)}")
        raise


def create_schema_if_not_exists(tenant_id: str, host_index: int = 0) -> bool:
    engine = SqlEngine.get_engine(host_index)
    with Session(engine) as db_session:
        with db_session.begin():
            result = db_session.execute(
                text(
                    "SELECT schema_name FROM information_schema.schemata WHERE schema_name = :schema_name"
                ),
                {"schema_name": tenant_id},
            )
            schema_exists = result.scalar() is not None
            if not schema_exists:
                stmt = CreateSchema(tenant_id)
                db_session.execute(stmt)
                return True
            return False


def drop_schema(tenant_id: str, host_index: int = 0) -> None:
    """Drop a tenant's schema.

    Uses strict regex validation to reject unexpected formats early,
    preventing SQL injection since schema names cannot be parameterized.
    """
    if not validate_tenant_id(tenant_id):
        raise ValueError(f"Invalid tenant_id format: {tenant_id}")

    engine = SqlEngine.get_engine(host_index)
    with engine.connect() as connection:
        with connection.begin():
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{tenant_id}" CASCADE'))


def get_current_alembic_version(tenant_id: str, host_index: int = 0) -> str:
    """Get the current Alembic version for a tenant."""
    from alembic.runtime.migration import MigrationContext
    from sqlalchemy import text

    engine = SqlEngine.get_engine(host_index)

    with engine.connect() as connection:
        connection.execute(text(f'SET search_path TO "{tenant_id}"'))

        context = MigrationContext.configure(connection)
        current_rev = context.get_current_revision()

    return current_rev or "head"
