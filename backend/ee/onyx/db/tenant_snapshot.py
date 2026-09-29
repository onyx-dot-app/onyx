"""Snapshot of a migrated tenant schema, cloned into new tenants.

The rollout job keeps one template schema per shard at head, dumps it after the
migration run, and stores the dump keyed by revision. Rendering the dump with a
new tenant's name and applying it yields exactly what an empty schema becomes
after the whole migration chain, baseline rows included, in about a second.
"""

import os
import re
import subprocess
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from difflib import unified_diff
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from psycopg2 import sql
from sqlalchemy import bindparam, delete, select, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.schema import CreateSchema, DropSchema

from onyx.configs.app_configs import DB_READONLY_USER
from onyx.db.engine.shard_registry import (
    get_engine_for_shard,
    get_shard_spec,
    get_shard_specs,
)
from onyx.db.engine.sql_engine import build_connection_string, get_catalog_session
from onyx.db.engine.tenant_utils import validate_tenant_id
from onyx.db.models import TenantSchemaSnapshot
from onyx.utils.logger import setup_logger
from shared_configs.configs import TENANT_ID_PREFIX, TENANT_TEMPLATE_SCHEMA

logger = setup_logger()


def _schema_name_pattern(schema: str) -> re.Pattern[str]:
    """The name as an identifier, quoted or bare, never as part of a longer word."""
    return re.compile(rf'(?<!\w)"?{re.escape(schema)}"?(?!\w)')


# The image being replaced keeps its own snapshot until the rollout completes.
_SNAPSHOTS_KEPT_PER_SHARD = 2
# The dump names the template everywhere, including inside trigger function bodies,
# so rendering is one identifier swap. pg_dump leaves the plain template name bare
# but a real tenant name needs quoting, so every occurrence is rendered quoted.
_TEMPLATE_NAME = _schema_name_pattern(TENANT_TEMPLATE_SCHEMA)
# Dropped from the dump: the schema line (the caller owns the target schema),
# psql meta-commands, and session settings, which vary by pg_dump version and
# have no place inside a tenant build.
_DRIVER_UNSAFE_LINES = re.compile(
    r"^(CREATE SCHEMA .*;|\\(un)?restrict .*|SET \w+ = .*;|SELECT pg_catalog\.set_config\(.*\);)$",
    re.MULTILINE,
)
_DRIVER_TAG = re.compile(r"^postgresql\+\w+://")
# Values that legitimately differ between a clone and a fresh migration: row
# timestamps, encrypted blobs (a random salt per write) and generated ids.
_UNCOMPARED_COLUMN_TYPES = (
    "timestamp without time zone",
    "timestamp with time zone",
    "bytea",
    "uuid",
)
_DIFF_LINES_REPORTED = 60
# Postgres deparses a varchar list in a CHECK or partial index either as an array
# of casts or as a cast of an array, flipping form on every re-parse. Same
# constraint, so both spellings compare as one.
_ARRAY_OF_CASTS = re.compile(
    r"ARRAY\[((?:\('[^']*'::character varying\)::text(?:, )?)+)\]"
)
_CAST_OF_ARRAY = re.compile(
    r"\(ARRAY\[((?:'[^']*'::character varying(?:, )?)+)\]\)::text\[\]"
)
_QUOTED_LITERAL = re.compile(r"'[^']*'")
# Where alembic.ini lives: the alembic subprocess and the head lookup run from here.
_BACKEND_DIR = Path(__file__).resolve().parents[3]


def get_head_revision() -> str | None:
    config = Config(str(_BACKEND_DIR / "alembic.ini"))
    # The ini names the scripts folder relative to the working directory.
    config.set_main_option("script_location", str(_BACKEND_DIR / "alembic"))
    return ScriptDirectory.from_config(config).get_current_head()


def ensure_template_schema(shard_name: str) -> None:
    """The template joins the next migration run once it exists."""
    with get_engine_for_shard(shard_name).begin() as connection:
        connection.execute(CreateSchema(TENANT_TEMPLATE_SCHEMA, if_not_exists=True))


def dump_schema(shard_name: str, schema: str, schema_only: bool = False) -> str:
    """pg_dump of one schema as plain SQL a driver can execute in one go.

    Rows come out as INSERTs rather than COPY blocks for that reason."""
    if not validate_tenant_id(schema):
        raise ValueError(f"Refusing to dump schema {schema!r}")
    spec = get_shard_spec(shard_name)
    # libpq takes the same URL the engine uses, minus the SQLAlchemy driver tag.
    url = build_connection_string(
        user=spec.user,
        password=spec.password,
        host=spec.host,
        port=spec.port,
        db=spec.db,
    )
    url = _DRIVER_TAG.sub("postgresql://", url, count=1)
    command = [
        "pg_dump",
        "--schema",
        schema,
        "--no-owner",
        "--no-privileges",
        "--no-comments",
        "--no-tablespaces",
        "--no-security-labels",
        "--inserts",
        "--dbname",
        url,
    ]
    if schema_only:
        command.append("--schema-only")
    result = subprocess.run(
        command, env=os.environ, capture_output=True, text=True, check=True
    )
    return _DRIVER_UNSAFE_LINES.sub("", result.stdout)


