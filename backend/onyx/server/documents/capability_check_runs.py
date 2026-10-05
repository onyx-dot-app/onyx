"""Starting granular capability-check runs: mark the scope RUNNING, then enqueue."""

from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

from pydantic_core import to_jsonable_python
from sqlalchemy.orm import Session

from onyx.background.celery.tasks.capability_checks.enqueue import (
    send_capability_check_run_task,
)
from onyx.background.celery.versioned_apps.client import app as client_app
from onyx.configs.constants import (
    DocumentSource,
    OnyxCeleryPriority,
    OnyxCeleryQueues,
    OnyxCeleryTask,
)
from onyx.connectors.capability_checks.draft_runs import (
    DRAFT_RUN_QUEUE_EXPIRY_SECONDS,
    DraftCheckPlan,
    DraftCheckRunSnapshot,
    DraftCheckState,
    DraftCheckStateKind,
    DraftRerunMode,
    DraftRunPairScope,
    DraftRunStatus,
    StoredDraftRun,
    apply_cached_result,
    cc_pair_draft_key,
    decide_draft_check_state,
    draft_result_cache_key,
    draft_run_start_lock,
    get_cached_draft_result,
    save_draft_run,
    set_latest_draft_run,
)
from onyx.connectors.capability_checks.form_state import (
    FormState,
    validate_form_state,
)
from onyx.connectors.capability_checks.models import (
    CapabilityCheck,
    CapabilityCheckContext,
)
from onyx.connectors.capability_checks.registry import (
    get_capability_checks,
    has_named_capability_checks,
)
from onyx.connectors.capability_checks.runner import (
    capability_check_run_stale_after,
)
from onyx.connectors.connector_config import ConnectorConfig
from onyx.connectors.registry import CONNECTOR_CLASS_MAP
from onyx.db.connector_credential_pair import get_connector_credential_pair_from_id
from onyx.db.credential_capability import (
    mark_capability_report_running,
    mark_capability_run_failed,
)
from onyx.db.enums import AccessType, CapabilityCheckTrigger
from onyx.db.models import Credential, CredentialCapabilityReportRow
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()

