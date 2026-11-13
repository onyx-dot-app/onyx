"""Runs the queued deferred constraint checks after each Alembic revision.

Every pending revision runs in one transaction. A revision that writes rows
under a deferred constraint queues checks until commit, and an ALTER TABLE on
that table in a later revision fails with "pending trigger events". The
statement is plain SQL so offline (``--sql``) scripts carry it too. It names
each constraint: SET CONSTRAINTS ALL would also make constraints that later
revisions create immediate.
"""

from collections.abc import Collection, Mapping
from typing import Any

from alembic.runtime.migration import MigrationContext, MigrationInfo

RUN_QUEUED_DEFERRED_CHECKS = """
DO $$
DECLARE
    deferred_names text;
BEGIN
    SELECT string_agg(format('%I.%I', n.nspname, c.conname), ', ')
    INTO deferred_names
    FROM pg_constraint c
    JOIN pg_namespace n ON n.oid = c.connamespace
    WHERE c.condeferred AND n.nspname = current_schema();
    IF deferred_names IS NOT NULL THEN
        EXECUTE 'SET CONSTRAINTS ' || deferred_names || ' IMMEDIATE';
        EXECUTE 'SET CONSTRAINTS ' || deferred_names || ' DEFERRED';
    END IF;
END $$
"""


def run_queued_deferred_checks(
    ctx: MigrationContext,
    step: MigrationInfo,  # noqa: ARG001
    heads: Collection[Any],  # noqa: ARG001
    run_args: Mapping[str, Any],  # noqa: ARG001
) -> None:
    """Alembic ``on_version_apply`` callback: run the checks, then restore the
    deferred default."""
    ctx.execute(RUN_QUEUED_DEFERRED_CHECKS)