def store_template_snapshots(alembic_revision: str) -> None:
    """Dump each shard's template once per revision. Runs after every migration
    run, so the first rollout after a code change fills the gap."""
    for shard_name in sorted(get_shard_specs()):
        if get_snapshot(shard_name, alembic_revision) is not None:
            continue
        dump = dump_schema(shard_name, TENANT_TEMPLATE_SCHEMA)
        store_snapshot(shard_name, alembic_revision, dump)
        logger.info(
            "Stored template snapshot for shard %s at %s (%d bytes)",
            shard_name,
            alembic_revision,
            len(dump),
        )


def store_snapshot(shard_name: str, alembic_revision: str, dump: str) -> None:
    """Upsert the shard's snapshot for this revision and drop all but the newest."""
    with get_catalog_session() as db_session:
        existing = db_session.scalar(
            select(TenantSchemaSnapshot).where(
                TenantSchemaSnapshot.shard_name == shard_name,
                TenantSchemaSnapshot.alembic_revision == alembic_revision,
            )
        )
        if existing is None:
            db_session.add(
                TenantSchemaSnapshot(
                    shard_name=shard_name,
                    alembic_revision=alembic_revision,
                    dump=dump,
                )
            )
        else:
            existing.dump = dump
        db_session.flush()

        keep = db_session.scalars(
            select(TenantSchemaSnapshot.id)
            .where(TenantSchemaSnapshot.shard_name == shard_name)
            .order_by(TenantSchemaSnapshot.created_at.desc())
            .limit(_SNAPSHOTS_KEPT_PER_SHARD)
        ).all()
        db_session.execute(
            delete(TenantSchemaSnapshot).where(
                TenantSchemaSnapshot.shard_name == shard_name,
                TenantSchemaSnapshot.id.not_in(keep),
            )
        )
        db_session.commit()


def get_snapshot(shard_name: str, alembic_revision: str) -> str | None:
    with get_catalog_session() as db_session:
        return db_session.scalar(
            select(TenantSchemaSnapshot.dump).where(
                TenantSchemaSnapshot.shard_name == shard_name,
                TenantSchemaSnapshot.alembic_revision == alembic_revision,
            )
        )


def render_snapshot(dump: str, tenant_id: str) -> str:
    if not validate_tenant_id(tenant_id) or tenant_id == TENANT_TEMPLATE_SCHEMA:
        raise ValueError(f"Refusing to render a snapshot for {tenant_id!r}")
    return _TEMPLATE_NAME.sub(f'"{tenant_id}"', dump)


def apply_snapshot(engine: Engine, dump: str, tenant_id: str) -> None:
    """Build the tenant schema from the dump in one transaction.

    The dump carries the alembic version row, so the result is already stamped
    at the snapshot's revision. Migration grants schema usage to the read-only
    role, which a dump does not carry, so it is granted here."""
    rendered = render_snapshot(dump, tenant_id)
    with engine.connect() as connection:
        with connection.begin():
            connection.execute(CreateSchema(tenant_id, if_not_exists=True))
            _execute_verbatim(connection, rendered)
            _grant_readonly_usage(connection, tenant_id)
        # pg_dump's session settings (search_path among them) would otherwise
        # ride along on this pooled connection.
        connection.invalidate()


def _execute_verbatim(connection: Connection, statements: str) -> None:
    """Straight to the driver cursor with no parameters: the dump and the grant
    contain literal % signs that parameter interpolation would try to expand."""
    cursor = connection.connection.cursor()
    try:
        cursor.execute(statements)
    finally:
        cursor.close()


