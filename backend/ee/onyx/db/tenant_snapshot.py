"""Snapshot of a migrated tenant schema, cloned into new tenants.

The rollout job keeps one template schema per shard at head, dumps it after the
migration run, and stores the dump keyed by revision. Rendering the dump with a
new tenant's name and applying it yields what an empty schema becomes after the
whole migration chain, baseline rows included.
"""

import functools
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
from sqlalchemy import (
    DateTime,
    LargeBinary,
    Text,
    Uuid,
    and_,
    bindparam,
    case,
    cast,
    column,
    delete,
    func,
    inspect,
    literal,
    select,
    table,
    tuple_,
)
from sqlalchemy.dialects.postgresql import aggregate_order_by
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import Session
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
_UNCOMPARED_COLUMN_TYPES = (DateTime, LargeBinary, Uuid)
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

# The catalog tables the structure comparison reads.
_PG_CATALOG = "pg_catalog"
_pg_namespace = table(
    "pg_namespace", column("oid"), column("nspname"), schema=_PG_CATALOG
)
_pg_class = table(
    "pg_class",
    column("oid"),
    column("relname"),
    column("relnamespace"),
    column("relkind"),
    column("relpersistence"),
    column("relreplident"),
    column("relrowsecurity"),
    column("relforcerowsecurity"),
    column("reloptions"),
    column("relpartbound"),
    schema=_PG_CATALOG,
)
_pg_policies = table(
    "pg_policies",
    column("schemaname"),
    column("tablename"),
    column("policyname"),
    column("permissive"),
    column("roles"),
    column("cmd"),
    column("qual"),
    column("with_check"),
    schema=_PG_CATALOG,
)
_pg_attribute = table(
    "pg_attribute",
    column("attrelid"),
    column("attnum"),
    column("attname"),
    column("atttypid"),
    column("atttypmod"),
    column("attnotnull"),
    column("attidentity"),
    column("attgenerated"),
    column("attisdropped"),
    schema=_PG_CATALOG,
)
_pg_attrdef = table(
    "pg_attrdef",
    column("adrelid"),
    column("adnum"),
    column("adbin"),
    schema=_PG_CATALOG,
)
_pg_constraint = table(
    "pg_constraint",
    column("oid"),
    column("conname"),
    column("connamespace"),
    column("conrelid"),
    schema=_PG_CATALOG,
)
_pg_index = table(
    "pg_index",
    column("indexrelid"),
    column("indrelid"),
    column("indisvalid"),
    schema=_PG_CATALOG,
)
_pg_proc = table(
    "pg_proc",
    column("oid"),
    column("proname"),
    column("pronamespace"),
    column("prokind"),
    schema=_PG_CATALOG,
)
_pg_trigger = table(
    "pg_trigger",
    column("oid"),
    column("tgname"),
    column("tgrelid"),
    column("tgisinternal"),
    column("tgenabled"),
    schema=_PG_CATALOG,
)
_pg_type = table(
    "pg_type",
    column("oid"),
    column("typname"),
    column("typnamespace"),
    column("typtype"),
    column("typbasetype"),
    column("typtypmod"),
    column("typnotnull"),
    column("typdefault"),
    schema=_PG_CATALOG,
)
_pg_range = table(
    "pg_range", column("rngtypid"), column("rngsubtype"), schema=_PG_CATALOG
)
_pg_enum = table(
    "pg_enum",
    column("enumtypid"),
    column("enumlabel"),
    column("enumsortorder"),
    schema=_PG_CATALOG,
)
_pg_sequences = table(
    "pg_sequences",
    column("schemaname"),
    column("sequencename"),
    column("data_type"),
    column("start_value"),
    column("min_value"),
    column("max_value"),
    column("increment_by"),
    column("cycle"),
    column("cache_size"),
    schema=_PG_CATALOG,
)
_pg_depend = table(
    "pg_depend",
    column("objid"),
    column("refobjid"),
    column("refobjsubid"),
    column("deptype"),
    schema=_PG_CATALOG,
)
_schema_oid = (
    select(_pg_namespace.c.oid)
    .where(_pg_namespace.c.nspname == bindparam("schema"))
    .scalar_subquery()
)
_in_schema = _pg_class.c.relnamespace == _schema_oid
# relkind is a "char". The text form compares and sorts like any string.
_relkind = cast(_pg_class.c.relkind, Text)
_sequence_owner = _pg_class.alias("sequence_owner")
_owned_sequence = _pg_class.alias("owned_sequence")
# What Onyx schemas hold, each as one line of text. Any relation the other
# queries do not break down still shows up here by kind and name.
# Rows are ordered by name within each kind. Columns keep their table order.
_STRUCTURE_QUERIES = (
    select(
        literal("relation"),
        _relkind,
        _pg_class.c.relname,
        cast(_pg_class.c.relpersistence, Text),
        cast(_pg_class.c.relreplident, Text),
        _pg_class.c.relrowsecurity,
        _pg_class.c.relforcerowsecurity,
        # Storage options, and a view's security_invoker and barrier settings.
        _pg_class.c.reloptions,
        func.pg_get_partkeydef(_pg_class.c.oid),
        func.pg_get_expr(_pg_class.c.relpartbound, _pg_class.c.oid),
        case(
            (_relkind.in_(["v", "m"]), func.pg_get_viewdef(_pg_class.c.oid)),
            else_=literal(""),
        ),
    )
    .where(_in_schema, _relkind != "i")
    .order_by(_relkind, _pg_class.c.relname),
    select(
        literal("policy"),
        _pg_policies.c.tablename,
        _pg_policies.c.policyname,
        _pg_policies.c.permissive,
        _pg_policies.c.roles,
        _pg_policies.c.cmd,
        _pg_policies.c.qual,
        _pg_policies.c.with_check,
    )
    .where(_pg_policies.c.schemaname == bindparam("schema"))
    .order_by(_pg_policies.c.tablename, _pg_policies.c.policyname),
    select(
        literal("column"),
        _pg_class.c.relname,
        _pg_attribute.c.attname,
        func.format_type(_pg_attribute.c.atttypid, _pg_attribute.c.atttypmod),
        _pg_attribute.c.attnotnull,
        cast(_pg_attribute.c.attidentity, Text),
        cast(_pg_attribute.c.attgenerated, Text),
        func.pg_get_expr(_pg_attrdef.c.adbin, _pg_attrdef.c.adrelid),
    )
    .select_from(
        _pg_attribute.join(
            _pg_class, _pg_class.c.oid == _pg_attribute.c.attrelid
        ).outerjoin(
            _pg_attrdef,
            and_(
                _pg_attrdef.c.adrelid == _pg_attribute.c.attrelid,
                _pg_attrdef.c.adnum == _pg_attribute.c.attnum,
            ),
        )
    )
    .where(
        _in_schema,
        _relkind != "i",
        _pg_attribute.c.attnum > 0,
        _pg_attribute.c.attisdropped.is_(False),
    )
    .order_by(_pg_class.c.relname, _pg_attribute.c.attnum),
    select(
        literal("constraint"),
        _pg_class.c.relname,
        _pg_constraint.c.conname,
        func.pg_get_constraintdef(_pg_constraint.c.oid),
    )
    # Outer join: a domain's constraint has no table.
    .select_from(
        _pg_constraint.outerjoin(
            _pg_class, _pg_class.c.oid == _pg_constraint.c.conrelid
        )
    )
    .where(_pg_constraint.c.connamespace == _schema_oid)
    .order_by(_pg_class.c.relname, _pg_constraint.c.conname),
    select(
        literal("index"),
        _pg_class.c.relname,
        _pg_index.c.indisvalid,
        func.pg_get_indexdef(_pg_index.c.indexrelid),
    )
    .select_from(_pg_index.join(_pg_class, _pg_class.c.oid == _pg_index.c.indexrelid))
    .where(_in_schema)
    .order_by(_pg_class.c.relname),
    select(
        literal("sequence"),
        _pg_sequences.c.sequencename,
        _pg_sequences.c.data_type,
        _pg_sequences.c.start_value,
        _pg_sequences.c.min_value,
        _pg_sequences.c.max_value,
        _pg_sequences.c.increment_by,
        _pg_sequences.c.cycle,
        _pg_sequences.c.cache_size,
    )
    .where(_pg_sequences.c.schemaname == bindparam("schema"))
    .order_by(_pg_sequences.c.sequencename),
    select(
        literal("sequence owner"),
        _owned_sequence.c.relname,
        _sequence_owner.c.relname,
        _pg_attribute.c.attname,
    )
    .select_from(
        _pg_depend.join(_owned_sequence, _owned_sequence.c.oid == _pg_depend.c.objid)
        .join(_sequence_owner, _sequence_owner.c.oid == _pg_depend.c.refobjid)
        .join(
            _pg_attribute,
            and_(
                _pg_attribute.c.attrelid == _pg_depend.c.refobjid,
                _pg_attribute.c.attnum == _pg_depend.c.refobjsubid,
            ),
        )
    )
    .where(
        _owned_sequence.c.relnamespace == _schema_oid,
        cast(_owned_sequence.c.relkind, Text) == "S",
        cast(_pg_depend.c.deptype, Text) == "a",
    )
    .order_by(_owned_sequence.c.relname),
    select(
        literal("function"),
        cast(_pg_proc.c.prokind, Text),
        _pg_proc.c.proname,
        func.pg_get_function_identity_arguments(_pg_proc.c.oid),
        func.pg_get_function_result(_pg_proc.c.oid),
        # pg_get_functiondef cannot render an aggregate, so one is compared by
        # its signature alone.
        case(
            (
                cast(_pg_proc.c.prokind, Text) != "a",
                func.pg_get_functiondef(_pg_proc.c.oid),
            ),
            else_=literal(""),
        ),
    )
    .where(_pg_proc.c.pronamespace == _schema_oid)
    .order_by(
        _pg_proc.c.proname, func.pg_get_function_identity_arguments(_pg_proc.c.oid)
    ),
    select(
        literal("trigger"),
        _pg_class.c.relname,
        _pg_trigger.c.tgname,
        cast(_pg_trigger.c.tgenabled, Text),
        func.pg_get_triggerdef(_pg_trigger.c.oid),
    )
    .select_from(_pg_trigger.join(_pg_class, _pg_class.c.oid == _pg_trigger.c.tgrelid))
    .where(_in_schema, _pg_trigger.c.tgisinternal.is_(False))
    .order_by(_pg_class.c.relname, _pg_trigger.c.tgname),
    select(
        literal("type"),
        cast(_pg_type.c.typtype, Text),
        _pg_type.c.typname,
        # Domain: base type, nullability, default. Range: subtype. Enum: labels.
        func.format_type(_pg_type.c.typbasetype, _pg_type.c.typtypmod),
        _pg_type.c.typnotnull,
        _pg_type.c.typdefault,
        select(func.format_type(_pg_range.c.rngsubtype, None))
        .where(_pg_range.c.rngtypid == _pg_type.c.oid)
        .scalar_subquery(),
        select(
            func.string_agg(
                _pg_enum.c.enumlabel,
                aggregate_order_by(literal(","), _pg_enum.c.enumsortorder),
            )
        )
        .where(_pg_enum.c.enumtypid == _pg_type.c.oid)
        .scalar_subquery(),
    )
    .where(
        _pg_type.c.typnamespace == _schema_oid,
        # Enums, domains and ranges. A composite type is a relation, listed above.
        cast(_pg_type.c.typtype, Text).in_(["e", "d", "r"]),
    )
    .order_by(_pg_type.c.typname),
)


