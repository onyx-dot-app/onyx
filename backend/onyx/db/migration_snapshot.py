"""Snapshot the result of the Alembic chain so dev and CI do not replay every revision.

The chain has grown past 400 revisions and a run from base takes tens of seconds. Tests
rebuild the schema on every `reset` fixture, so the cost is paid many times per job.

A snapshot is a `pg_dump` of a database that the real migrations built. It is never
hand-written and never committed. The cache key is a hash of `alembic/versions`, so a
snapshot only applies to the exact revision set that produced it. Change any migration
file and the key changes.

Three outcomes, in order of preference:

1. `SNAPSHOT` - the key matches. Restore the dump. No migration runs.
2. `SNAPSHOT_DELTA` - an older snapshot holds a strict prefix of the current revision
   set. Restore it, then run only the revisions added since. New migrations still get
   exercised, which is the point: a snapshot must never hide a broken migration.
3. `FULL_CHAIN` - nothing usable. Run every revision, exactly as production does.

Every outcome ends with the same schema. `scripts/alembic_snapshot.py verify` proves it
by building a database both ways and comparing the catalog and every row.

Production never calls this. It runs `alembic upgrade head` unchanged.
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import psycopg2
import psycopg2.extensions
from alembic.script import ScriptDirectory

from onyx.configs.app_configs import (
    POSTGRES_HOST,
    POSTGRES_PASSWORD,
    POSTGRES_PORT,
    POSTGRES_USER,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Opt out and every caller falls back to the full chain.
DISABLE_ENV_VAR = "ONYX_DISABLE_MIGRATION_SNAPSHOT"

# Where snapshots live. CI points this at a restored cache directory.
SNAPSHOT_DIR_ENV_VAR = "ONYX_MIGRATION_SNAPSHOT_DIR"

_BACKEND_DIR = Path(__file__).resolve().parents[2]
_DEFAULT_SNAPSHOT_DIR = _BACKEND_DIR / ".migration_snapshots"
_VERSIONS_DIR = _BACKEND_DIR / "alembic" / "versions"

# Bump when the dump or restore procedure changes so old snapshots are ignored.
_SNAPSHOT_FORMAT_VERSION = 1


class SnapshotOutcome(str, Enum):
    SNAPSHOT = "snapshot"
    SNAPSHOT_DELTA = "snapshot+delta"
    FULL_CHAIN = "full_chain"


@dataclass(frozen=True)
class SnapshotMetadata:
    """What a stored snapshot contains, so we can tell if it still applies."""

    key: str
    head_revision: str
    server_major: int
    format_version: int
    # revision file name -> sha256 of its contents
    files: dict[str, str]

    def to_json(self) -> str:
        return json.dumps(
            {
                "key": self.key,
                "head_revision": self.head_revision,
                "server_major": self.server_major,
                "format_version": self.format_version,
                "files": self.files,
            },
            indent=2,
            sort_keys=True,
        )

    @staticmethod
    def from_json(raw: str) -> "SnapshotMetadata":
        data = json.loads(raw)
        return SnapshotMetadata(
            key=data["key"],
            head_revision=data["head_revision"],
            server_major=data["server_major"],
            format_version=data["format_version"],
            files=data["files"],
        )


def snapshot_dir() -> Path:
    configured = os.environ.get(SNAPSHOT_DIR_ENV_VAR, "").strip()
    return Path(configured) if configured else _DEFAULT_SNAPSHOT_DIR


def is_enabled() -> bool:
    return os.environ.get(DISABLE_ENV_VAR, "").lower() not in ("1", "true", "yes")


def revision_file_hashes() -> dict[str, str]:
    """sha256 of every revision file, keyed by file name."""
    hashes: dict[str, str] = {}
    for path in sorted(_VERSIONS_DIR.glob("*.py")):
        hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes


def _cache_key(files: dict[str, str], server_major: int) -> str:
    """Identity of a revision set on a given server major.

    A dump is only valid for the server major that produced it, so the major is part
    of the key rather than a separate check.
    """
    digest = hashlib.sha256()
    digest.update(f"v{_SNAPSHOT_FORMAT_VERSION}|pg{server_major}|".encode())
    for name in sorted(files):
        digest.update(f"{name}:{files[name]}|".encode())
    return digest.hexdigest()[:32]


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
        application_name="migration_snapshot",
    )
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            yield cur
    finally:
        conn.close()


def server_major_version(database: str) -> int:
    with _cursor(database) as cur:
        cur.execute("SHOW server_version_num")
        row = cur.fetchone()
        assert row is not None
        return int(row[0]) // 10000


def _head_revision() -> str:
    script = ScriptDirectory(str(_BACKEND_DIR / "alembic"))
    head = script.get_current_head()
    if head is None:
        raise RuntimeError("Alembic reports no head revision.")
    return head


def _is_ancestor_of_head(revision: str) -> bool:
    """True when `revision` is on the path from base to the current head.

    Guards the delta path. A snapshot taken on a branch whose revisions are gone after
    a checkout must not be restored: `alembic upgrade head` would fail on an
    alembic_version row it cannot resolve.
    """
    script = ScriptDirectory(str(_BACKEND_DIR / "alembic"))
    try:
        return any(
            rev.revision == revision
            for rev in script.iterate_revisions(_head_revision(), "base")
        )
    except Exception:
        # Unknown revision - alembic raises rather than returning empty.
        return False


# pg_dump writes a preamble of GUCs that a newer client may emit and an older server
# may reject (`transaction_timeout` from a 17+ client against a 15 server), plus psql
# meta-commands (`\restrict`) that are not SQL. Both are stripped so the dump can be
# replayed over a plain database connection with no psql binary involved.
#
# Only the preamble is filtered. A `SET` inside a function body is indented and appears
# after the first object, so it is never touched.
_PREAMBLE_NOISE = re.compile(r"^(SET |SELECT pg_catalog\.set_config)")
_FIRST_OBJECT = ("CREATE ", "ALTER ", "COPY ", "COMMENT ", "INSERT ")


def _to_portable_sql(dump: str) -> str:
    lines: list[str] = []
    in_preamble = True
    for line in dump.splitlines():
        if line.startswith("\\"):
            continue
        if in_preamble:
            if _PREAMBLE_NOISE.match(line):
                continue
            if line.startswith(_FIRST_OBJECT):
                in_preamble = False
        lines.append(line)
    return "\n".join(lines) + "\n"


def dump_database(database: str) -> str:
    """Portable SQL that recreates `database`.

    Dumps the whole database rather than a single schema. `--schema=public` omits
    `CREATE EXTENSION`, which restores without error and then fails at runtime on the
    first `gen_random_uuid()` default - a silent corruption we must not ship.

    `--inserts` keeps the output free of `COPY ... FROM stdin`, which is a psql
    protocol feature rather than SQL. The seeded data is small enough that the size
    cost does not matter.
    """
    pg_dump = shutil.which("pg_dump")
    if pg_dump is None:
        raise FileNotFoundError("pg_dump is not on PATH")

    result = subprocess.run(
        [
            pg_dump,
            "--host",
            POSTGRES_HOST,
            "--port",
            str(POSTGRES_PORT),
            "--username",
            POSTGRES_USER,
            "--dbname",
            database,
            "--no-owner",
            "--no-privileges",
            "--inserts",
        ],
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, "PGPASSWORD": POSTGRES_PASSWORD},
    )
    return _to_portable_sql(result.stdout)


def restore_dump(database: str, sql: str, schema: str = "public") -> None:
    """Replay a dump into an empty schema.

    The caller drops the schema first (reset.py already does). We recreate it here
    because a whole-database dump assumes `public` exists.
    """
    with _cursor(database) as cur:
        cur.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        cur.execute(f'CREATE SCHEMA "{schema}"')
        cur.execute(f'GRANT ALL ON SCHEMA "{schema}" TO {POSTGRES_USER}')
        cur.execute(f'GRANT ALL ON SCHEMA "{schema}" TO public')
        cur.execute(f'SET search_path TO "{schema}"')
        cur.execute(sql)


def _load_metadata(directory: Path) -> list[SnapshotMetadata]:
    found: list[SnapshotMetadata] = []
    if not directory.is_dir():
        return found
    for path in sorted(directory.glob("*.json")):
        try:
            metadata = SnapshotMetadata.from_json(path.read_text())
        except (OSError, json.JSONDecodeError, KeyError):
            logger.warning("Ignoring unreadable snapshot metadata: %s", path)
            continue
        if metadata.format_version != _SNAPSHOT_FORMAT_VERSION:
            continue
        if not (directory / f"{metadata.key}.sql").is_file():
            continue
        found.append(metadata)
    return found


def _find_reusable_snapshot(
    directory: Path, files: dict[str, str], server_major: int
) -> SnapshotMetadata | None:
    """Newest snapshot holding a strict prefix of the current revision set.

    "Prefix" means every revision file it recorded is still present with identical
    contents. That rules out reusing a snapshot from a branch that edited a migration
    in place, where replaying only the newer revisions would leave a different schema.
    """
    candidates: list[SnapshotMetadata] = []
    for metadata in _load_metadata(directory):
        if metadata.server_major != server_major:
            continue
        if any(files.get(name) != digest for name, digest in metadata.files.items()):
            continue
        if not _is_ancestor_of_head(metadata.head_revision):
            continue
        candidates.append(metadata)

    if not candidates:
        return None
    # More recorded files means fewer revisions left to replay.
    return max(candidates, key=lambda m: len(m.files))


def _store_snapshot(
    directory: Path, key: str, sql: str, metadata: SnapshotMetadata
) -> None:
    """Write a snapshot so concurrent test workers never observe a partial file."""
    directory.mkdir(parents=True, exist_ok=True)
    for suffix, payload in ((".sql", sql), (".json", metadata.to_json())):
        handle, temp_path = tempfile.mkstemp(dir=directory, suffix=suffix)
        try:
            with os.fdopen(handle, "w") as file:
                file.write(payload)
            os.replace(temp_path, directory / f"{key}{suffix}")
        except BaseException:
            Path(temp_path).unlink(missing_ok=True)
            raise


def _empty_schema(database: str, schema: str) -> None:
    with _cursor(database) as cur:
        cur.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        cur.execute(f'CREATE SCHEMA "{schema}"')
        cur.execute(f'GRANT ALL ON SCHEMA "{schema}" TO {POSTGRES_USER}')
        cur.execute(f'GRANT ALL ON SCHEMA "{schema}" TO public')


def build_schema(
    database: str,
    migrate_to_head: Callable[[], None],
    schema: str = "public",
) -> SnapshotOutcome:
    """Bring `database` to head, reusing a snapshot when one applies.

    `migrate_to_head` must run `alembic upgrade head` against `database`. It is passed
    in so this module stays independent of how each caller configures Alembic.

    Any failure in the snapshot path falls back to the full chain. A snapshot is an
    optimisation; it must never be the reason a test cannot run.
    """
    if not is_enabled():
        migrate_to_head()
        return SnapshotOutcome.FULL_CHAIN

    try:
        directory = snapshot_dir()
        files = revision_file_hashes()
        server_major = server_major_version(database)
        key = _cache_key(files, server_major)

        exact = directory / f"{key}.sql"
        if exact.is_file():
            restore_dump(database, exact.read_text(), schema=schema)
            logger.info(
                "Restored migration snapshot %s (%s revisions)", key, len(files)
            )
            return SnapshotOutcome.SNAPSHOT

        reusable = _find_reusable_snapshot(directory, files, server_major)
        outcome = SnapshotOutcome.FULL_CHAIN
        if reusable is not None:
            pending = len(files) - len(reusable.files)
            logger.info(
                "Restoring snapshot %s, then replaying %s new revision(s)",
                reusable.key,
                pending,
            )
            restore_dump(
                database, (directory / f"{reusable.key}.sql").read_text(), schema=schema
            )
            outcome = SnapshotOutcome.SNAPSHOT_DELTA
        else:
            _empty_schema(database, schema)

    except Exception:
        logger.exception("Migration snapshot unusable; running the full chain.")
        _empty_schema(database, schema)
        migrate_to_head()
        return SnapshotOutcome.FULL_CHAIN

    migrate_to_head()

    try:
        _store_snapshot(
            directory,
            key,
            dump_database(database),
            SnapshotMetadata(
                key=key,
                head_revision=_head_revision(),
                server_major=server_major,
                format_version=_SNAPSHOT_FORMAT_VERSION,
                files=files,
            ),
        )
        logger.info("Stored migration snapshot %s", key)
    except Exception:
        # The database is already at head. Only the cache write failed.
        logger.exception("Could not store migration snapshot; continuing.")

    return outcome
