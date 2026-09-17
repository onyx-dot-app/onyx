#!/usr/bin/env python3
"""Parallel Alembic Migration Runner

Upgrades tenant schemas to head in batched, parallel alembic subprocesses.
Each subprocess handles a batch of schemas (via ``-x schemas=a,b,c``),
reducing per-process overhead compared to one-schema-per-process.

Usage examples::

    # defaults: 6 workers, 50 schemas/batch
    python alembic/run_multitenant_migrations.py

    # custom settings
    python alembic/run_multitenant_migrations.py -j 8 -b 100
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import NamedTuple

from alembic.config import Config
from alembic.script import ScriptDirectory

from onyx.db.engine.sql_engine import SqlEngine
from onyx.db.engine.tenant_utils import get_schemas_needing_migration
from onyx.db.engine.tenant_utils import get_tenant_ids_by_shard
from shared_configs.configs import TENANT_ID_PREFIX

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


class Args(NamedTuple):
    jobs: int
    batch_size: int


class Batch(NamedTuple):
    shard_name: str
    schemas: list[str]


class BatchResult(NamedTuple):
    schemas: list[str]
    success: bool
    output: str
    elapsed_sec: float


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------


def run_alembic_for_batch(batch: Batch) -> BatchResult:
    """Run ``alembic upgrade head`` for a batch of schemas in one subprocess.

    If the batch fails, it is automatically retried with ``-x continue=true``
    so that the remaining schemas in the batch still get migrated.  The retry
    output (which contains alembic's per-schema error messages) is returned
    for diagnosis.
    """
    schemas = batch.schemas
    csv = ",".join(schemas)
    # `shard` pins the subprocess to the database holding these schemas.
    base_cmd = ["alembic", "-x", f"schemas={csv}", "-x", f"shard={batch.shard_name}"]

    start = time.monotonic()
    result = subprocess.run(
        [*base_cmd, "upgrade", "head"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    if result.returncode == 0:
        elapsed = time.monotonic() - start
        return BatchResult(schemas, True, result.stdout or "", elapsed)

    # At least one schema failed.  Print the initial error output, then
    # re-run with continue=true so the remaining schemas still get migrated.
    if result.stdout:
        print(f"Initial error output:\n{result.stdout}", file=sys.stderr, flush=True)
    print(
        f"Batch failed (exit {result.returncode}), retrying with 'continue=true'...",
        file=sys.stderr,
        flush=True,
    )

    retry = subprocess.run(
        [*base_cmd, "-x", "continue=true", "upgrade", "head"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    elapsed = time.monotonic() - start
    return BatchResult(schemas, False, retry.stdout or "", elapsed)


def get_head_revision() -> str | None:
    """Get the head revision from the alembic script directory."""
    alembic_cfg = Config("alembic.ini")
    script = ScriptDirectory.from_config(alembic_cfg)
    return script.get_current_head()


def run_migrations_parallel(
    schemas_by_shard: dict[str, list[str]],
    max_workers: int,
    batch_size: int,
) -> bool:
    """Chunk each shard's schemas into batches and run them in parallel.

    Batches never span shards, so one subprocess talks to exactly one database.

    A background monitor thread prints a status line every 60 s listing
    which batches are still in-flight, making it easy to spot hung tenants.
    """
    batches = [
        Batch(shard_name, shard_schemas[i : i + batch_size])
        for shard_name, shard_schemas in sorted(schemas_by_shard.items())
        for i in range(0, len(shard_schemas), batch_size)
    ]
    total_batches = len(batches)
    total_schemas = sum(len(s) for s in schemas_by_shard.values())
    print(
        f"{total_schemas} schemas across {len(schemas_by_shard)} shard(s) in "
        f"{total_batches} batch(es) with {max_workers} workers (batch size: {batch_size})...",
        flush=True,
    )
    all_success = True

    # Thread-safe tracking of in-flight batches for the monitor thread.
    in_flight: dict[int, list[str]] = {}
    prev_in_flight: set[int] = set()
    lock = threading.Lock()
    stop_event = threading.Event()

    def _monitor() -> None:
        """Print a status line every 60 s listing batches still in-flight.

        Only prints batches that were also present in the previous tick,
        making it easy to spot batches that are stuck.
        """
        nonlocal prev_in_flight
        while not stop_event.wait(60):
            with lock:
                if not in_flight:
                    prev_in_flight = set()
                    continue
                current = set(in_flight)
                stuck = current & prev_in_flight
                prev_in_flight = current

                if not stuck:
                    continue

                schemas = [s for idx in sorted(stuck) for s in in_flight[idx]]
                print(
                    f"⏳ batch(es) still running since last check "
                    f"({', '.join(str(i + 1) for i in sorted(stuck))}): "
                    + ", ".join(schemas),
                    flush=True,
                )

    monitor_thread = threading.Thread(target=_monitor, daemon=True)
    monitor_thread.start()

    try:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:

            def _run(batch_idx: int, batch: Batch) -> BatchResult:
                with lock:
                    in_flight[batch_idx] = batch.schemas
                print(
                    f"Batch {batch_idx + 1}/{total_batches} started on shard "
                    f"{batch.shard_name} ({len(batch.schemas)} schemas): "
                    f"{', '.join(batch.schemas)}",
                    flush=True,
                )
                result = run_alembic_for_batch(batch)
                with lock:
                    in_flight.pop(batch_idx, None)
                return result

            future_to_idx = {
                executor.submit(_run, i, b): i for i, b in enumerate(batches)
            }

            for future in as_completed(future_to_idx):
                batch_idx = future_to_idx[future]
                try:
                    result = future.result()
                    status = "✓" if result.success else "✗"

                    print(
                        f"Batch {batch_idx + 1}/{total_batches} "
                        f"{status} {len(result.schemas)} schemas "
                        f"in {result.elapsed_sec:.1f}s",
                        flush=True,
                    )

                    if not result.success:
                        # Print last 20 lines of retry output for diagnosis
                        tail = result.output.strip().splitlines()[-20:]
                        for line in tail:
                            print(f"    {line}", flush=True)
                        all_success = False

                except Exception as e:
                    print(
                        f"Batch {batch_idx + 1}/{total_batches} ✗ exception: {e}",
                        flush=True,
                    )
                    all_success = False
    finally:
        stop_event.set()
        monitor_thread.join(timeout=2)

    return all_success


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


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
        help="Number of parallel alembic processes (default: 6)",
    )
    parser.add_argument(
        "-b",
        "--batch-size",
        type=int,
        default=50,
        metavar="N",
        help="Schemas per alembic process (default: 50)",
    )
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error("--jobs must be >= 1")
    if args.batch_size < 1:
        parser.error("--batch-size must be >= 1")
    return Args(jobs=args.jobs, batch_size=args.batch_size)


def main() -> int:
    args = parse_args()

    head_rev = get_head_revision()
    if head_rev is None:
        print("Could not determine head revision.", file=sys.stderr)
        return 1

    schemas_by_shard: dict[str, list[str]] = {}
    with SqlEngine.scoped_engine(pool_size=5, max_overflow=2):
        # The prefix filter drops `public`, which enumeration reports as the sole
        # "tenant" outside multi-tenant mode. That is what makes the hint below fire.
        tenants_by_shard = {
            shard_name: [t for t in tenants if t.startswith(TENANT_ID_PREFIX)]
            for shard_name, tenants in get_tenant_ids_by_shard().items()
        }
        total_tenants = sum(len(s) for s in tenants_by_shard.values())

        if not total_tenants:
            print(
                "No tenant schemas found. Is MULTI_TENANT=true set?",
                file=sys.stderr,
            )
            return 1

        # Per shard: alembic_version lives in the schema, so each shard has to be
        # asked about its own tenants.
        for shard_name, tenants in tenants_by_shard.items():
            if not tenants:
                continue
            needing = get_schemas_needing_migration(tenants, head_rev, shard_name)
            if needing:
                schemas_by_shard[shard_name] = needing

    total_to_migrate = sum(len(s) for s in schemas_by_shard.values())
    if not total_to_migrate:
        print(f"All {total_tenants} tenants are already at head revision ({head_rev}).")
        return 0

    print(
        f"{total_to_migrate}/{total_tenants} tenants need migration (head: {head_rev})."
    )

    success = run_migrations_parallel(
        schemas_by_shard,
        max_workers=args.jobs,
        batch_size=args.batch_size,
    )

    print(f"\n{'All migrations successful' if success else 'Some migrations failed'}")
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