@functools.cache
def get_head_revision() -> str | None:
    """Head of the tenant chain, fixed for the life of the process."""
    config = Config(str(_BACKEND_DIR / "alembic.ini"))
    # The ini names the scripts folder relative to the working directory.
    config.set_main_option("script_location", str(_BACKEND_DIR / "alembic"))
    return ScriptDirectory.from_config(config).get_current_head()


def schema_has_tables(engine: Engine, schema: str) -> bool:
    return bool(inspect(engine).get_table_names(schema=schema))


def scratch_schema_name() -> str:
    """A short-lived schema the parity check builds and drops. The name passes the
    tenant validator but no scheduler treats it as a workspace."""
    return f"{TENANT_TEMPLATE_SCHEMA}_{uuid.uuid4().hex}"


@contextmanager
def template_session(shard_name: str) -> Iterator[Session]:
    """Session on one shard's template. Tenant routing cannot reach it, since
    every shard holds a template under the same name."""
    with (
        get_engine_for_shard(shard_name)
        .connect()
        .execution_options(
            schema_translate_map={None: TENANT_TEMPLATE_SCHEMA}
        ) as connection
    ):
        session = Session(bind=connection, expire_on_commit=False)
        try:
            yield session
        finally:
            session.close()


def ensure_template_schema(shard_name: str) -> None:
    """Created before enumeration so the template is migrated in this run."""
    with get_engine_for_shard(shard_name).begin() as connection:
        connection.execute(CreateSchema(TENANT_TEMPLATE_SCHEMA, if_not_exists=True))