_ENQUEUE_MARGIN_SECONDS = 60
# How long a draft start waits for a concurrent start of the same draft key.
_DRAFT_START_LOCK_WAIT_SECONDS = 10


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
        send_capability_check_run_task(
            credential_id=credential_id,
            connector_id=connector_id,
            source=source,
            trigger=trigger,
            run_id=run_id,
            connector_specific_config=connector_specific_config,
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


def start_capability_checks_for_new_credential(
    db_session: Session, credential: Credential
) -> None:
    """After a credential is created, runs its source's credential-scoped
    checks in the background, so the token checks have a result before any
    connector form is filled. Best-effort: the credential is already created,
    so any failure here is logged, the session is rolled back, and creation
    still succeeds."""
    credential_id = credential.id
    source = credential.source
    try:
        if not has_named_capability_checks(source):
            return
        start_capability_check_run(
            db_session,
            credential_id=credential_id,
            connector_id=None,
            source=source,
            trigger=CapabilityCheckTrigger.CREDENTIAL_CREATED,
        )
    except CapabilityRunEnqueueError:
        logger.warning(
            "The capability run for new credential %s did not start.", credential_id
        )
    except Exception:
        logger.exception(
            "The capability run for new credential %s could not be started.",
            credential_id,
        )
        db_session.rollback()


@dataclass(frozen=True)
class _PlannedDraft:
    form_state: FormState[Any]
    # None for a form with no values: config-reading checks wait.
    connector_specific_config: dict[str, Any] | None
    checks: list[tuple[CapabilityCheck[Any], DraftCheckState]]


def _plan_draft(
    *,
    source: DocumentSource,
    config_class: type[ConnectorConfig],
    access_type: AccessType | None,
    form_values: dict[str, Any],
) -> _PlannedDraft:
    """Decides each check's state before it runs. Reads no credential and does
    no I/O to the source."""
    form_state = validate_form_state(config_class, form_values)
    connector_specific_config = (
        form_values if form_state.provided or form_state.errors else None
    )
    context = CapabilityCheckContext(
        source=source,
        credential_json={},
        connector_specific_config=connector_specific_config,
        access_type=access_type,
    )
    return _PlannedDraft(
        form_state=form_state,
        connector_specific_config=connector_specific_config,
        checks=[
            (check, decide_draft_check_state(check, context))
            for check in get_capability_checks(source)
        ],
    )


def plan_draft_capability_checks(
    *,
    source: DocumentSource,
    config_class: type[ConnectorConfig],
    access_type: AccessType | None,
    form_values: dict[str, Any],
) -> DraftCheckPlan:
    """The checks a draft run would hold for this form, each in its state
    before anything runs. Needs no credential, does no I/O to the source, and
    starts no run."""
    plan = _plan_draft(
        source=source,
        config_class=config_class,
        access_type=access_type,
        form_values=form_values,
    )
    return DraftCheckPlan(
        source=source,
        access_type=access_type,
        form_errors=plan.form_state.errors,
        unknown_fields=sorted(plan.form_state.unknown),
        checks=[state for _, state in plan.checks],
    )


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
    pair_scope: DraftRunPairScope | None = None,
) -> DraftCheckRunSnapshot:
    """Decides every check's draft state, fills results from the cache, and
    enqueues one task for the checks that are left. Does no I/O to the source.
    The run replaces any earlier run of the same user and draft key.
    ``pair_scope`` makes the run a dry run of an existing pair.

    ``rerun`` picks the cached results to ignore: with FAILED, a cached FAILED
    result is run again, so a fix made at the source since the last run shows;
    with ALL, every check runs again. Fresh results still go to the cache.

    Raises:
        CapabilityRunEnqueueError: The broker did not accept the task. The run
            is stored as FAILED_TO_RUN.
        OnyxError: A concurrent start of the same draft key held the start
            lock for too long.
    """
    plan = _plan_draft(
        source=source,
        config_class=config_class,
        access_type=access_type,
        form_values=form_values,
    )
    form_state = plan.form_state
    connector_specific_config = plan.connector_specific_config
    checks: list[DraftCheckState] = []
    result_cache_keys: dict[str, str] = {}
    for check, check_state in plan.checks:
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
            cc_pair_id=pair_scope.cc_pair_id if pair_scope is not None else None,
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
        pair_scope=pair_scope,
    )
    if has_pending:
        # The task can wait in the queue this long, plus a margin for the
        # enqueue itself.
        run.renew_lease(DRAFT_RUN_QUEUE_EXPIRY_SECONDS + _ENQUEUE_MARGIN_SECONDS)
    start_lock = draft_run_start_lock(user_id, draft_key)
    if not start_lock.acquire(blocking_timeout=_DRAFT_START_LOCK_WAIT_SECONDS):
        raise OnyxError(
            OnyxErrorCode.SERVICE_UNAVAILABLE,
            "Another check run for this form is starting; try again shortly.",
        )
    try:
        save_draft_run(run)
        set_latest_draft_run(run)
    finally:
        start_lock.release()
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
            queue=OnyxCeleryQueues.CAPABILITY_CHECKS_DRAFT,
            priority=OnyxCeleryPriority.HIGH,
            # The run's lease runs out then, so a later start is useless.
            expires=DRAFT_RUN_QUEUE_EXPIRY_SECONDS,
        )
    except Exception as e:
        logger.exception(
            "Draft capability check enqueue failed for credential %s.", credential.id
        )
        run.snapshot.status = DraftRunStatus.FAILED_TO_RUN
        save_draft_run(run)
        raise CapabilityRunEnqueueError(str(e)) from e
    return run.snapshot


def start_cc_pair_draft_check_run(
    db_session: Session,
    *,
    user_id: UUID,
    cc_pair_id: int,
    proposed_credential: Credential | None,
    access_type: AccessType,
    connector_specific_config: dict[str, Any],
    rerun: DraftRerunMode = DraftRerunMode.NONE,
) -> DraftCheckRunSnapshot:
    """Starts a dry run of the capability checks for a proposed state of an
    existing pair. Like a create-form draft run, it never writes a stored
    report; the checks get the pair's connector, as at creation.
    ``proposed_credential`` None keeps the pair's credential. The caller
    authorizes the user for the pair and the proposed credential.

    Raises:
        OnyxError: The pair does not exist, or its source has no connector
            configuration.
        CapabilityRunEnqueueError: As for a create-form draft run.
    """
    cc_pair = get_connector_credential_pair_from_id(
        db_session, cc_pair_id, eager_load_connector=True, eager_load_credential=True
    )
    if cc_pair is None:
        raise OnyxError(
            OnyxErrorCode.CONNECTOR_NOT_FOUND,
            f"Connector-credential pair {cc_pair_id} does not exist.",
        )
    connector = cc_pair.connector
    mapping = CONNECTOR_CLASS_MAP.get(connector.source)
    if mapping is None:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"{connector.source.value} has no connector configuration.",
        )
    return start_draft_capability_check_run(
        user_id=user_id,
        credential=proposed_credential or cc_pair.credential,
        source=connector.source,
        config_class=mapping.config_class,
        access_type=access_type,
        draft_key=cc_pair_draft_key(cc_pair_id),
        form_values=connector_specific_config,
        rerun=rerun,
        pair_scope=DraftRunPairScope(
            cc_pair_id=cc_pair_id,
            connector_id=connector.id,
            input_type=connector.input_type,
        ),
    )
