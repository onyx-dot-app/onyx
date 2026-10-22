"""Enqueueing the stored capability-check run task."""

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from onyx.background.celery.versioned_apps.client import app as client_app
from onyx.configs.constants import (
    DocumentSource,
    OnyxCeleryPriority,
    OnyxCeleryQueues,
    OnyxCeleryTask,
)
from onyx.connectors.capability_checks.models import CapabilityCheckResult
from onyx.connectors.capability_checks.runner import (
    capability_check_run_ceiling_seconds,
)
from onyx.db.enums import AccessType, CapabilityCheckTrigger
from shared_configs.contextvars import get_current_tenant_id


def send_capability_check_run_task(
    *,
    credential_id: int,
    connector_id: int | None,
    source: DocumentSource,
    trigger: CapabilityCheckTrigger,
    run_id: UUID,
    connector_specific_config: dict[str, Any] | None = None,
    access_type: AccessType | None = None,
    check_ids: frozenset[str] | None = None,
    prior_results: Sequence[CapabilityCheckResult] = (),
) -> None:
    """Enqueues the run task for a scope the caller already marked RUNNING
    with ``run_id``. ``check_ids`` limits the run, and ``prior_results`` are
    the results of the other checks, which the task stores with its own.
    Raises whatever the broker raises."""
    kwargs: dict[str, Any] = {
        "credential_id": credential_id,
        "connector_id": connector_id,
        "connector_specific_config": connector_specific_config,
        "tenant_id": get_current_tenant_id(),
        # The attempt's fence: the task's terminal writes land only while this
        # id still owns the row.
        "run_id": str(run_id),
        "trigger": trigger.value,
    }
    # Sent only when set, so a full run's payload stays readable by workers
    # that predate these arguments.
    if access_type is not None:
        kwargs["access_type"] = access_type.value
    if check_ids is not None:
        kwargs["check_ids"] = sorted(check_ids)
        kwargs["prior_results"] = [
            result.model_dump(mode="json") for result in prior_results
        ]
    client_app.send_task(
        OnyxCeleryTask.RUN_CAPABILITY_CHECKS,
        kwargs=kwargs,
        queue=OnyxCeleryQueues.CAPABILITY_CHECKS,
        priority=OnyxCeleryPriority.HIGH,
        # Queue wait is bounded by one execution ceiling; the staleness
        # cutoff allows for both, so an expired task never strands the
        # scope.
        expires=capability_check_run_ceiling_seconds(source),
    )
