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
    DraftCheckActions,
    DraftCheckPlan,
    DraftCheckRunSnapshot,
    DraftCheckState,
    DraftCheckStateKind,
    DraftRerunMode,
    DraftRunPairScope,
    DraftRunStatus,
    StoredDraftRun,
    apply_cached_result,
    cache_user_skip,
    cc_pair_draft_key,
    clear_latest_draft_run,
    decide_draft_check_state,
    draft_result_cache_key,
    draft_run_start_lock,
    get_cached_draft_result,
    is_superseded,
    kept_draft_state,
    load_draft_run,
    load_latest_draft_run,
    save_draft_run,
    set_latest_draft_run,
    skip_draft_check,
    wait_for_dependencies,
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
from onyx.connectors.factory import assert_user_can_use_credential
from onyx.connectors.registry import CONNECTOR_CLASS_MAP, ConnectorMapping
from onyx.db.connector import fetch_connector_by_id
from onyx.db.connector_credential_pair import (
    get_connector_credential_pair,
    get_connector_credential_pair_from_id,
)
from onyx.db.credential_capability import (
    mark_capability_report_running,
    mark_capability_run_failed,
)
from onyx.db.credentials import fetch_credential_by_id
from onyx.db.enums import AccessType, CapabilityCheckTrigger
from onyx.db.models import Credential, CredentialCapabilityReportRow, User
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


def _assert_user_can_run_stored_checks(
    db_session: Session,
    *,
    user: User,
    credential_id: int,
    connector_id: int | None,
    source: DocumentSource,
    connector_specific_config: dict[str, Any] | None,
) -> None:
    """``assert_user_can_use_credential`` for a stored-report run. A
    connector-scoped run without an override uses the connector's stored config,
    so the existing pair counts as the user's own use."""
    credential = fetch_credential_by_id(credential_id, db_session)
    if credential is None:
        raise OnyxError(
            OnyxErrorCode.CREDENTIAL_NOT_FOUND,
            f"Credential {credential_id} does not exist or is not accessible.",
        )
    config = connector_specific_config
    current_pair = None
    if connector_id is not None:
        connector = fetch_connector_by_id(connector_id, db_session)
        if connector is None:
            raise OnyxError(
                OnyxErrorCode.CONNECTOR_NOT_FOUND,
                f"Connector {connector_id} does not exist or is not accessible.",
            )
        if config is None:
            config = connector.connector_specific_config
            current_pair = get_connector_credential_pair(
                db_session, connector_id, credential_id
            )
    assert_user_can_use_credential(
        db_session,
        user=user,
        credential=credential,
        source=source,
        connector_specific_config=config,
        current_pair=current_pair,
    )


def start_capability_check_run(
    db_session: Session,
    *,
    user: User | None,
    credential_id: int,
    connector_id: int | None,
    source: DocumentSource,
    trigger: CapabilityCheckTrigger,
    connector_specific_config: dict[str, Any] | None = None,
) -> CredentialCapabilityReportRow | None:
    """Marks the scope RUNNING and enqueues the run task.

    ``user`` is who asks for the run, held to ``assert_user_can_use_credential``
    with the config the run uses; None only for system triggers. The caller
    authorizes the user for the connector's pair.

    Returns the RUNNING row, or None when an unexpired run is already in flight
    (nothing is enqueued then). Commits before enqueueing, so the worker can
    only observe the RUNNING mark.

    Raises:
        OnyxError: The user may not use the credential with this config.
        CapabilityRunEnqueueError: The broker did not accept the task.
    """
    if user is not None:
        _assert_user_can_run_stored_checks(
            db_session,
            user=user,
            credential_id=credential_id,
            connector_id=connector_id,
            source=source,
            connector_specific_config=connector_specific_config,
        )
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
            error_message=str(e),
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
            user=None,
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
    # None for a config-less create form: config-reading checks wait.
    connector_specific_config: dict[str, Any] | None
    checks: list[tuple[CapabilityCheck[Any], DraftCheckState]]


