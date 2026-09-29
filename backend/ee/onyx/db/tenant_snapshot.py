"""Snapshot of a migrated tenant schema, cloned into new tenants.

The rollout job keeps one template schema per shard at head, dumps it after the
migration run, and stores the dump keyed by revision. Rendering the dump with a
new tenant's name and applying it yields what an empty schema becomes after the
whole migration chain, baseline rows included.
"""

import os
import re
import shutil
import subprocess
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from difflib import unified_diff
from pathlib import Path
from urllib.parse import unquote_plus

from alembic.config import Config
from alembic.script import ScriptDirectory
from psycopg2 import sql
from sqlalchemy import bindparam, delete, func, select, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.schema import CreateSchema, DropSchema

from onyx.configs.app_configs import AWS_REGION_NAME, DB_READONLY_USER, USE_IAM_AUTH
from onyx.configs.constants import SSL_CERT_FILE
from onyx.db.engine.iam_auth import get_iam_auth_token
from onyx.db.engine.pg_ssl import pg_ssl_psycopg2_connect_args
from onyx.db.engine.shard_registry import (
    get_engine_for_shard,
    get_shard_spec,
    get_shard_specs,
)
from onyx.db.engine.sql_engine import get_catalog_session
from onyx.db.engine.tenant_utils import validate_tenant_id
from onyx.db.models import TenantSchemaSnapshot
from onyx.utils.logger import setup_logger
from shared_configs.configs import TENANT_TEMPLATE_SCHEMA

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
# libpq reads these instead of a URL, so the password never appears in argv.
_LIBPQ_SSL_ENV = {
    "sslmode": "PGSSLMODE",
    "sslrootcert": "PGSSLROOTCERT",
    "sslcert": "PGSSLCERT",
    "sslkey": "PGSSLKEY",
}
# Values that legitimately differ between a clone and a fresh migration: row
# timestamps, encrypted blobs (a random salt per write) and generated ids.
_UNCOMPARED_COLUMN_TYPES = (
    "timestamp without time zone",
    "timestamp with time zone",
    "bytea",
    "uuid",
)
_DIFF_LINES_REPORTED = 60
# Seeded rows with one JSON field set to the migration's run date, so clone and
# fresh schema differ by day. Only that field is dropped before comparing.
# Table to (key column, key value, JSON column, dated field).
_RUN_DATE_SEEDED_FIELDS = {
    "key_value_store": ("key", "kg_config", "value", "KG_COVERAGE_START")
}
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


def scratch_schema_name() -> str:
    """A short-lived schema the parity check builds and drops. The name passes the
    tenant validator but no scheduler treats it as a workspace."""
    return f"{TENANT_TEMPLATE_SCHEMA}_{uuid.uuid4().hex}"


def ensure_template_schema(shard_name: str) -> None:
    """Created before enumeration so the template is migrated in this run."""
    with get_engine_for_shard(shard_name).begin() as connection:
        connection.execute(CreateSchema(TENANT_TEMPLATE_SCHEMA, if_not_exists=True))


def dump_schema(shard_name: str, schema: str, schema_only: bool = False) -> str:
    """pg_dump of one schema as plain SQL a driver can execute in one go.

    Rows come out as INSERTs rather than COPY blocks for that reason."""
    if not validate_tenant_id(schema):
        raise ValueError(f"Refusing to dump schema {schema!r}")
    if shutil.which("pg_dump") is None:
        raise RuntimeError("pg_dump is not installed, run from an image that has it")
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
    ]
    if schema_only:
        command.append("--schema-only")
    result = subprocess.run(
        command,
        env={**os.environ, **_libpq_env(shard_name)},
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"pg_dump of {schema} failed: {result.stderr.strip()}")
    return _DRIVER_UNSAFE_LINES.sub("", result.stdout)


def _libpq_env(shard_name: str) -> dict[str, str]:
    """The shard's connection as libpq variables, with the same auth and TLS
    settings the engine uses for that shard."""
    spec = get_shard_spec(shard_name)
    # The spec carries the URL-encoded form the engine embeds in its URL.
    env = {
        "PGHOST": spec.host,
        "PGPORT": spec.port,
        "PGUSER": spec.user,
        "PGDATABASE": spec.db,
        "PGPASSWORD": unquote_plus(spec.password),
    }
    if USE_IAM_AUTH:
        # Same token and TLS the engine's IAM connect handler applies.
        env["PGPASSWORD"] = get_iam_auth_token(
            spec.host, spec.port, spec.user, AWS_REGION_NAME
        )
        env["PGSSLMODE"] = "require"
        env["PGSSLROOTCERT"] = SSL_CERT_FILE
        return env
    ssl_args = pg_ssl_psycopg2_connect_args()
    if "sslpassword" in ssl_args:
        # libpq has no variable for it and argv would expose it.
        raise RuntimeError("pg_dump cannot use a passphrase-protected client key")
    for arg, variable in _LIBPQ_SSL_ENV.items():
        value = ssl_args.get(arg)
        if value:
            env[variable] = value
    return env


