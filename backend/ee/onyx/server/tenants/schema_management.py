import hashlib
import logging
import os
import re
from types import SimpleNamespace

from sqlalchemy import text
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema
from sqlalchemy.schema import MetaData
from sqlalchemy.sql.elements import quoted_name

from alembic import command
from alembic.config import Config
from onyx.db.engine.sql_engine import build_connection_string
from onyx.db.engine.sql_engine import get_sqlalchemy_engine
from shared_configs.configs import TENANT_ID_PREFIX

logger = logging.getLogger(__name__)


def _get_current_alembic_head() -> str:
    """Return the head revision from the alembic migration scripts."""
    from alembic.script import ScriptDirectory

    current_dir = os.path.dirname(os.path.abspath(__file__))
    root_dir = os.path.abspath(os.path.join(current_dir, "..", "..", "..", ".."))
    alembic_cfg = Config(os.path.join(root_dir, "alembic.ini"))
    alembic_cfg.set_main_option("script_location", os.path.join(root_dir, "alembic"))
    script = ScriptDirectory.from_config(alembic_cfg)
    head = script.get_current_head()
    if head is None:
        raise RuntimeError("Could not determine alembic head revision")
    return head


# Regex pattern for valid tenant IDs:
# - UUID format: tenant_xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
# - AWS instance ID format: tenant_i-xxxxxxxxxxxxxxxxx
# Also useful for not accidentally dropping `public` schema
TENANT_ID_PATTERN = re.compile(
    rf"^{re.escape(TENANT_ID_PREFIX)}("
    r"[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}"  # UUID
    r"|i-[a-f0-9]+"  # AWS instance ID
    r")$"
)


def validate_tenant_id(tenant_id: str) -> bool:
    """Validate that tenant_id matches expected format.

    This is important for SQL injection prevention since schema names
    cannot be parameterized in SQL and must be formatted directly.
    """
    return bool(TENANT_ID_PATTERN.match(tenant_id))


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
        alembic_cfg.cmd_opts.x = [f"schemas={schema_name}"]  # type: ignore

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
    """Drop a tenant's schema.

    Uses strict regex validation to reject unexpected formats early,
    preventing SQL injection since schema names cannot be parameterized.
    """
    if not validate_tenant_id(tenant_id):
        raise ValueError(f"Invalid tenant_id format: {tenant_id}")

    with get_sqlalchemy_engine().connect() as connection:
        with connection.begin():
            # Use string formatting with validated tenant_id (safe after validation)
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{tenant_id}" CASCADE'))


def _deduplicate_ddl_names(
    metadata: MetaData,
) -> dict[str, str]:
    """Temporarily rename duplicate index/constraint names across tables.

    Some KG models share index and constraint names (a pre-existing model
    bug that works with Alembic because they're created in separate
    migrations). Returns a mapping of {new_name: original_name} for
    restoration.
    """
    seen: set[str] = set()
    renames: dict[str, str] = {}

    def _make_unique(original: str, table_name: str) -> str:
        # Use a short hash suffix to stay under PostgreSQL's 63-char limit
        suffix = hashlib.sha256(table_name.encode()).hexdigest()[:6]
        # Truncate the original name if needed to leave room for suffix
        max_base = 63 - 1 - len(suffix)  # 1 for underscore
        return f"{original[:max_base]}_{suffix}"

    for table in metadata.sorted_tables:
        # Deduplicate indexes
        for idx in list(table.indexes):
            if idx.name and idx.name in seen:
                original_name = idx.name
                new_name = _make_unique(original_name, table.name)
                idx.name = quoted_name(new_name, quote=False)
                renames[new_name] = original_name
            elif idx.name:
                seen.add(idx.name)

        # Deduplicate named constraints (UniqueConstraint, etc.)
        for constraint in list(table.constraints):
            name = getattr(constraint, "name", None)
            if name and name in seen:
                original_name = name
                new_name = _make_unique(original_name, table.name)
                constraint.name = new_name
                renames[new_name] = original_name
            elif name:
                seen.add(name)

    return renames


def _restore_ddl_names(metadata: MetaData, renames: dict[str, str]) -> None:
    """Restore original index/constraint names after create_all."""
    if not renames:
        return
    for table in metadata.sorted_tables:
        for idx in table.indexes:
            if idx.name in renames:
                idx.name = quoted_name(renames[idx.name], quote=False)
        for constraint in table.constraints:
            name = getattr(constraint, "name", None)
            if name and name in renames:
                constraint.name = renames[name]


def fast_provision_tenant_schema(tenant_id: str) -> None:
    """Create all tables via metadata.create_all() and seed default data.

    This is dramatically faster than running hundreds of sequential Alembic
    migrations (~80s → ~2s) and produces an identical schema since the
    models are the single source of truth for both paths.
    """
    from ee.onyx.server.tenants.seed_tenant_data import seed_tenant_defaults
    from onyx.db.models import Base

    engine = get_sqlalchemy_engine()
    head_rev = _get_current_alembic_head()

    logger.info(f"Fast-provisioning schema for tenant: {tenant_id}")

    # Temporarily deduplicate index names to avoid collisions during create_all
    renames = _deduplicate_ddl_names(Base.metadata)

    try:
        with engine.connect() as conn:
            # Create schema (already exists from create_schema_if_not_exists,
            # but be safe)
            conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{tenant_id}"'))
            conn.execute(text(f'SET search_path TO "{tenant_id}"'))

            # Create tenant-specific tables only.
            # Exclude: tables with explicit schema (e.g. public),
            # public-only tables without schema annotation, and tables
            # defined in models but never created by migrations.
            _PUBLIC_ONLY_TABLES = {
                "available_tenant",
                "tenant_anonymous_user_path",
                "milestone",
            }
            tenant_tables = [
                t
                for t in Base.metadata.sorted_tables
                if t.schema is None and t.name not in _PUBLIC_ONLY_TABLES
            ]
            Base.metadata.create_all(bind=conn, checkfirst=True, tables=tenant_tables)
            # Note: ResultModelBase (Celery) tables are NOT created per-tenant;
            # they only exist in the public/default schema.

            # Stamp the alembic_version table so future migrations work
            conn.execute(
                text(
                    "CREATE TABLE IF NOT EXISTS alembic_version "
                    "(version_num VARCHAR(32) NOT NULL)"
                )
            )
            conn.execute(
                text("INSERT INTO alembic_version (version_num) VALUES (:rev)"),
                {"rev": head_rev},
            )

            # Insert seed/default data
            seed_tenant_defaults(conn)

            conn.commit()
    finally:
        _restore_ddl_names(Base.metadata, renames)

    logger.info(
        f"Fast-provisioning complete for tenant {tenant_id} " f"(stamped at {head_rev})"
    )


def get_current_alembic_version(tenant_id: str) -> str:
    """Get the current Alembic version for a tenant."""
    from alembic.runtime.migration import MigrationContext
    from sqlalchemy import text

    engine = get_sqlalchemy_engine()

    # Set the search path to the tenant's schema
    with engine.connect() as connection:
        connection.execute(text(f'SET search_path TO "{tenant_id}"'))

        # Get the current version from the alembic_version table
        context = MigrationContext.configure(connection)
        current_rev = context.get_current_revision()

    return current_rev or "head"