def _plan_draft(
    *,
    source: DocumentSource,
    config_class: type[ConnectorConfig],
    access_type: AccessType | None,
    form_values: dict[str, Any],
    config_is_complete: bool = False,
) -> _PlannedDraft:
    """Decides each check's state before it runs. Reads no credential and does
    no I/O to the source.

    A create form with no values is config-less, and config-reading checks
    wait, unless the defaults alone make a complete config (a source whose
    fields all have defaults, such as Linear). With ``config_is_complete`` (a
    pair's proposed config), {} selects the defaults."""
    form_state = validate_form_state(config_class, form_values)
    connector_specific_config: dict[str, Any] | None = (
        form_values
        if config_is_complete
        or form_state.provided
        or form_state.errors
        or form_state.complete is not None
        else None
    )
    context = CapabilityCheckContext(
        source=source,
        credential_json={},
        connector_specific_config=connector_specific_config,
        access_type=access_type,
    )
    checks: list[tuple[CapabilityCheck[Any], DraftCheckState]] = [
        (check, decide_draft_check_state(check, context))
        for check in get_capability_checks(source)
    ]
    wait_for_dependencies(checks)
    return _PlannedDraft(
        form_state=form_state,
        connector_specific_config=connector_specific_config,
        checks=checks,
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


def validate_draft_check_actions(
    actions: DraftCheckActions,
    checks: list[CapabilityCheck[Any]],
    rerun: DraftRerunMode,
) -> None:
    """Rejects actions that name a check the source does not have, or that
    contradict each other.

    Raises:
        OnyxError: INVALID_INPUT, with the reason.
    """
    run_ids = set(actions.check_ids or ())
    skip_ids = set(actions.skip_check_ids)
    named = run_ids | skip_ids
    if actions.start_check_id is not None:
        named.add(actions.start_check_id)
    unknown = named - {check.check_id for check in checks}
    if unknown:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"Unknown capability checks: {', '.join(sorted(unknown))}.",
        )
    if actions.check_ids is not None and not run_ids:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT, "check_ids must name at least one check."
        )
    if both := run_ids & skip_ids:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"Checks to run and to skip at once: {', '.join(sorted(both))}.",
        )
    if actions.start_check_id in skip_ids:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"The check to start now is skipped: {actions.start_check_id}.",
        )
    if actions.check_ids is not None and rerun != DraftRerunMode.NONE:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "check_ids picks the checks to run again; send it without rerun.",
        )


