#!/usr/bin/env python3
"""Parallel Alembic Migration Runner"""
from __future__ import annotations

import argparse
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, NamedTuple

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text

from onyx.db.engine.sql_engine import is_valid_schema_name
from onyx.db.engine.sql_engine import SqlEngine
from onyx.db.engine.tenant_utils import get_all_tenant_ids
from shared_configs.configs import TENANT_ID_PREFIX


class Args(NamedTuple):
    jobs: int


class MigrationResult(NamedTuple):
    schema: str
    success: bool
    output: str


def run_alembic_for_schema(schema: str) -> MigrationResult:
    """
    Run alembic upgrade for a single schema in a subprocess.
    """
    cmd = ["alembic", "-x", f"schemas={schema}", "upgrade", "head"]

    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=True,
        )
        return MigrationResult(schema, True, result.stdout or "Success")
    except subprocess.CalledProcessError as e:
        error_msg = f"Exit code {e.returncode}\n{e.stdout or ''}"
        return MigrationResult(schema, False, error_msg)


def get_head_revision() -> str | None:
    """Get the head revision from the alembic script directory."""
    alembic_cfg = Config("alembic.ini")
    script = ScriptDirectory.from_config(alembic_cfg)
    return script.get_current_head()


def get_schemas_needing_migration(
    tenant_schemas: List[str], head_rev: str
) -> List[str]:
    """Return only schemas whose current alembic version is not at head."""
    if not tenant_schemas:
        return []

    engine = SqlEngine.get_engine()

    with engine.connect() as conn:
        # Find which schemas actually have an alembic_version table
        rows = conn.execute(
            text(
                "SELECT table_schema FROM information_schema.tables "
                "WHERE table_name = 'alembic_version' "
                "AND table_schema = ANY(:schemas)"
            ),
            {"schemas": tenant_schemas},
        )
        schemas_with_table = set(row[0] for row in rows)

        # Schemas without the table definitely need migration
        needs_migration = [s for s in tenant_schemas if s not in schemas_with_table]

        if not schemas_with_table:
            return needs_migration

        # Validate schema names before interpolating into SQL
        for schema in schemas_with_table:
            if not is_valid_schema_name(schema):
                raise ValueError(f"Invalid schema name: {schema}")

        # Single query to get every schema's current revision at once.
        # Use integer tags instead of interpolating schema names into
        # string literals to avoid quoting issues.
        schema_list = list(schemas_with_table)
        union_parts = [
            f'SELECT {i} AS idx, version_num FROM "{schema}".alembic_version'
            for i, schema in enumerate(schema_list)
        ]
        rows = conn.execute(text(" UNION ALL ".join(union_parts)))
        version_by_schema = {schema_list[row[0]]: row[1] for row in rows}

        needs_migration.extend(
            s for s in schemas_with_table if version_by_schema.get(s) != head_rev
        )

    return needs_migration


def run_migrations_parallel(schemas: List[str], max_workers: int) -> bool:
    """
    Run alembic migrations for multiple schemas in parallel.
    Returns True if all succeeded.
    """
    all_success = True
    completed = 0
    total = len(schemas)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all tasks
        future_to_schema = {
            executor.submit(run_alembic_for_schema, schema): schema
            for schema in schemas
        }

        # Process results as they complete
        for future in as_completed(future_to_schema):
            schema = future_to_schema[future]
            completed += 1

            try:
                result = future.result()

                if result.success:
                    print(f"[{completed}/{total}] ✓ {schema}")
                else:
                    print(f"[{completed}/{total}] ✗ {schema} failed:")
                    print(f"    {result.output.replace(chr(10), chr(10) + '    ')}")
                    all_success = False

            except Exception as e:
                print(f"[{completed}/{total}] ✗ {schema} exception: {e}")
                all_success = False

    return all_success


def parse_args() -> Args:
    parser = argparse.ArgumentParser(
        description="Run alembic migrations for all tenant schemas in parallel"
    )
    parser.add_argument(
        "-j",
        "--jobs",
        type=int,
        default=6,
        metavar="N",
        help="Number of parallel migrations (default: 6)",
    )
    args = parser.parse_args()
    return Args(jobs=args.jobs)


def main() -> int:
    args = parse_args()

    head_rev = get_head_revision()
    if head_rev is None:
        print("Could not determine head revision.", file=sys.stderr)
        return 1

    SqlEngine.init_engine(pool_size=5, max_overflow=2)

    try:
        tenant_ids = get_all_tenant_ids()
        tenant_schemas = [tid for tid in tenant_ids if tid.startswith(TENANT_ID_PREFIX)]

        if not tenant_schemas:
            print("No tenant schemas found.")
            return 0

        schemas_to_migrate = get_schemas_needing_migration(tenant_schemas, head_rev)
    finally:
        # CRITICAL: Dispose engine before spawning subprocesses
        # This ensures no lingering connections that might interfere
        SqlEngine.reset_engine()

    if not schemas_to_migrate:
        print(
            f"All {len(tenant_schemas)} tenants are already at head "
            f"revision ({head_rev})."
        )
        return 0

    print(
        f"{len(schemas_to_migrate)}/{len(tenant_schemas)} tenants need "
        f"migration (head: {head_rev}). Running with {args.jobs} workers...\n"
    )

    success = run_migrations_parallel(schemas_to_migrate, max_workers=args.jobs)

    print(f"\n{'All migrations successful' if success else 'Some migrations failed'}")
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
