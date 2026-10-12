"""Celery tasks for the granular capability check runs.

The run task is enqueued by ``send_capability_check_run_task`` after the
caller marks the scope's row RUNNING: from ``start_capability_check_run`` (the
manual trigger endpoint and credential creation), and from cc-pair creation and
credential swap for the checks that did not finish in the blocking budget. It
writes through the unconditional upsert: a granular run is the freshest truth and replaces whatever is stored (see the accessors'
writer model). A run that fails gracefully records FAILED_TO_RUN itself; only
hard kills and expired tasks leave their row RUNNING for the beat sweep to
retire once the mark outlives its source's run ceiling.
"""

from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from celery import Task, shared_task

from onyx.background.celery.apps.app_base import task_logger
from onyx.configs.constants import DocumentSource, OnyxCeleryTask
from onyx.connectors.capability_checks.draft_runs import (
    DRAFT_CHECK_TIMEOUT_SECONDS,
    DRAFT_RUN_TTL_SECONDS,
    DraftCheckState,
    DraftCheckStateKind,
    DraftRunPairScope,
    DraftRunStatus,
    apply_check_result,
    cache_draft_result,
    cached_check_result,
    clear_draft_result_in_flight,
    form_draft_result_keys,
    is_draft_result_in_flight,
    is_superseded,
    load_draft_run,
    mark_draft_results_in_flight,
    save_draft_run,
    wait_for_draft_result,
)
from onyx.connectors.capability_checks.form_state import validate_form_state
from onyx.connectors.capability_checks.models import CapabilityCheckResult
from onyx.connectors.capability_checks.registry import get_capability_checks
from onyx.connectors.capability_checks.runner import (
    CAPABILITY_CHECK_TIMEOUT_SECONDS,
    capability_check_run_stale_after,
    effective_check_timeout_seconds,
    generate_capability_report,
    merge_capability_results,
)
from onyx.connectors.config_hash import compute_connector_config_hash
from onyx.connectors.models import InputType
from onyx.connectors.registry import CONNECTOR_CLASS_MAP
from onyx.db.connector import fetch_connector_by_id
from onyx.db.connector_credential_pair import get_connector_credential_pair
from onyx.db.credential_capability import (
    get_sources_with_running_capability_runs,
    mark_capability_run_failed,
    mark_stale_capability_runs_failed,
    upsert_completed_capability_report,
)
from onyx.db.credentials import (
    delete_stale_draft_credentials,
    fetch_credential_by_id,
)
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import AccessType, CapabilityCheckTrigger
from onyx.db.models import Credential