def _grant_readonly_usage(connection: Connection, tenant_id: str) -> None:
    # Both names are validated identifiers, as in the migration that grants this.
    _execute_verbatim(
        connection,
        f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = '{DB_READONLY_USER}') THEN
                EXECUTE format('GRANT USAGE ON SCHEMA %I TO %I', '{tenant_id}', '{DB_READONLY_USER}');
            END IF;
        END
        $$;
        """,
    )


def check_snapshot_parity(shard_name: str, dump: str) -> list[str]:
    """Differences between a clone of the dump and a freshly migrated schema.

    Empty means the snapshot is safe to clone. Both scratch schemas are dropped."""
    engine = get_engine_for_shard(shard_name)
    cloned = f"{TENANT_ID_PREFIX}{uuid.uuid4()}"
    migrated = f"{TENANT_ID_PREFIX}{uuid.uuid4()}"
    with _dropped_afterwards(engine, cloned, migrated):
        apply_snapshot(engine, dump, cloned)
        _migrate_empty_schema(shard_name, migrated)
        return compare_schemas(shard_name, cloned, migrated)


def compare_schemas(shard_name: str, left: str, right: str) -> list[str]:
    """Structure must match byte for byte once the names are normalised. Rows
    must match in count and, outside the uncompared column types, in content."""
    differences = _structure_differences(shard_name, left, right)
    with get_engine_for_shard(shard_name).connect() as connection:
        differences.extend(_row_differences(connection, left, right))
    return differences


def _structure_differences(shard_name: str, left: str, right: str) -> list[str]:
    left_lines = _normalised_structure(dump_schema(shard_name, left, True), left)
    right_lines = _normalised_structure(dump_schema(shard_name, right, True), right)
    diff = list(
        unified_diff(left_lines, right_lines, fromfile=left, tofile=right, lineterm="")
    )
    if not diff:
        return []
    return ["structure differs:"] + diff[:_DIFF_LINES_REPORTED]


def _normalised_structure(dump: str, schema: str) -> list[str]:
    body = _schema_name_pattern(schema).sub("SCHEMA", dump)
    return [
        _canonical_text_arrays(line)
        for line in body.splitlines()
        if line.strip() and not line.startswith("--")
    ]


def _canonical_text_arrays(line: str) -> str:
    def literals_only(match: re.Match[str]) -> str:
        return "ARRAY[" + ", ".join(_QUOTED_LITERAL.findall(match.group(1))) + "]"

    return _CAST_OF_ARRAY.sub(literals_only, _ARRAY_OF_CASTS.sub(literals_only, line))


def _row_differences(connection: Connection, left: str, right: str) -> list[str]:
    differences: list[str] = []
    for table in _tables(connection, left):
        columns = _compared_columns(connection, left, table)
        left_count, left_digest = _row_digest(connection, left, table, columns)
        right_count, right_digest = _row_digest(connection, right, table, columns)
        if left_count != right_count:
            differences.append(
                f"{table}: {left_count} rows in {left}, {right_count} in {right}"
            )
        elif left_digest != right_digest:
            differences.append(f"{table}: row contents differ")
    return differences


def _tables(connection: Connection, schema: str) -> list[str]:
    return list(
        connection.scalars(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = :schema AND table_type = 'BASE TABLE' "
                "ORDER BY table_name"
            ),
            {"schema": schema},
        )
    )


def _compared_columns(connection: Connection, schema: str, table: str) -> list[str]:
    return list(
        connection.scalars(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = :schema AND table_name = :table "
                "AND is_generated = 'NEVER' AND data_type NOT IN :skipped "
                "ORDER BY ordinal_position"
            ).bindparams(bindparam("skipped", expanding=True)),
            {
                "schema": schema,
                "table": table,
                "skipped": list(_UNCOMPARED_COLUMN_TYPES),
            },
        )
    )


def _row_digest(
    connection: Connection, schema: str, table: str, columns: list[str]
) -> tuple[int, str]:
    source = sql.Identifier(schema, table)
    if not columns:
        query = sql.SQL("SELECT count(*) FROM {}").format(source)
    else:
        row_text = sql.SQL(", ").join(
            sql.SQL("{}::text").format(sql.Identifier(column)) for column in columns
        )
        query = sql.SQL(
            "SELECT count(*), "
            "md5(coalesce(string_agg(row_text, '|' ORDER BY row_text), '')) "
            "FROM (SELECT concat_ws(',', {}) AS row_text FROM {}) rows"
        ).format(row_text, source)
    row = connection.exec_driver_sql(
        query.as_string(connection.connection.dbapi_connection)
    ).one()
    return int(row[0]), "" if not columns else str(row[1])


def _migrate_empty_schema(shard_name: str, schema: str) -> None:
    """Run the migration chain against a new schema, the way the rollout job does."""
    result = subprocess.run(
        [
            "alembic",
            "-x",
            f"schemas={schema}",
            "-x",
            f"shard={shard_name}",
            "upgrade",
            "head",
        ],
        cwd=_BACKEND_DIR,
        env=os.environ,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Migrating {schema} for the parity check failed:\n{result.stdout}"
        )


@contextmanager
def _dropped_afterwards(engine: Engine, *schemas: str) -> Iterator[None]:
    try:
        yield
    finally:
        with engine.begin() as connection:
            for schema in schemas:
                connection.execute(DropSchema(schema, cascade=True, if_exists=True))