def dump_schema(shard_name: str, schema: str) -> str:
    """pg_dump of one schema as plain SQL a driver can execute in one go.

    Rows come out as INSERTs rather than COPY blocks for that reason. pg_dump reads
    the whole catalog before it filters to the schema, so this is a per-rollout
    cost, never a per-tenant one."""
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
    version_table = table(
        "alembic_version", column("version_num"), schema=TENANT_TEMPLATE_SCHEMA
    )
    with get_engine_for_shard(shard_name).connect() as connection:
        stamped = connection.scalar(select(version_table.c.version_num))
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
    """Structure must match catalog line for line after name and array-cast
    normalisation. Rows must match in count and, outside the excluded columns
    in content."""
    differences = _structure_differences(shard_name, left, right)
    with get_engine_for_shard(shard_name).connect() as connection:
        differences.extend(_row_differences(connection, left, right))
    return differences


def _structure_differences(shard_name: str, left: str, right: str) -> list[str]:
    with get_engine_for_shard(shard_name).connect() as connection:
        left_lines = _structure_lines(connection, left)
        right_lines = _structure_lines(connection, right)
    diff = list(
        unified_diff(left_lines, right_lines, fromfile=left, tofile=right, lineterm="")
    )
    if not diff:
        return []
    return ["structure differs:"] + diff[:_DIFF_LINES_REPORTED]


