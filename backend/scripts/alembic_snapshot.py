"""Manage Alembic schema snapshots.

    apply    Bring a database to head, reusing a snapshot when one applies.
             A drop-in replacement for `alembic upgrade head` in dev and CI.
    clear    Delete stored snapshots.

Run from `backend/`. See onyx/db/migration_snapshot.py for the design, and
tests/integration/tests/migrations/test_migration_snapshot.py for the proof that a
snapshot reaches the same schema as running every revision.
"""

import argparse
import os
import sys
from types import SimpleNamespace

from alembic import command
from alembic.config import Config

from onyx.configs.app_configs import (
    POSTGRES_HOST,
    POSTGRES_PASSWORD,
    POSTGRES_PORT,
    POSTGRES_USER,
)
from onyx.db.engine.shard_registry import ALEMBIC_TARGET_URL_ATTRIBUTE
from onyx.db.engine.sql_engine import build_connection_string
from onyx.db.migration_snapshot import build_schema, snapshot_dir


def _alembic_config(database: str) -> Config:
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
    return config


def _upgrade(database: str, revision: str = "head") -> None:
    command.upgrade(_alembic_config(database), revision)


def cmd_apply(args: argparse.Namespace) -> int:
    database = args.database or os.environ.get("POSTGRES_DB") or "postgres"
    outcome = build_schema(
        database=database, migrate_to_head=lambda: _upgrade(database)
    )
    print(f"{database} is at head via {outcome.value}")
    return 0


def cmd_clear(args: argparse.Namespace) -> int:  # noqa: ARG001
    directory = snapshot_dir()
    removed = 0
    for path in list(directory.glob("*.sql")) + list(directory.glob("*.json")):
        path.unlink()
        removed += 1
    print(f"Removed {removed} file(s) from {directory}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    apply_parser = subparsers.add_parser("apply", help="bring a database to head")
    apply_parser.add_argument("--database", help="defaults to $POSTGRES_DB")
    apply_parser.set_defaults(func=cmd_apply)

    clear_parser = subparsers.add_parser("clear", help="delete stored snapshots")
    clear_parser.set_defaults(func=cmd_clear)

    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
