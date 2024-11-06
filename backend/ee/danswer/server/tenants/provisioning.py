import os
from types import SimpleNamespace

from sqlalchemy import text
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema

from alembic import command
from alembic.config import Config
from danswer.db.engine import build_connection_string
from danswer.db.engine import get_session_with_tenant
from danswer.db.engine import get_sqlalchemy_engine
from danswer.db.models import UserTenantMapping
from danswer.utils.logger import setup_logger
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA

logger = setup_logger()


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


def ensure_schema_exists(tenant_id: str) -> bool:
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


# For now, we're implementing a primitive mapping between users and tenants.
# This function is only used to determine a user's relationship to a tenant upon creation (implying ownership).
def user_owns_a_tenant(email: str) -> bool:
    with get_session_with_tenant(POSTGRES_DEFAULT_SCHEMA) as db_session:
        result = (
            db_session.query(UserTenantMapping)
            .filter(UserTenantMapping.email == email)
            .first()
        )
        return result is not None


def add_users_to_tenant(emails: list[str], tenant_id: str) -> None:
    with get_session_with_tenant(POSTGRES_DEFAULT_SCHEMA) as db_session:
        try:
            for email in emails:
                db_session.add(UserTenantMapping(email=email, tenant_id=tenant_id))
        except Exception as e:
            logger.exception(f"Failed to add users to tenant {tenant_id}: {str(e)}")
        db_session.commit()


def remove_users_from_tenant(emails: list[str], tenant_id: str) -> None:
    with get_session_with_tenant(POSTGRES_DEFAULT_SCHEMA) as db_session:
        try:
            mappings_to_delete = (
                db_session.query(UserTenantMapping)
                .filter(
                    UserTenantMapping.email.in_(emails),
                    UserTenantMapping.tenant_id == tenant_id,
                )
                .all()
            )

            for mapping in mappings_to_delete:
                db_session.delete(mapping)

            db_session.commit()
        except Exception as e:
            logger.exception(
                f"Failed to remove users from tenant {tenant_id}: {str(e)}"
            )
            db_session.rollback()
