"""Starting granular capability-check runs: mark the scope RUNNING, then enqueue."""

from typing import Any

from sqlalchemy.orm import Session

from onyx.background.celery.versioned_apps.client import app as client_app
from onyx.configs.constants import (
    DocumentSource,
    OnyxCeleryPriority,
    OnyxCeleryQueues,
    OnyxCeleryTask,
)
from onyx.connectors.capability_checks.registry import has_named_capability_checks
from onyx.connectors.capability_checks.runner import (
    capability_check_run_ceiling_seconds,
    capability_check_run_stale_after,
)
from onyx.db.connector import fetch_connector_by_id
from onyx.db.credential_capability import (
    mark_capability_report_running,
    mark_capability_run_failed,
)
from onyx.db.enums import CapabilityCheckTrigger
from onyx.db.models import CredentialCapabilityReportRow
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()


class CapabilityRunEnqueueError(Exception):
    """The run could not be enqueued. The scope is already marked FAILED_TO_RUN,
    so an immediate re-trigger is not blocked."""


def start_capability_check_run(
    db_session: Session,
    *,
    credential_id: int,
    connector_id: int | None,
    source: DocumentSource,
    trigger: CapabilityCheckTrigger,
    connector_specific_config: dict[str, Any] | None = None,
) -> CredentialCapabilityReportRow | None:
    """Marks the scope RUNNING and enqueues the run task.

    Returns the RUNNING row, or None when an unexpired run is already in flight
    (nothing is enqueued then). Commits before enqueueing, so the worker can
    only observe the RUNNING mark.

    Raises:
        CapabilityRunEnqueueError: The broker did not accept the task.
    """
    row = mark_capability_report_running(
        db_session,
        credential_id=credential_id,
        connector_id=connector_id,
        source=source,
        trigger=trigger,
        active_within=capability_check_run_stale_after(source),
    )
    if row is None:
        return None
    run_id = row.run_id
    assert run_id is not None, "The RUNNING mark always stamps a run_id."
    db_session.commit()
    try:
        client_app.send_task(
            OnyxCeleryTask.RUN_CAPABILITY_CHECKS,
            kwargs={
                "credential_id": credential_id,
                "connector_id": connector_id,
                "connector_specific_config": connector_specific_config,
                "tenant_id": get_current_tenant_id(),
                # The attempt's fence: the task's terminal writes land only
                # while this id still owns the row.
                "run_id": str(run_id),
                "trigger": trigger.value,
            },
            queue=OnyxCeleryQueues.CAPABILITY_CHECKS,
            priority=OnyxCeleryPriority.HIGH,
            # Queue wait is bounded by one execution ceiling; the staleness
            # cutoff allows for both, so an expired task never strands the
            # scope.
            expires=capability_check_run_ceiling_seconds(source),
        )
    except Exception as e:
        # Broker down and a bad task payload must stay distinguishable in the
        # logs, so record the cause here.
        logger.exception(
            "Capability check enqueue failed for credential %s, connector %s.",
            credential_id,
            connector_id,
        )
        mark_capability_run_failed(
            db_session,
            credential_id=credential_id,
            connector_id=connector_id,
            run_id=run_id,
        )
        db_session.commit()
        raise CapabilityRunEnqueueError(str(e)) from e
    return row


def start_capability_checks_for_new_pairing(
    db_session: Session,
    *,
    credential_id: int,
    connector_id: int,
) -> None:
    """Best-effort background run of the source's named checks for a new or
    re-credentialed pairing; failures are logged and leave the stored
    blocking-validation report in place."""
    try:
        connector = fetch_connector_by_id(connector_id, db_session)
        if connector is None:
            raise ValueError(f"Connector {connector_id} of a new pairing is missing.")
        if not has_named_capability_checks(connector.source):
            return
        start_capability_check_run(
            db_session,
            credential_id=credential_id,
            connector_id=connector_id,
            source=connector.source,
            trigger=CapabilityCheckTrigger.CC_PAIR_VALIDATION,
        )
    except CapabilityRunEnqueueError:
        logger.warning(
            "The full capability run for connector %s, credential %s did not "
            "start; the report keeps the creation-time validation result.",
            connector_id,
            credential_id,
        )
    except Exception:
        logger.exception(
            "The full capability run for connector %s, credential %s could not "
            "be started; the report keeps the creation-time validation result.",
            connector_id,
            credential_id,
        )
        db_session.rollback()