def start_draft_capability_check_run(
    db_session: Session,
    *,
    user: User,
    credential: Credential,
    source: DocumentSource,
    config_class: type[ConnectorConfig],
    access_type: AccessType | None,
    draft_key: str,
    form_values: dict[str, Any],
    rerun: DraftRerunMode = DraftRerunMode.NONE,
    actions: DraftCheckActions | None = None,
    pair_scope: DraftRunPairScope | None = None,
) -> DraftCheckRunSnapshot:
    """Decides every check's draft state, fills results from the cache, and
    enqueues one task for the checks that are left. Does no I/O to the source.
    The run replaces any earlier run of the same user and draft key.
    ``pair_scope`` makes the run a dry run of an existing pair. The user must
    pass ``assert_user_can_use_credential`` with the form's config; the pair
    of ``pair_scope`` counts as their own use.

    ``rerun`` picks the cached results to ignore: with FAILED, a cached FAILED
    result is run again, so a fix made at the source since the last run shows;
    with ALL, every check runs again. Fresh results still go to the cache.

    ``actions`` are the admin's per-check actions (``DraftCheckActions``);
    None runs every check. A skip applies to a check that could run. The skip of an optional check is
    cached, so creation on the same form honors it.

    Raises:
        CapabilityRunEnqueueError: The broker did not accept the task. The run
            is stored as FAILED_TO_RUN.
        OnyxError: The actions are not valid, the user may not use the
            credential with this config, or a concurrent start of the same
            draft key held the start lock for too long.
    """
    actions = actions or DraftCheckActions()
    validate_draft_check_actions(actions, get_capability_checks(source), rerun)
    user_id = user.id
    plan = _plan_draft(
        config_is_complete=pair_scope is not None,
        source=source,
        config_class=config_class,
        access_type=access_type,
        form_values=form_values,
    )
    form_state = plan.form_state
    connector_specific_config = plan.connector_specific_config
    assert_user_can_use_credential(
        db_session,
        user=user,
        credential=credential,
        source=source,
        # The values the task runs on.
        connector_specific_config=(
            form_state.values if connector_specific_config is not None else None
        ),
        current_pair=(
            get_connector_credential_pair_from_id(
                db_session, pair_scope.cc_pair_id, eager_load_connector=True
            )
            if pair_scope is not None
            else None
        ),
    )
    run_ids: set[str] | None = (
        set(actions.check_ids) if actions.check_ids is not None else None
    )
    skip_ids = set(actions.skip_check_ids)
    # A run of chosen checks keeps the other results of the latest run.
    prior = load_latest_draft_run(user_id, draft_key) if run_ids is not None else None
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
        result_cache_keys[check.check_id] = cache_key
        if check.check_id in skip_ids:
            skip_draft_check(check_state)
            cache_user_skip(cache_key, check_state)
            continue
        if run_ids is not None and check.check_id in run_ids:
            continue
        cached = (
            None if rerun == DraftRerunMode.ALL else get_cached_draft_result(cache_key)
        )
        # A cached skip holds only while the request still skips the check.
        if cached is not None and cached.skipped_by_user:
            cached = None
        if cached is not None and not (
            rerun == DraftRerunMode.FAILED
            and cached.state == DraftCheckStateKind.FAILED
        ):
            apply_cached_result(check_state, cached)
            continue
        if run_ids is not None and (
            kept := kept_draft_state(prior, check_state, cache_key)
        ):
            checks[-1] = kept

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
        first_check_id=actions.start_check_id,
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
    user: User,
    cc_pair_id: int,
    proposed_credential: Credential | None,
    access_type: AccessType,
    connector_specific_config: dict[str, Any],
    rerun: DraftRerunMode = DraftRerunMode.NONE,
    actions: DraftCheckActions | None = None,
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
    mapping: ConnectorMapping | None = CONNECTOR_CLASS_MAP.get(connector.source)
    if mapping is None:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"{connector.source.value} has no connector configuration.",
        )
    return start_draft_capability_check_run(
        db_session,
        user=user,
        credential=proposed_credential or cc_pair.credential,
        source=connector.source,
        config_class=mapping.config_class,
        access_type=access_type,
        draft_key=cc_pair_draft_key(cc_pair_id),
        form_values=connector_specific_config,
        rerun=rerun,
        actions=actions,
        pair_scope=DraftRunPairScope(
            cc_pair_id=cc_pair_id,
            connector_id=connector.id,
            input_type=connector.input_type,
        ),
    )


def cancel_draft_capability_check_run(*, run_id: UUID, user_id: UUID) -> bool:
    """Stops a draft run the user started: it reads as SUPERSEDED, and its task
    stops before its next check. A check already running still finishes.

    Returns False when the run expired or another user started it. A run a
    newer run already replaced is left alone, so the newer one keeps going.
    """
    run = load_draft_run(run_id)
    if run is None or run.user_id != user_id:
        return False
    start_lock = draft_run_start_lock(user_id, run.snapshot.draft_key)
    if not start_lock.acquire(blocking_timeout=_DRAFT_START_LOCK_WAIT_SECONDS):
        raise OnyxError(
            OnyxErrorCode.SERVICE_UNAVAILABLE,
            "A check run for this form is starting; try again shortly.",
        )
    try:
        if not is_superseded(run):
            clear_latest_draft_run(run)
    finally:
        start_lock.release()
    return True
