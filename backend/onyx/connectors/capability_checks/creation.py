"""Named capability checks when a cc-pair is created or its credential swapped.

For a source with named checks, this replaces the legacy blocking validation
(``validate_connector_settings`` and ``validate_perm_sync``). It runs the
source's checks for the pairing's access type and stores the full report. A
fresh result of a draft run on the same form is reused, so the check does not
run again. Only a required check that failed within the blocking budget blocks
the pairing: INDETERMINATE is transient, and skipped checks do not apply. A
check that is still running at the end of the budget does not block; a
background run produces its result.
"""

from datetime import datetime, timedelta, timezone
from functools import partial
from typing import Any
from uuid import UUID

from onyx.background.celery.tasks.capability_checks.enqueue import (
    send_capability_check_run_task,
)
from onyx.configs.constants import DocumentSource
from onyx.connectors.capability_checks.draft_runs import (
    CachedDraftResult,
    DraftCheckStateKind,
    cached_check_result,
    draft_result_cache_key,
    get_cached_draft_result,
)
from onyx.connectors.capability_checks.form_state import validate_form_state
from onyx.connectors.capability_checks.models import (
    CapabilityCheck,
    CapabilityCheckResult,
    CapabilityCheckStatus,
    CredentialCapabilityReport,
    NamedCheckRun,
)
from onyx.connectors.capability_checks.registry import get_capability_checks
from onyx.connectors.capability_checks.runner import (
    generate_capability_report,
    merge_capability_results,
)
from onyx.connectors.config_hash import compute_connector_config_hash
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.models import InputType
from onyx.connectors.registry import CONNECTOR_CLASS_MAP
from onyx.db.credential_capability import (
    mark_capability_report_running,
    mark_capability_run_failed,
    upsert_completed_capability_report,
)
from onyx.db.credentials import fetch_credential_by_id
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import AccessType, CapabilityCheckTrigger
from onyx.db.models import Credential
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import run_functions_tuples_in_parallel

logger = setup_logger()

_TRIGGER = CapabilityCheckTrigger.CC_PAIR_VALIDATION

# The longest time creation waits for its checks. A check that is still running
# then does not block the pairing.
CREATION_BLOCKING_BUDGET_SECONDS = 3.0

_REJECTED_MESSAGE = "Did not finish before the connector was rejected."


def _fresh_draft_results(
    checks: list[CapabilityCheck[Any]],
    *,
    credential: Credential,
    source: DocumentSource,
    access_type: AccessType,
    connector_specific_config: dict[str, Any],
) -> dict[str, CachedDraftResult]:
    """check_id to its cached draft result, for the checks a draft run already
    ran with this credential, access type and form values. A cached FAILED
    result is left out, so the check runs again: the source may have been
    fixed since, and a client without a draft run cannot ask for a re-run."""
    form_values = validate_form_state(
        CONNECTOR_CLASS_MAP[source].config_class, connector_specific_config
    ).values
    fresh: dict[str, CachedDraftResult] = {}
    for check in checks:
        cached = get_cached_draft_result(
            draft_result_cache_key(
                credential_id=credential.id,
                credential_updated_at=credential.time_updated,
                source=source,
                access_type=access_type,
                check=check,
                form_values=form_values,
            )
        )
        if cached is not None and cached.state != DraftCheckStateKind.FAILED:
            fresh[check.check_id] = cached
    return fresh


def _mark_running(
    *, credential_id: int, connector_id: int, source: DocumentSource
) -> UUID | None:
    """Claims the pairing's report row for this run, also from a run in flight.
    This run decides the pairing, so its report is the one to keep; the fence
    drops the terminal writes of the replaced run."""
    with get_session_with_current_tenant() as db_session:
        row = mark_capability_report_running(
            db_session,
            credential_id=credential_id,
            connector_id=connector_id,
            source=source,
            trigger=_TRIGGER,
            active_within=timedelta(0),
        )
        db_session.commit()
        return row.run_id if row is not None else None


def _run_check_group(
    credential: Credential,
    *,
    check_id: str,
    source: DocumentSource,
    connector_specific_config: dict[str, Any],
    connector_id: int | None,
    input_type: InputType | None,
    access_type: AccessType,
) -> list[CapabilityCheckResult]:
    """Runs one check, with a result row per capability it is mirrored on."""
    return generate_capability_report(
        credential,
        source=source,
        connector_specific_config=connector_specific_config,
        connector_id=connector_id,
        input_type=input_type,
        trigger=_TRIGGER,
        access_type=access_type,
        check_ids=frozenset({check_id}),
    ).check_results