def _await_draft_results(
    check_ids: list[str],
    *,
    credential: Credential,
    source: DocumentSource,
    access_type: AccessType | None,
    connector_specific_config: dict[str, Any] | None,
) -> tuple[list[CapabilityCheckResult], list[str]]:
    """The results a create-form draft run of the same form is still to write
    for ``check_ids``, awaited up to each check's draft timeout, and the ids
    of the checks that still need to run."""
    checks = get_capability_checks(source)
    keys = form_draft_result_keys(
        [check for check in checks if check.check_id in check_ids],
        credential_id=credential.id,
        credential_updated_at=credential.time_updated,
        source=source,
        access_type=access_type,
        form_values=validate_form_state(
            CONNECTOR_CLASS_MAP[source].config_class, connector_specific_config or {}
        ).values,
        cc_pair_id=None,
    )
    awaited: list[CapabilityCheckResult] = []
    to_run: list[str] = []
    for check_id in check_ids:
        key = keys.get(check_id)
        cached = (
            wait_for_draft_result(key, DRAFT_CHECK_TIMEOUT_SECONDS)
            if key is not None and is_draft_result_in_flight(key)
            else None
        )
        if cached is None:
            to_run.append(check_id)
            continue
        awaited.extend(
            cached_check_result(check, cached)
            for check in checks
            if check.check_id == check_id
        )
    return awaited, to_run


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
    # What started the run. Defaults to MANUAL for tasks enqueued before this
    # argument existed.
    trigger: str = CapabilityCheckTrigger.MANUAL.value,
    # The pair's access type, for a run started before the pair exists.
    access_type: str | None = None,
    # Limits the run to these checks; ``prior_results`` hold the results of
    # the others, which the stored report includes.
    check_ids: list[str] | None = None,
    prior_results: list[dict[str, Any]] | None = None,
) -> None:
    """Runs the capability checks for the scope and stores the report.

    Terminal writes are fenced on ``run_id``: if this attempt was retired and
    the scope re-triggered, both the completion and the failure write no-op
    instead of mislabeling the successor's row.
    """
    parsed_run_id = UUID(run_id) if run_id is not None else None
    parsed_trigger = CapabilityCheckTrigger(trigger)
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
            parsed_access_type = (
                AccessType(access_type) if access_type is not None else None
            )
            config = connector_specific_config
            # A family credential can serve connectors of other sources, so a
            # connector-scoped run checks the connector's source.
            source = credential.source
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
                source = connector.source
                if config is None:
                    config = connector.connector_specific_config
                # Checks outside the pair's access type are skipped as not
                # applicable. A run before the pair exists runs them all.
                cc_pair = get_connector_credential_pair(
                    db_session, connector_id, credential_id
                )
                if cc_pair is not None and parsed_access_type is None:
                    parsed_access_type = cc_pair.access_type
        # A run of the checks creation left unfinished first waits for the
        # ones a draft run of the same form is still running.
        awaited_results: list[CapabilityCheckResult] = []
        run_check_ids = check_ids
        if check_ids is not None:
            awaited_results, run_check_ids = _await_draft_results(
                check_ids,
                credential=credential,
                source=source,
                access_type=parsed_access_type,
                connector_specific_config=config,
            )
        report = generate_capability_report(
            credential,
            source=source,
            connector_specific_config=config,
            connector_id=connector_id,
            input_type=input_type,
            trigger=parsed_trigger,
            access_type=parsed_access_type,
            check_ids=frozenset(run_check_ids) if run_check_ids is not None else None,
        )
        merged_prior: list[CapabilityCheckResult] = [
            *awaited_results,
            *(
                CapabilityCheckResult.model_validate(result)
                for result in prior_results or []
            ),
        ]
        if merged_prior:
            report = merge_capability_results(report, merged_prior)
        with get_session_with_current_tenant() as db_session:
            completed_row = upsert_completed_capability_report(
                db_session,
                credential_id=credential_id,
                connector_id=connector_id,
                source=source,
                trigger=parsed_trigger,
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


class _DraftRunSupersededError(Exception):
    """A newer run for the same draft key started; this run stops."""


@shared_task(  # ty: ignore[invalid-argument-type]
    name=OnyxCeleryTask.RUN_DRAFT_CAPABILITY_CHECKS,
    bind=True,
)
def run_draft_capability_checks_task(
    self: Task,  # noqa: ARG001
    *,
    run_id: str,
    connector_specific_config: dict[str, Any] | None,
    tenant_id: str | None,
) -> None:
    """Runs a draft run's PENDING checks and writes each result into the stored
    run as it lands. The task is the only writer of the run after its start.
    Before each next check it stops if a newer run for the same draft key
    started. A dry run of a pair builds the connector with the pair's input
    type, as creation does."""
    run = load_draft_run(UUID(run_id))
    if run is None:
        task_logger.info(f"Draft capability run {run_id} expired (tenant {tenant_id}).")
        return
    snapshot = run.snapshot
    # In the order the runner executes them: discovery checks last.
    pending: list[DraftCheckState] = sorted(
        (
            check
            for check in snapshot.checks
            if check.state == DraftCheckStateKind.PENDING
        ),
        key=lambda check: check.discovery,
    )
    pending_result_keys: list[str] = list(
        dict.fromkeys(run.result_cache_keys[check.check_id] for check in pending)
    )
    timeout_by_check_id = {
        check.check_id: min(
            effective_check_timeout_seconds(check), DRAFT_CHECK_TIMEOUT_SECONDS
        )
        for check in get_capability_checks(snapshot.source)
    }

    def mark_next_running() -> None:
        if (
            next_check := next(
                (c for c in pending if c.state == DraftCheckStateKind.PENDING), None
            )
        ) is not None:
            next_check.state = DraftCheckStateKind.RUNNING
            # The check's hang guard, plus the guard of a connector
            # instantiation that can run before it.
            run.renew_lease(
                timeout_by_check_id[next_check.check_id]
                + min(CAPABILITY_CHECK_TIMEOUT_SECONDS, DRAFT_CHECK_TIMEOUT_SECONDS)
            )

    def on_result(results: Sequence[CapabilityCheckResult]) -> None:
        result = results[-1]
        check_state = next(
            check
            for check in pending
            if check.check_id == result.check_id
            and check.capability == result.capability
        )
        apply_check_result(check_state, result)
        result_key = run.result_cache_keys[result.check_id]
        cache_draft_result(result_key, result)
        clear_draft_result_in_flight(result_key)
        if is_superseded(run):
            raise _DraftRunSupersededError()
        mark_next_running()
        save_draft_run(run)

    try:
        if is_superseded(run):
            raise _DraftRunSupersededError()
        with get_session_with_current_tenant() as db_session:
            credential = fetch_credential_by_id(snapshot.credential_id, db_session)
        if credential is None:
            task_logger.info(
                f"Draft capability run {run_id} stopped: credential "
                f"{snapshot.credential_id} was deleted (tenant {tenant_id})."
            )
            snapshot.status = DraftRunStatus.FAILED_TO_RUN
            save_draft_run(run)
            return
        # A validation of the same form waits for these results instead of
        # running the checks again.
        mark_draft_results_in_flight(pending_result_keys, DRAFT_RUN_TTL_SECONDS)
        mark_next_running()
        save_draft_run(run)
        pair_scope: DraftRunPairScope | None = run.pair_scope
        generate_capability_report(
            credential,
            source=snapshot.source,
            connector_specific_config=connector_specific_config,
            connector_id=pair_scope.connector_id if pair_scope is not None else None,
            input_type=pair_scope.input_type if pair_scope is not None else None,
            access_type=snapshot.access_type,
            on_result=on_result,
            check_ids=frozenset(check.check_id for check in pending),
            timeout_cap_seconds=DRAFT_CHECK_TIMEOUT_SECONDS,
        )
        snapshot.status = DraftRunStatus.COMPLETED
        save_draft_run(run)
    except _DraftRunSupersededError:
        task_logger.info(
            f"Draft capability run {run_id} stopped: a newer run for its draft "
            f"key started (tenant {tenant_id})."
        )
        snapshot.status = DraftRunStatus.SUPERSEDED
        save_draft_run(run)
    except Exception:
        snapshot.status = DraftRunStatus.FAILED_TO_RUN
        save_draft_run(run)
        raise
    finally:
        # A check the run did not finish is not coming.
        for result_key in pending_result_keys:
            clear_draft_result_in_flight(result_key)


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


# Far longer than any form session: a draft is changed on every edit.
DRAFT_CREDENTIAL_MAX_AGE = timedelta(days=7)


@shared_task(
    name=OnyxCeleryTask.CLEANUP_STALE_DRAFT_CREDENTIALS, ignore_result=True, trail=False
)
def cleanup_stale_draft_credentials(*, tenant_id: str) -> None:
    """Deletes draft credentials of connector forms that were never
    submitted."""
    with get_session_with_current_tenant() as db_session:
        deleted = delete_stale_draft_credentials(
            db_session,
            updated_before=datetime.now(timezone.utc) - DRAFT_CREDENTIAL_MAX_AGE,
        )
    if deleted:
        task_logger.info(
            f"Deleted {deleted} stale draft credential(s) (tenant {tenant_id})."
        )
