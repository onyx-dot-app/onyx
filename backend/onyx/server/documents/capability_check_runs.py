"""Starting granular capability-check runs: mark the scope RUNNING, then enqueue."""

from typing import Any
from uuid import UUID, uuid4

from pydantic_core import to_jsonable_python
from sqlalchemy.orm import Session

from onyx.background.celery.versioned_apps.client import app as client_app
from onyx.configs.constants import (
    DocumentSource,
    OnyxCeleryPriority,
    OnyxCeleryQueues,
    OnyxCeleryTask,
)
from onyx.connectors.capability_checks.draft_runs import (
    DRAFT_RUN_TTL_SECONDS,
    DraftCheckRunSnapshot,
    DraftCheckState,
    DraftCheckStateKind,
    DraftRerunMode,
    DraftRunStatus,
    StoredDraftRun,
    apply_cached_result,
    decide_draft_check_state,
    draft_result_cache_key,
    get_cached_draft_result,
    save_draft_run,
    set_latest_draft_run,
)
from onyx.connectors.capability_checks.form_state import validate_form_state
from onyx.connectors.capability_checks.models import CapabilityCheckContext
from onyx.connectors.capability_checks.registry import (
    get_capability_checks,
    has_named_capability_checks,
)
from onyx.connectors.capability_checks.runner import (
    capability_check_run_ceiling_seconds,
    capability_check_run_stale_after,
)
from onyx.connectors.connector_config import ConnectorConfig
from onyx.db.connector import fetch_connector_by_id
from onyx.db.credential_capability import (
    mark_capability_report_running,
    mark_capability_run_failed,
)
from onyx.db.enums import AccessType, CapabilityCheckTrigger
from onyx.db.models import Credential, CredentialCapabilityReportRow
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


def start_draft_capability_check_run(
    *,
    user_id: UUID,
    credential: Credential,
    source: DocumentSource,
    config_class: type[ConnectorConfig],
    access_type: AccessType | None,
    draft_key: str,
    form_values: dict[str, Any],
    rerun: DraftRerunMode = DraftRerunMode.NONE,
) -> DraftCheckRunSnapshot:
    """Decides every check's draft state, fills results from the cache, and
    enqueues one task for the checks that are left. Does no I/O to the source.
    The run replaces any earlier run of the same user and draft key.

    ``rerun`` picks the cached results to ignore: with FAILED, a cached FAILED
    result is run again, so a fix made at the source since the last run shows;
    with ALL, every check runs again. Fresh results still go to the cache.

    Raises:
        CapabilityRunEnqueueError: The broker did not accept the task. The run
            is stored as FAILED_TO_RUN.
    """
    form_state = validate_form_state(config_class, form_values)
    # A form with no values is config-less: config-reading checks wait.
    connector_specific_config = (
        form_values if form_state.provided or form_state.errors else None
    )
    context = CapabilityCheckContext(
        source=source,
        credential_json={},
        connector_specific_config=connector_specific_config,
        access_type=access_type,
    )
    checks: list[DraftCheckState] = []
    result_cache_keys: dict[str, str] = {}
    for check in get_capability_checks(source):
        check_state = decide_draft_check_state(check, context)
        checks.append(check_state)
        if check_state.state != DraftCheckStateKind.PENDING:
            continue
        cache_key = draft_result_cache_key(
            credential_id=credential.id,
            credential_updated_at=credential.time_updated,
            source=source,
            access_type=access_type,
            check=check,
            form_values=(
                form_state.values if connector_specific_config is not None else None
            ),
        )
        cached = (
            None if rerun == DraftRerunMode.ALL else get_cached_draft_result(cache_key)
        )
        if cached is not None and not (
            rerun == DraftRerunMode.FAILED
            and cached.state == DraftCheckStateKind.FAILED
        ):
            apply_cached_result(check_state, cached)
        else:
            result_cache_keys[check.check_id] = cache_key

    has_pending = any(check.state == DraftCheckStateKind.PENDING for check in checks)
    run = StoredDraftRun(
        user_id=user_id,
        snapshot=DraftCheckRunSnapshot(
            run_id=uuid4(),
            draft_key=draft_key,
            source=source,
            credential_id=credential.id,
            access_type=access_type,
            status=DraftRunStatus.RUNNING if has_pending else DraftRunStatus.COMPLETED,
            form_errors=form_state.errors,
            unknown_fields=sorted(form_state.unknown),
            checks=checks,
        ),
        result_cache_keys=result_cache_keys,
    )
    save_draft_run(run)
    set_latest_draft_run(user_id, draft_key, run.snapshot.run_id)
    if not has_pending:
        return run.snapshot
    try:
        client_app.send_task(
            OnyxCeleryTask.RUN_DRAFT_CAPABILITY_CHECKS,
            kwargs={
                "run_id": str(run.snapshot.run_id),
                # The validated values, so the task runs on the config that
                # the result cache keys hash.
                "connector_specific_config": (
                    to_jsonable_python(form_state.values)
                    if connector_specific_config is not None
                    else None
                ),
                "tenant_id": get_current_tenant_id(),
            },
            queue=OnyxCeleryQueues.CAPABILITY_CHECKS,
            priority=OnyxCeleryPriority.HIGH,
            # The stored run expires then, so a later start is useless.
            expires=DRAFT_RUN_TTL_SECONDS,
        )
    except Exception as e:
        logger.exception(
            "Draft capability check enqueue failed for credential %s.", credential.id
        )
        run.snapshot.status = DraftRunStatus.FAILED_TO_RUN
        save_draft_run(run)
        raise CapabilityRunEnqueueError(str(e)) from e
    return run.snapshot
