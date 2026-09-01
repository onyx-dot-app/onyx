"""Celery task running the granular capability checks for one scope.

Enqueued by the capability-check trigger endpoint after it marks the scope's row
RUNNING. Writes through the unconditional upsert: a granular run is the freshest
truth and replaces whatever is stored (see the accessors' writer model). A
task-level crash leaves the row RUNNING; the mark's staleness bound un-blocks
re-triggering.
"""

from typing import Any

from celery import Task, shared_task

from onyx.background.celery.apps.app_base import task_logger
from onyx.configs.constants import OnyxCeleryTask
from onyx.connectors.capability_checks.models import compute_connector_config_hash
from onyx.connectors.capability_checks.runner import generate_capability_report
from onyx.connectors.models import InputType
from onyx.db.connector import fetch_connector_by_id
from onyx.db.credential_capability import upsert_completed_capability_report
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
