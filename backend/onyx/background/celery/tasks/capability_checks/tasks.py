"""Celery tasks for the granular capability check runs.

The run task is enqueued by the capability-check trigger endpoint after it marks
the scope's row RUNNING, and writes through the unconditional upsert: a granular
run is the freshest truth and replaces whatever is stored (see the accessors'
writer model). A run that fails gracefully records FAILED_TO_RUN itself; only
hard kills and expired tasks leave their row RUNNING for the beat sweep to
retire once the mark outlives its source's run ceiling.
"""

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from celery import Task, shared_task

from onyx.background.celery.apps.app_base import task_logger
from onyx.configs.constants import OnyxCeleryTask
from onyx.connectors.capability_checks.models import (
    CapabilityCheckResult,
    compute_connector_config_hash,
)
from onyx.connectors.capability_checks.runner import (
    CapabilityCheckProgressCallback,
    capability_check_run_stale_after,
    generate_capability_report,
)
from onyx.connectors.models import InputType
from onyx.db.connector import fetch_connector_by_id
from onyx.db.credential_capability import (
    get_sources_with_running_capability_runs,
    mark_capability_run_failed,
    mark_stale_capability_runs_failed,
    record_capability_run_progress,
    upsert_completed_capability_report,
)
from onyx.db.credentials import fetch_credential_by_id
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import CapabilityCheckTrigger


def _progress_recorder(
    *, credential_id: int, connector_id: int | None, run_id: UUID
) -> CapabilityCheckProgressCallback:
    """Builds the per-check progress writer for one run attempt.

    Each write opens its own short-lived session: the run can last hours and
    must not hold a connection between checks. Best-effort by design: a failed
    progress write is logged and dropped, because the completion write is the
    run's truth and a poller merely sees progress stall until then.
    """

    def record(results: Sequence[CapabilityCheckResult]) -> None:
        try:
            with get_session_with_current_tenant() as db_session:
                landed = record_capability_run_progress(
                    db_session,
                    credential_id=credential_id,
                    connector_id=connector_id,
                    run_id=run_id,
                    results=results,
                )
                # The accessors leave the transaction to the caller.
                db_session.commit()
        except Exception:
            task_logger.warning(
                f"Could not record capability check progress for credential "
                f"{credential_id}, connector {connector_id} (run {run_id}).",
                exc_info=True,
            )
            return
        if not landed:
            task_logger.info(
                f"Discarded a superseded capability run's progress for "
                f"credential {credential_id}, connector {connector_id} "
                f"(run {run_id})."
            )

    return record


@shared_task(  # ty: ignore[invalid-argument-type]
    name=OnyxCeleryTask.RUN_CAPABILITY_CHECKS,
    bind=True,
)
def run_capability_checks_task(
    self: Task,  # noqa: ARG001
    *,
    credential_id: int,
    connector_id: int | None,
    connector_specific_config: dict[str, Any] | None,
    tenant_id: str | None,
    # Serialized UUID; None only for tasks enqueued before the fence deployed,
    # whose terminal writes then match only their own pre-migration NULL marks.
    run_id: str | None = None,
) -> None:
    """Runs every capability check for the scope and stores the report.

    Terminal writes are fenced on ``run_id``: if this attempt was retired and
    the scope re-triggered, both the completion and the failure write no-op
    instead of mislabeling the successor's row. Progress writes share the fence;
    a legacy task with no ``run_id`` records no progress.
    """
    parsed_run_id = UUID(run_id) if run_id is not None else None
    on_result: CapabilityCheckProgressCallback | None = (
        _progress_recorder(
            credential_id=credential_id,
            connector_id=connector_id,
            run_id=parsed_run_id,
        )
        if parsed_run_id is not None
        else None
    )
    try:
        # Setup reads use a short-lived session: the probes below can run for
        # hours, and an open transaction would hold its connection and read
        # locks for the whole run. ``credential`` stays readable after the close
        # because its columns are already loaded.
        with get_session_with_current_tenant() as db_session:
            credential = fetch_credential_by_id(credential_id, db_session)
            if credential is None:
                # Deleted since the trigger; its report rows cascaded with it.
                task_logger.info(
                    f"Skipping capability checks for deleted credential "
                    f"{credential_id} (tenant {tenant_id})."
                )
                return
            input_type: InputType | None = None
            config = connector_specific_config
            if connector_id is not None:
                connector = fetch_connector_by_id(connector_id, db_session)
                if connector is None:
                    # Deleted since the trigger; its report row cascaded with
                    # it.
                    task_logger.info(
                        f"Skipping capability checks for deleted connector "
                        f"{connector_id} (tenant {tenant_id})."
                    )
                    return
                input_type = connector.input_type
                if config is None:
                    config = connector.connector_specific_config
        report = generate_capability_report(
            credential,
            connector_specific_config=config,
            connector_id=connector_id,
            input_type=input_type,
            trigger=CapabilityCheckTrigger.MANUAL,
            on_result=on_result,
        )
        with get_session_with_current_tenant() as db_session:
            completed_row = upsert_completed_capability_report(
                db_session,
                credential_id=credential_id,
                connector_id=connector_id,
                source=credential.source,
                trigger=CapabilityCheckTrigger.MANUAL,
                report=report,
                connector_config_hash=(
                    compute_connector_config_hash(config)
                    if connector_id is not None
                    else None
                ),
                run_id=parsed_run_id,
            )
            # The accessors leave the transaction to the caller.
            db_session.commit()
        if completed_row is None:
            task_logger.info(
                f"Discarded a superseded capability run's completion for "
                f"credential {credential_id}, connector {connector_id} "
                f"(run {run_id}, tenant {tenant_id})."
            )
    except Exception:
        # The worker is alive, so record the failure now: without this the scope
        # would read RUNNING until the sweep's staleness window expires. Hard
        # kills still rely on the sweep.
        with get_session_with_current_tenant() as db_session:
            mark_capability_run_failed(
                db_session,
                credential_id=credential_id,
                connector_id=connector_id,
                run_id=parsed_run_id,
            )
            db_session.commit()
        raise


@shared_task(  # ty: ignore[invalid-argument-type]
    name=OnyxCeleryTask.CHECK_FOR_STALE_CAPABILITY_RUNS,
    bind=True,
)
def check_for_stale_capability_runs(
    self: Task,  # noqa: ARG001
    *,
    tenant_id: str,
) -> None:
    """Retires RUNNING marks that outlived their source's run ceiling.

    A sweep rather than lazy recovery at trigger time: a re-trigger immediately
    re-marks the scope RUNNING, so only a sweep can surface FAILED_TO_RUN to a
    polling client without user action. A run that is merely slow and completes
    after being retired overwrites FAILED_TO_RUN with its report (the completion
    write is unconditional), so mislabeling self-heals.
    """
    with get_session_with_current_tenant() as db_session:
        for source in get_sources_with_running_capability_runs(db_session):
            retired = mark_stale_capability_runs_failed(
                db_session,
                source=source,
                stale_after=capability_check_run_stale_after(source),
            )
            if retired:
                task_logger.info(
                    f"Retired {retired} stale capability run(s) for source "
                    f"{source.value} to FAILED_TO_RUN (tenant {tenant_id})."
                )
        # The accessors leave the transaction to the caller.
        db_session.commit()