def store_template_snapshots(alembic_revision: str) -> None:
    """Dump every shard's template after a migration run. A fresh dump each run
    keeps re-encrypted rows current and marks the running head as the newest."""
    for shard_name in sorted(get_shard_specs()):
        _require_template_at(shard_name, alembic_revision)
        dump = dump_schema(shard_name, TENANT_TEMPLATE_SCHEMA)
        store_snapshot(shard_name, alembic_revision, dump)
        logger.info(
            "Stored template snapshot for shard %s at %s (%d bytes)",
            shard_name,
            alembic_revision,
            len(dump),
        )


def _require_template_at(shard_name: str, alembic_revision: str) -> None:
    query = sql.SQL("SELECT version_num FROM {}").format(
        sql.Identifier(TENANT_TEMPLATE_SCHEMA, "alembic_version")
    )
    with get_engine_for_shard(shard_name).connect() as connection:
        stamped = connection.exec_driver_sql(
            query.as_string(connection.connection.dbapi_connection)
        ).scalar()
    if stamped != alembic_revision:
        raise RuntimeError(
            f"Template on shard {shard_name} is at {stamped}, not {alembic_revision}"
        )


def store_snapshot(shard_name: str, alembic_revision: str, dump: str) -> None:
    """Upsert the shard's snapshot for this revision as the newest, and drop all
    but the newest two."""
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
            # A rollback re-stores an older revision, which must then outlive
            # the one it replaced.
            existing.created_at = func.now()
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
    """Build the tenant schema from the dump in one transaction, stamped at the
    snapshot's revision by the version row the dump carries. Migration grants
    schema usage to the read-only role, which a dump lacks, so it is granted here."""
    rendered = render_snapshot(dump, tenant_id)
    with engine.connect() as connection:
        with connection.begin():
            connection.execute(CreateSchema(tenant_id, if_not_exists=True))
            _execute_verbatim(connection, rendered)
            _grant_readonly_usage(connection, tenant_id)
        # Defensive: a session setting the strip regex let through would
        # otherwise stay on this pooled connection.
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
    # tenant_id was validated in render_snapshot. The role name is trusted
    # config, interpolated the way the migration that grants this does.
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
    cloned = scratch_schema_name()
    migrated = scratch_schema_name()
    with _dropped_afterwards(engine, cloned, migrated):
        apply_snapshot(engine, dump, cloned)
        _migrate_empty_schema(shard_name, migrated)
        return compare_schemas(shard_name, cloned, migrated)


def compare_schemas(shard_name: str, left: str, right: str) -> list[str]:
    """Structure must match line for line after name, comment and array-cast
    normalisation. Rows must match in count and, outside the uncompared column
    types, in content."""
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
        # ROW keeps NULL positions, so a NULL moving between columns still differs.
        row_text = sql.SQL("ROW({})::text").format(
            sql.SQL(", ").join(_compared_value(table, column) for column in columns)
        )
        query = sql.SQL(
            "SELECT count(*), "
            "md5(coalesce(string_agg(row_text, '|' ORDER BY row_text), '')) "
            "FROM (SELECT {} AS row_text FROM {}) rows"
        ).format(row_text, source)
    row = connection.exec_driver_sql(
        query.as_string(connection.connection.dbapi_connection)
    ).one()
    return int(row[0]), "" if not columns else str(row[1])


def _compared_value(table: str, column: str) -> sql.Composable:
    seeded = _RUN_DATE_SEEDED_FIELDS.get(table)
    if seeded is None or column != seeded[2]:
        return sql.Identifier(column)
    key_column, key_value, json_column, dated_field = seeded
    return sql.SQL("CASE WHEN {} = {} THEN {} - {} ELSE {} END").format(
        sql.Identifier(key_column),
        sql.Literal(key_value),
        sql.Identifier(json_column),
        sql.Literal(dated_field),
        sql.Identifier(json_column),
    )


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
