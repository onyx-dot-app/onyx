"""Re-encrypt stored secrets under the write key, or check that they are.

Keys come from the environment: ENCRYPTION_KEY_SECRET, ENCRYPTION_KEYS and
ENCRYPTION_WRITE_KEY_ID. Every physical schema on every shard is covered,
including the tenant template and both copies of a tenant mid-move.

Usage (docker):
    docker exec -it onyx-api_server-1 python -m scripts.reencrypt_secrets --dry-run
    docker exec -it onyx-api_server-1 python -m scripts.reencrypt_secrets
    docker exec -it onyx-api_server-1 python -m scripts.reencrypt_secrets --verify

Usage (kubernetes):
    kubectl exec -it <api pod> -- python -m scripts.reencrypt_secrets --dry-run

Modes:
    --dry-run   Decrypt every value and write nothing. Fails on unreadable or
                unsupported values. Runs without a write key.
    (default)   Rewrite every stale value. Fails when any value is left stale,
                conflicted, unreadable or unsupported. Safe to run again.
    --verify    Decrypt every value and write nothing to any row. Fails unless
                every value is an envelope under the write key, including the
                template snapshot a new tenant would be cloned from, which it
                builds into a scratch schema on each shard and drops again.

Pass --tenant-id to limit a run to one schema wherever it exists.
The exit status is 1 when the run is incomplete.
"""

import argparse
import os
import sys

parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(parent_dir)

from ee.onyx.db.rotate_encryption_key import (  # noqa: E402
    RotationMode,
    RotationReport,
    ValueOutcome,
    rotate_encryption_key,
)
from onyx.db.engine.sql_engine import SqlEngine  # noqa: E402
from onyx.utils.variable_functionality import global_version  # noqa: E402


def format_report(report: RotationReport) -> str:
    """Counts by shard, schema, table and column; identifiers and numbers only."""
    lines = [f"Mode: {report.mode.value}"]
    for schema in report.schemas:
        lines.append(f"{schema.shard_name}/{schema.schema_name}")
        if schema.error is not None:
            lines.append(f"  ERROR {schema.error}")
        if schema.absent_columns:
            lines.append(
                f"  no table or column for {len(schema.absent_columns)} encrypted "
                "column(s): nothing stored there"
            )
        for column in schema.columns:
            counts = " ".join(
                f"{outcome.value}={count}"
                for outcome, count in sorted(column.counts.items())
                if count
            )
            if counts:
                lines.append(f"  {column.name}: {counts}")
    lines.append("Totals:")
    lines.extend(
        f"  {outcome.value}: {report.total(outcome)}" for outcome in ValueOutcome
    )
    reasons = report.incomplete_reasons()
    if reasons:
        lines.append("INCOMPLETE:")
        lines.extend(f"  {reason}" for reason in reasons)
    else:
        lines.append("Complete.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Re-encrypt stored secrets under the write key."
    )
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--dry-run",
        action="store_true",
        help="Decrypt every value and write nothing.",
    )
    mode_group.add_argument(
        "--verify",
        action="store_true",
        help=(
            "Decrypt every value, write no row, fail unless all are current. "
            "Builds and drops a scratch schema per shard to read the snapshot."
        ),
    )
    parser.add_argument(
        "--tenant-id",
        default=None,
        help="Limit the run to one schema, on every shard that holds it.",
    )
    args = parser.parse_args(argv)

    if args.dry_run:
        mode = RotationMode.DRY_RUN
    elif args.verify:
        mode = RotationMode.VERIFY
    else:
        mode = RotationMode.EXECUTE

    global_version.set_ee()
    with SqlEngine.scoped_engine(pool_size=5, max_overflow=2):
        report = rotate_encryption_key(mode, only_schema=args.tenant_id)
    print(format_report(report))
    return 1 if report.incomplete_reasons() else 0


if __name__ == "__main__":
    raise SystemExit(main())
