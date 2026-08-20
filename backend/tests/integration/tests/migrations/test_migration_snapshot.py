"""Prove that restoring a schema snapshot matches running every migration.

Dev and CI skip the ~440-revision replay by restoring a `pg_dump` of a database the
migrations already built (see `onyx/db/migration_snapshot.py`). That shortcut is only
safe while it lands on exactly the schema the full chain produces, including the
triggers, functions, extensions, and seeded rows that older migrations create by hand.

The test builds one database each way and compares the catalog and every row.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from types import SimpleNamespace

import psycopg2
import psycopg2.extensions
import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

from onyx.configs.app_configs import (
    POSTGRES_HOST,
    POSTGRES_PASSWORD,
    POSTGRES_PORT,
    POSTGRES_USER,
)
from onyx.db.engine.shard_registry import ALEMBIC_TARGET_URL_ATTRIBUTE
from onyx.db.engine.sql_engine import build_connection_string
from onyx.db.migration_snapshot import dump_database, restore_dump

# How many revisions to replay on top of the snapshot. Mirrors the delta path a PR
# that adds migrations takes.
REVISIONS_ON_TOP = 10

_DB_PREFIX = "onyx_snapshot_equivalence"

# Every object the migration chain creates: shape, integrity rules, executable code,
# and seeded rows.
_FACET_QUERIES: dict[str, str] = {
    "columns": """
        SELECT table_name, column_name, data_type, is_nullable, column_default,
               character_maximum_length, numeric_precision, udt_name
        FROM information_schema.columns WHERE table_schema = 'public'
        ORDER BY table_name, column_name""",
    "constraints": """
        SELECT conrelid::regclass::text, conname, pg_get_constraintdef(oid)
        FROM pg_constraint WHERE connamespace = 'public'::regnamespace
        ORDER BY 1, 2, 3""",
    "indexes": """
        SELECT tablename, indexname, indexdef FROM pg_indexes
        WHERE schemaname = 'public' ORDER BY 1, 2""",
    "functions": """
        SELECT p.proname, pg_get_functiondef(p.oid)
        FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
        LEFT JOIN pg_depend d ON d.objid = p.oid AND d.deptype = 'e'
        WHERE n.nspname = 'public' AND d.objid IS NULL ORDER BY 1, 2""",
    "triggers": """
        SELECT c.relname, t.tgname, pg_get_triggerdef(t.oid)
        FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid
        WHERE NOT t.tgisinternal ORDER BY 1, 2""",
    "extensions": "SELECT extname FROM pg_extension ORDER BY 1",
    "enums": """
        SELECT t.typname, string_agg(e.enumlabel, ',' ORDER BY e.enumsortorder)
        FROM pg_type t
        JOIN pg_enum e ON e.enumtypid = t.oid
        JOIN pg_namespace n ON n.oid = t.typnamespace
        WHERE n.nspname = 'public' GROUP BY 1 ORDER BY 1""",
    "sequences": """
        SELECT sequencename, start_value, increment_by, last_value
        FROM pg_sequences WHERE schemaname = 'public' ORDER BY 1""",
}

# Seeding migrations call now() and gen_random_uuid(), so columns of these types
# differ between any two runs of the chain - snapshots are not involved. Two
# independent full-chain runs disagree on them as well. Masking them keeps the
# comparison on what the migrations actually determine. Row counts are compared
# separately, so a masked column cannot hide a missing or extra row.
_NONDETERMINISTIC_UDT = ("uuid", "_uuid", "timestamp", "timestamptz")
_MASK = "'~masked~'"


@contextmanager
def _cursor(database: str) -> Iterator["psycopg2.extensions.cursor"]:
    """An autocommit cursor.

    Deliberately avoids `with connection`, which opens a transaction even when
    autocommit is set and so blocks statements like CREATE DATABASE.
    """
    conn = psycopg2.connect(
        dbname=database,
        user=POSTGRES_USER,
        password=POSTGRES_PASSWORD,
        host=POSTGRES_HOST,
        port=POSTGRES_PORT,
        application_name="snapshot_equivalence_test",
    )
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            yield cur
    finally:
        conn.close()


def _recreate_database(database: str) -> None:
    with _cursor("postgres") as cur:
        cur.execute(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)')
        cur.execute(f'CREATE DATABASE "{database}"')


def _upgrade(database: str, revision: str = "head") -> None:
    config = Config("alembic.ini")
    config.attributes["configure_logger"] = False
    config.cmd_opts = SimpleNamespace()  # ty: ignore[invalid-assignment]
    config.cmd_opts.x = ["schema=public"]  # ty: ignore[invalid-assignment]
    # env.py ignores `sqlalchemy.url` by design and reads this attribute instead. It
    # builds an async engine from it, so the URL must use the async driver.
    config.attributes[ALEMBIC_TARGET_URL_ATTRIBUTE] = build_connection_string(
        db=database,
        user=POSTGRES_USER,
        password=POSTGRES_PASSWORD,
        host=POSTGRES_HOST,
        port=POSTGRES_PORT,
    )
    command.upgrade(config, revision)


def _row_expression(cur: "psycopg2.extensions.cursor", table: str) -> str:
    """A row-to-text expression with nondeterministic columns masked."""
    cur.execute(
        """
        SELECT column_name, udt_name FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = %s
        ORDER BY ordinal_position
        """,
        (table,),
    )
    parts = [
        _MASK if udt in _NONDETERMINISTIC_UDT else f't."{name}"::text'
        for name, udt in cur.fetchall()
    ]
    return f"concat_ws('|', {', '.join(parts)})" if parts else "''"


def _fingerprint(database: str) -> dict[str, str]:
    """Catalog and row-level identity of a database.

    Read through SQL rather than pg_dump so the check does not lean on the same tool
    that produced the snapshot.
    """
    facets: dict[str, str] = {}
    with _cursor(database) as cur:
        for name, query in _FACET_QUERIES.items():
            cur.execute(query)
            facets[name] = "\n".join(
                " | ".join(map(str, row)) for row in cur.fetchall()
            )

        cur.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY 1"
        )
        rows = []
        for (table,) in cur.fetchall():
            cur.execute(f'SELECT count(*) FROM public."{table}"')
            count_row = cur.fetchone()
            assert count_row is not None

            cur.execute(
                "SELECT md5(string_agg(r, E'\\n' ORDER BY r)) FROM "
                f"(SELECT {_row_expression(cur, table)} AS r "
                f'FROM public."{table}" t) s'
            )
            digest_row = cur.fetchone()
            assert digest_row is not None
            rows.append(f"{table} | {count_row[0]} rows | {digest_row[0]}")
        facets["data"] = "\n".join(rows)
    return facets


def _describe(facet: str, expected: str, actual: str) -> str:
    only_expected = sorted(set(expected.splitlines()) - set(actual.splitlines()))
    only_actual = sorted(set(actual.splitlines()) - set(expected.splitlines()))
    lines = [f"{facet} differs between the full chain and the snapshot:"]
    lines += [f"  full chain only: {line[:240]}" for line in only_expected[:10]]
    lines += [f"  snapshot only:   {line[:240]}" for line in only_actual[:10]]
    return "\n".join(lines)


@pytest.fixture
def scratch_databases() -> Iterator[tuple[str, str, str]]:
    names = (f"{_DB_PREFIX}_full", f"{_DB_PREFIX}_snapshot", f"{_DB_PREFIX}_roundtrip")
    try:
        yield names
    finally:
        with _cursor("postgres") as cur:
            for name in names:
                cur.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def test_snapshot_plus_new_revisions_matches_full_chain(
    scratch_databases: tuple[str, str, str],
) -> None:
    full_db, snapshot_db, roundtrip_db = scratch_databases

    revisions = list(ScriptDirectory("alembic").iterate_revisions("head", "base"))
    assert REVISIONS_ON_TOP < len(revisions)
    split = revisions[REVISIONS_ON_TOP].revision

    _recreate_database(full_db)
    _upgrade(full_db)

    # Snapshot an older point in history, then replay the newer revisions on top.
    _recreate_database(snapshot_db)
    _upgrade(snapshot_db, split)
    snapshot_sql = dump_database(snapshot_db)
    _recreate_database(snapshot_db)
    restore_dump(snapshot_db, snapshot_sql)
    _upgrade(snapshot_db)

    # Both sides must pass through exactly one dump/restore before they are compared.
    # Postgres re-renders a few `sa.Enum` IN-lists when it reparses them
    # (`ANY ((ARRAY[x])::text[])` becomes `ANY (ARRAY[(x)::text])`), which is a display
    # change rather than a semantic one, and it converges after one cycle. Round
    # tripping the full-chain database cancels it out, so this stays an exact equality
    # with no hand-written normalisation to get wrong.
    _recreate_database(roundtrip_db)
    restore_dump(roundtrip_db, dump_database(full_db))

    expected = _fingerprint(roundtrip_db)
    actual = _fingerprint(snapshot_db)
    for facet, expected_value in expected.items():
        assert expected_value == actual[facet], _describe(
            facet, expected_value, actual[facet]
        )