def _structure_lines(connection: Connection, schema: str) -> list[str]:
    """One line per catalog fact about the schema, read straight from pg_catalog.

    These queries return only the schema's own rows. pg_dump loads the whole
    catalog before it filters to one schema, so its memory and time scale with
    every tenant in the database."""
    schema_name = _schema_name_pattern(schema)
    lines: list[str] = []
    for statement in _STRUCTURE_QUERIES:
        for row in connection.execute(statement, {"schema": schema}):
            line = " ".join("" if value is None else str(value) for value in row)
            line = schema_name.sub("SCHEMA", line.replace("\n", " "))
            lines.append(_canonical_text_arrays(line))
    return lines


def _canonical_text_arrays(line: str) -> str:
    def literals_only(match: re.Match[str]) -> str:
        return "ARRAY[" + ", ".join(_QUOTED_LITERAL.findall(match.group(1))) + "]"

    return _CAST_OF_ARRAY.sub(literals_only, _ARRAY_OF_CASTS.sub(literals_only, line))


def _row_differences(connection: Connection, left: str, right: str) -> list[str]:
    differences: list[str] = []
    for table_name in _tables(connection, left):
        columns = _compared_columns(connection, left, table_name)
        left_count, left_digest = _row_digest(connection, left, table_name, columns)
        right_count, right_digest = _row_digest(connection, right, table_name, columns)
        if left_count != right_count:
            differences.append(
                f"{table_name}: {left_count} rows in {left}, {right_count} in {right}"
            )
        elif left_digest != right_digest:
            differences.append(f"{table_name}: row contents differ")
    return differences


def _tables(connection: Connection, schema: str) -> list[str]:
    return sorted(inspect(connection).get_table_names(schema=schema))


def _compared_columns(
    connection: Connection, schema: str, table_name: str
) -> list[str]:
    """Columns whose values a clone and a fresh migration must agree on."""
    return [
        reflected["name"]
        for reflected in inspect(connection).get_columns(table_name, schema=schema)
        if "computed" not in reflected
        and not isinstance(reflected["type"], _UNCOMPARED_COLUMN_TYPES)
    ]


def _row_digest(
    connection: Connection, schema: str, table_name: str, columns: list[str]
) -> tuple[int, str]:
    source = table(table_name, *(column(name) for name in columns), schema=schema)
    if not columns:
        count = connection.scalar(select(func.count()).select_from(source))
        return int(count or 0), ""
    # A row constructor keeps NULL positions, so a NULL moving between columns
    # still differs.
    row_text = cast(
        tuple_(*(source.c[name] for name in columns)),
        Text,
    ).label("row_text")
    rows = select(row_text).select_from(source).subquery()
    digest = func.md5(
        func.coalesce(
            func.string_agg(
                rows.c.row_text, aggregate_order_by(literal("|"), rows.c.row_text)
            ),
            "",
        )
    )
    row = connection.execute(select(func.count(), digest).select_from(rows)).one()
    return int(row[0]), str(row[1])


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