def _run_checks_within_budget(
    check_ids: list[str],
    *,
    credential_id: int,
    source: DocumentSource,
    connector_specific_config: dict[str, Any],
    connector_id: int | None,
    input_type: InputType | None,
    access_type: AccessType,
) -> tuple[list[CapabilityCheckResult], frozenset[str]]:
    """Runs the checks concurrently for at most the blocking budget. Returns
    the results of the checks that finished, and the ids of the others.
    Concurrent, unlike the runner: the budget is too short to run them in
    sequence.

    A check that does not finish is abandoned, as the runner's hang guard does:
    its thread runs on until the check's own guard ends it, and its result is
    discarded. The threads read a credential loaded on a session that is
    already closed, so they share no session with the request.
    """
    if not check_ids:
        return [], frozenset()
    with get_session_with_current_tenant() as db_session:
        credential = fetch_credential_by_id(credential_id, db_session)
        if credential is None:
            raise RuntimeError(f"Credential {credential_id} was deleted.")
    # TODO(evan-onyx): concurrent creation checks can add load on rate-limited
    # sources; they may need a concurrency cap.
    groups = run_functions_tuples_in_parallel(
        [
            (
                partial(
                    _run_check_group,
                    credential,
                    check_id=check_id,
                    source=source,
                    connector_specific_config=connector_specific_config,
                    connector_id=connector_id,
                    input_type=input_type,
                    access_type=access_type,
                ),
                (),
            )
            for check_id in check_ids
        ],
        timeout=CREATION_BLOCKING_BUDGET_SECONDS,
        timeout_callback=lambda *_: None,
    )
    finished: list[CapabilityCheckResult] = []
    unfinished: set[str] = set()
    for check_id, group in zip(check_ids, groups, strict=True):
        if group is None:
            unfinished.add(check_id)
        else:
            finished.extend(group)
    return finished, frozenset(unfinished)


def _unfinished_results(
    checks: list[CapabilityCheck[Any]], unfinished: frozenset[str], message: str
) -> list[CapabilityCheckResult]:
    """INDETERMINATE rows for checks with no result, for a report that is
    stored without a background run."""
    return [
        CapabilityCheckResult(
            capability=check.capability,
            check_id=check.check_id,
            display_name=check.display_name,
            required=check.required,
            status=CapabilityCheckStatus.INDETERMINATE,
            message=message,
            is_fallback=check.is_fallback,
            remediation=check.remediation,
            docs_link=check.docs_link,
            validates_binding=check.validates_binding,
        )
        for check in checks
        if check.check_id in unfinished
    ]


def _store_report(
    results: list[CapabilityCheckResult],
    *,
    credential_id: int,
    connector_id: int,
    source: DocumentSource,
    connector_specific_config: dict[str, Any],
    run_id: UUID,
) -> None:
    report = merge_capability_results(
        CredentialCapabilityReport(
            credential_id=credential_id,
            source=source,
            connector_id=connector_id,
            checked_at=datetime.now(timezone.utc),
            trigger=_TRIGGER,
            verdicts={},
            check_results=[],
        ),
        results,
    )
    with get_session_with_current_tenant() as db_session:
        stored = upsert_completed_capability_report(
            db_session,
            credential_id=credential_id,
            connector_id=connector_id,
            source=source,
            trigger=_TRIGGER,
            report=report,
            connector_config_hash=compute_connector_config_hash(
                connector_specific_config
            ),
            run_id=run_id,
        )
        db_session.commit()
    if stored is None:
        logger.info(
            "Discarded the creation report for connector %s, credential %s: a "
            "newer run owns the row (run %s).",
            connector_id,
            credential_id,
            run_id,
        )


def _mark_run_failed(*, credential_id: int, connector_id: int, run_id: UUID) -> None:
    with get_session_with_current_tenant() as db_session:
        mark_capability_run_failed(
            db_session,
            credential_id=credential_id,
            connector_id=connector_id,
            run_id=run_id,
        )
        db_session.commit()


