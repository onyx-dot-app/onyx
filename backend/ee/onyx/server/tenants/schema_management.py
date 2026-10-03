import functools
import logging
import os
import threading
from types import SimpleNamespace

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema

from ee.onyx.db.tenant_snapshot import (
    apply_snapshot,
    get_head_revision,
    get_snapshot,
    schema_has_tables,
)
from onyx.db.engine.shard_registry import (
    ALEMBIC_TARGET_URL_ATTRIBUTE,
    get_engine_for_shard,
    get_shard_spec,
)
from onyx.db.engine.shard_routing import get_engine_for_tenant, get_shard_for_tenant
from onyx.db.engine.sql_engine import build_connection_string
from onyx.db.engine.tenant_utils import validate_tenant_id

logger = logging.getLogger(__name__)


def _tenant_connection_string(tenant_id: str) -> str:
    """Alembic URL for the database holding this tenant's schema.

    For the default shard this is byte-identical to ``build_connection_string()``,
    since the default shard's spec is derived from the same POSTGRES_* settings.
    """
    spec = get_shard_spec(get_shard_for_tenant(tenant_id))
    return build_connection_string(
        user=spec.user,
        password=spec.password,
        host=spec.host,
        port=spec.port,
        db=spec.db,
    )


# Alembic's `op` and `context` are module-level proxies, so two upgrades in one
# process overwrite each other's state. Every worker runs tasks on a thread pool.
_ALEMBIC_RUN_LOCK = threading.Lock()


def _alembic_config() -> Config:
    """Alembic config for the tenant script directory, without logging setup."""
    current_dir = os.path.dirname(os.path.abspath(__file__))
    root_dir = os.path.abspath(os.path.join(current_dir, "..", "..", "..", ".."))
    alembic_cfg = Config(os.path.join(root_dir, "alembic.ini"))
    alembic_cfg.set_main_option("script_location", os.path.join(root_dir, "alembic"))
    # Ensure that logging isn't broken
    alembic_cfg.attributes["configure_logger"] = False
    return alembic_cfg


@functools.cache
def get_alembic_head_revision() -> str:
    """Revision the running code migrates a tenant to. Read from the script
    directory, so it needs no database and answers whether a pool tenant is
    current without running alembic."""
    head = ScriptDirectory.from_config(_alembic_config()).get_current_head()
    if head is None:
        raise RuntimeError("Alembic script directory has no head revision")
    return head


def run_alembic_migrations(schema_name: str) -> None:
    logger.info("Starting Alembic migrations for schema: %s", schema_name)

    try:
        alembic_cfg = _alembic_config()
        # Pin the run to the tenant's shard. Uses env.py's dedicated attribute rather
        # than `sqlalchemy.url`, which env.py ignores by design.
        alembic_cfg.attributes[ALEMBIC_TARGET_URL_ATTRIBUTE] = (
            _tenant_connection_string(schema_name)
        )

        # Mimic command-line options by adding 'cmd_opts' to the config
        alembic_cfg.cmd_opts = SimpleNamespace()  # ty: ignore[invalid-assignment]
        alembic_cfg.cmd_opts.x = [  # ty: ignore[invalid-assignment]
            f"schemas={schema_name}"
        ]

        # Run migrations programmatically
        with _ALEMBIC_RUN_LOCK:
            command.upgrade(alembic_cfg, "head")

        # Run migrations programmatically
        logger.info(
            "Alembic migrations completed successfully for schema: %s", schema_name
        )

    except Exception as e:
        logger.exception(
            "Alembic migration failed for schema %s: %s", schema_name, str(e)
        )
        raise


def build_tenant_schema(tenant_id: str) -> None:
    """Clone the shard's snapshot for the code's head into a new tenant, or run
    the migration chain when the shard has no snapshot at this head. A schema
    that already holds tables is a retried build, which only the chain can resume."""
    shard_name = get_shard_for_tenant(tenant_id)
    engine = get_engine_for_shard(shard_name)
    head = get_head_revision()
    dump = get_snapshot(shard_name, head) if head else None
    if dump is None or schema_has_tables(engine, tenant_id):
        logger.warning(
            "Migrating tenant %s through the chain (snapshot for %s on shard %s: %s)",
            tenant_id,
            head,
            shard_name,
            "present" if dump else "missing",
        )
        run_alembic_migrations(tenant_id)
        return
    apply_snapshot(engine, dump, tenant_id)
    logger.info(
        "Cloned tenant %s from the shard %s snapshot at %s", tenant_id, shard_name, head
    )


def create_schema_if_not_exists(tenant_id: str) -> bool:
    with Session(get_engine_for_tenant(tenant_id)) as db_session:
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

    with get_engine_for_tenant(tenant_id).connect() as connection:
        with connection.begin():
            # Use string formatting with validated tenant_id (safe after validation)
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{tenant_id}" CASCADE'))


def get_current_alembic_version(tenant_id: str) -> str:
    """Get the current Alembic version for a tenant."""
    from alembic.runtime.migration import MigrationContext
    from sqlalchemy import text

    engine = get_engine_for_tenant(tenant_id)

    # Set the search path to the tenant's schema
    with engine.connect() as connection:
        connection.execute(text(f'SET search_path TO "{tenant_id}"'))

        # Get the current version from the alembic_version table
        context = MigrationContext.configure(connection)
        current_rev = context.get_current_revision()

    return current_rev or "head"
