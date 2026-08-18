"""Celery tasks for the granular capability check runs.

The run task is enqueued by the capability-check trigger endpoint after it
marks the scope's row RUNNING, and writes through the unconditional upsert: a
granular run is the freshest truth and replaces whatever is stored (see the
accessors' writer model). A crashed or expired run leaves its row RUNNING; the
beat sweep retires such marks to FAILED_TO_RUN once they outlive their
source's run ceiling.
"""

from typing import Any

from celery import Task, shared_task

from onyx.background.celery.apps.app_base import task_logger
from onyx.configs.constants import OnyxCeleryTask
from onyx.connectors.capability_checks.models import compute_connector_config_hash
from onyx.connectors.capability_checks.runner import (
    capability_check_run_stale_after,
    generate_capability_report,
)
from onyx.connectors.models import InputType
from onyx.db.connector import fetch_connector_by_id
from onyx.db.credential_capability import (
    get_sources_with_running_capability_runs,
    mark_stale_capability_runs_failed,
    upsert_completed_capability_report,
)
from onyx.db.credentials import fetch_credential_by_id
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import CapabilityCheckTrigger


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
) -> None:
    """Runs every capability check for the scope and stores the report."""
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
                # Deleted since the trigger; its report row cascaded with it.
                task_logger.info(
                    f"Skipping capability checks for deleted connector "
                    f"{connector_id} (tenant {tenant_id})."
                )
                return
            input_type = connector.input_type
            if config is None:
                config = connector.connector_specific_config
        report = generate_capability_report(
            db_session,
            credential,
            connector_specific_config=config,
            connector_id=connector_id,
            input_type=input_type,
            trigger=CapabilityCheckTrigger.MANUAL,
        )
        upsert_completed_capability_report(
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
        )
        # The accessors leave the transaction to the caller.
        db_session.commit()


@shared_task(  # ty: ignore[invalid-argument-type]
    name=OnyxCeleryTask.CHECK_FOR_STALE_CAPABILITY_RUNS,
    soft_time_limit=300,
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
    after being retired overwrites FAILED_TO_RUN with its report (the
    completion write is unconditional), so mislabeling self-heals.
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