def _enqueue_unfinished_checks(
    *,
    credential_id: int,
    connector_id: int,
    source: DocumentSource,
    run_id: UUID,
    connector_specific_config: dict[str, Any],
    access_type: AccessType,
    unfinished: frozenset[str],
    finished: list[CapabilityCheckResult],
) -> None:
    """Starts the background run of the checks that did not finish. When the
    run does not start, it is marked failed to run: the first index attempt
    waits until the admin re-runs the checks from the card."""
    try:
        send_capability_check_run_task(
            credential_id=credential_id,
            connector_id=connector_id,
            source=source,
            trigger=_TRIGGER,
            run_id=run_id,
            connector_specific_config=connector_specific_config,
            access_type=access_type,
            check_ids=unfinished,
            prior_results=finished,
        )
    except Exception:
        logger.exception(
            "The capability run for connector %s, credential %s did not start; "
            "the run is marked failed to run.",
            connector_id,
            credential_id,
        )
        _mark_run_failed(
            credential_id=credential_id, connector_id=connector_id, run_id=run_id
        )


def run_named_checks_within_budget(
    *,
    connector_id: int | None,
    source: DocumentSource,
    input_type: InputType | None,
    connector_specific_config: dict[str, Any],
    credential: Credential,
    access_type: AccessType,
) -> NamedCheckRun:
    """Runs the source's named checks for a pairing, with no writes.

    Fresh draft results for the same form are reused and count as finished at
    once. The other checks run for at most ``CREATION_BLOCKING_BUDGET_SECONDS``.
    Does not claim or store a report row and does not start a background run.
    """
    checks = get_capability_checks(source)
    reused = _fresh_draft_results(
        checks,
        credential=credential,
        source=source,
        access_type=access_type,
        connector_specific_config=connector_specific_config,
    )
    finished, unfinished = _run_checks_within_budget(
        list(
            dict.fromkeys(
                check.check_id for check in checks if check.check_id not in reused
            )
        ),
        credential_id=credential.id,
        source=source,
        connector_specific_config=connector_specific_config,
        connector_id=connector_id,
        input_type=input_type,
        access_type=access_type,
    )
    finished.extend(
        cached_check_result(check, cached)
        for check in checks
        if (cached := reused.get(check.check_id)) is not None
    )
    return NamedCheckRun(finished_results=finished, unfinished_check_ids=unfinished)


def validate_pairing_with_named_checks(
    *,
    connector_id: int,
    source: DocumentSource,
    input_type: InputType | None,
    connector_specific_config: dict[str, Any],
    credential: Credential,
    access_type: AccessType,
    enforce_creation: bool,
) -> bool:
    """Runs the source's named checks for a new pairing and stores the report.

    Waits at most ``CREATION_BLOCKING_BUDGET_SECONDS``. Reused draft results
    count as finished at once. When checks are still running at the end of the
    budget and none failed, the report row stays RUNNING and a background run
    of those checks stores the full report.

    Returns False when a required check failed and ``enforce_creation`` is
    False; True otherwise.

    Raises:
        ConnectorValidationError: A required check failed and
            ``enforce_creation`` is True. The message names each failed check.
    """
    credential_id = credential.id
    run_id = _mark_running(
        credential_id=credential_id, connector_id=connector_id, source=source
    )
    # Every write after the claim is in this block, so a failure anywhere
    # retires the RUNNING mark instead of leaving it until the stale sweep.
    try:
        run = run_named_checks_within_budget(
            connector_id=connector_id,
            source=source,
            input_type=input_type,
            connector_specific_config=connector_specific_config,
            credential=credential,
            access_type=access_type,
        )
        finished = run.finished_results
        unfinished = run.unfinished_check_ids
        failed = run.failed_required_results
        if run_id is None:
            logger.info(
                "A capability run for connector %s, credential %s started in the "
                "same instant; it writes the report.",
                connector_id,
                credential_id,
            )
        elif unfinished and not failed:
            _enqueue_unfinished_checks(
                credential_id=credential_id,
                connector_id=connector_id,
                source=source,
                run_id=run_id,
                connector_specific_config=connector_specific_config,
                access_type=access_type,
                unfinished=unfinished,
                finished=finished,
            )
        else:
            _store_report(
                finished
                + _unfinished_results(
                    get_capability_checks(source), unfinished, _REJECTED_MESSAGE
                ),
                credential_id=credential_id,
                connector_id=connector_id,
                source=source,
                connector_specific_config=connector_specific_config,
                run_id=run_id,
            )
    except Exception:
        if run_id is not None:
            _mark_run_failed(
                credential_id=credential_id, connector_id=connector_id, run_id=run_id
            )
        raise

    if not failed:
        return True
    if not enforce_creation:
        return False
    raise ConnectorValidationError(
        "Required capability checks failed: "
        + "; ".join(f"{result.display_name}: {result.message}" for result in failed)
    )
