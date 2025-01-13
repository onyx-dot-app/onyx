import logging
import os
from types import SimpleNamespace

from sqlalchemy import text
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema

from alembic import command
from alembic.config import Config
from onyx.db.engine import build_connection_string
from onyx.db.engine import get_sqlalchemy_engine

logger = logging.getLogger(__name__)


def run_alembic_migrations(schema_name: str) -> None:
    logger.info(f"Starting Alembic migrations for schema: {schema_name}")

    try:
        current_dir = os.path.dirname(os.path.abspath(__file__))
        root_dir = os.path.abspath(os.path.join(current_dir, "..", "..", "..", ".."))
        alembic_ini_path = os.path.join(root_dir, "alembic.ini")

        # Configure Alembic
        alembic_cfg = Config(alembic_ini_path)
        alembic_cfg.set_main_option("sqlalchemy.url", build_connection_string())
        alembic_cfg.set_main_option(
            "script_location", os.path.join(root_dir, "alembic")
        )

        # Ensure that logging isn't broken
        alembic_cfg.attributes["configure_logger"] = False

        # Mimic command-line options by adding 'cmd_opts' to the config
        alembic_cfg.cmd_opts = SimpleNamespace()  # type: ignore
        alembic_cfg.cmd_opts.x = [f"schema={schema_name}"]  # type: ignore

        # Run migrations programmatically
        command.upgrade(alembic_cfg, "head")

        # Run migrations programmatically
        logger.info(
            f"Alembic migrations completed successfully for schema: {schema_name}"
        )

    except Exception as e:
        logger.exception(f"Alembic migration failed for schema {schema_name}: {str(e)}")
        raise


def create_schema_if_not_exists(tenant_id: str) -> bool:
    with Session(get_sqlalchemy_engine()) as db_session:
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


def drop_schema(tenant_id: str) -> None:
    if not tenant_id.isidentifier():
        raise ValueError("Invalid tenant_id.")
    with get_sqlalchemy_engine().connect() as connection:
        connection.execute(
            text("DROP SCHEMA IF EXISTS %(schema_name)s CASCADE"),
            {"schema_name": tenant_id},
        )
