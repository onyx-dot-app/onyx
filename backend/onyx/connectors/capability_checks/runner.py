import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel

from onyx.configs.constants import DocumentSource
from onyx.connectors.capability_checks.findings_setting import check_findings_enabled
from onyx.connectors.capability_checks.models import (
    INCOMPLETE_STATUSES,
    CapabilityCheck,
    CapabilityCheckContext,
    CapabilityCheckResult,
    CapabilityCheckStatus,
    CheckAdvisory,
    CheckErrorDetail,
    CheckErrorKind,
    CheckFinding,
    CheckNotApplicableError,
    CheckNotRunReason,
    CheckOutput,
    CredentialCapability,
    CredentialCapabilityReport,
    check_error_detail,
    check_error_kind,
    compute_capability_verdicts,
    credential_strings,
)
from onyx.connectors.capability_checks.registry import (
    get_applicable_capabilities,
    get_capability_checks,
)
from onyx.connectors.credential_families import to_source_credential_json
from onyx.connectors.credentials_provider import build_db_credentials_provider
from onyx.connectors.exceptions import ConnectorValidationError, ValidationError
from onyx.connectors.factory import identify_connector_class, instantiate_connector
from onyx.connectors.interfaces import BaseConnector
from onyx.connectors.models import InputType
from onyx.connectors.registry import CONNECTOR_CLASS_MAP
from onyx.connectors.source_operations import (
    SourceOperations,
    get_source_operations_class,
)
from onyx.db.credentials import fetch_credential_by_id
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import AccessType, CapabilityCheckTrigger
from onyx.db.models import Credential
from onyx.utils.credential_audit import emit_credential_access
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import run_with_timeout

logger = setup_logger()

# Default per-check hang guard. Deliberately long: checks run async with no
# total budget, and a slow probe is vastly cheaper than a failed indexing run.
# Its sole purpose is to stop a stuck probe from blocking a worker thread
# forever. Known-slow probes override it via
# ``CapabilityCheck.timeout_seconds``.
CAPABILITY_CHECK_TIMEOUT_SECONDS = 600

_SKIP_NEEDS_INSTANCE_MESSAGE = (
    "Requires a connector instance -- will re-run automatically when the "
    "connector is instantiated."
)
_SKIP_NEEDS_CONFIG_MESSAGE = (
    "Requires connector configuration -- will re-run automatically when the "
    "connector is configured."
)
_SKIP_FINDINGS_OFF_MESSAGE = "Findings are turned off for this workspace."
_SKIP_VALIDATION_FAILED_MESSAGE = "Skipped: a required check failed."
_TIMEOUT_MESSAGE = (
    "Check timed out; the source may be slow -- try re-running the checks."
)
_RATE_LIMITED_NOT_RUN_MESSAGE = "Not run: rate limited"
# A row's line and description when the check's error does not give its own.
# Only for kinds a check cannot word better: an actionable failure keeps its
# message.
_DEFAULT_ROW_TEXT_BY_KIND: dict[CheckErrorKind, tuple[str, str]] = {
    CheckErrorKind.TIMEOUT: (
        "Timed out",
        "The check did not finish in time.\nRe-run, or check the source's status.",
    ),
    CheckErrorKind.RATE_LIMITED: (
        "Rate limited",
        "The source limited the number of requests.\nWait a minute, then re-run.",
    ),
    CheckErrorKind.UNREACHABLE: (
        "Cannot reach the source",
        "Onyx could not connect to the source.\nCheck the address, then re-run.",
    ),
    CheckErrorKind.UNEXPECTED: (
        "Unexpected error",
        "The check stopped on an error it does not know.\nRe-run the checks.",
    ),
}

# Receives the results recorded so far, after each result row is appended. The
# runner calls it on its own thread, never on an abandoned probe thread.
CapabilityCheckProgressCallback = Callable[[Sequence[CapabilityCheckResult]], None]


class CheckReadinessKind(str, Enum):
    NOT_APPLICABLE = "not_applicable"
    MISSING_FIELDS = "missing_fields"
    INVALID_FIELDS = "invalid_fields"
    NEEDS_CONFIG = "needs_config"
    NEEDS_INSTANCE = "needs_instance"
    RUNNABLE = "runnable"


class CheckReadiness(BaseModel):
    """Whether a check can run in a context, and why not."""

    kind: CheckReadinessKind
    # The missing or invalid field names, for those kinds.
    fields: frozenset[str] = frozenset()
    message: str = ""


class _CheckOutcome(BaseModel):
    """
    Outcome of one check execution, before it is joined with the check's
    metadata into a result row. Shared across checks with one check_id.
    """

    status: CapabilityCheckStatus
    message: str = ""
    error_type: str | None = None
    error_kind: CheckErrorKind | None = None
    error_detail: CheckErrorDetail | None = None
    not_run_reason: CheckNotRunReason | None = None
    blocked_by: str | None = None
    summary: str | None = None
    description: str | None = None
    duration_ms: int | None = None
    applicable: bool = True
    findings: list[CheckFinding] = []
    advisories: list[CheckAdvisory] = []


def _build_result(
    check: CapabilityCheck, outcome: _CheckOutcome
) -> CapabilityCheckResult:
    return CapabilityCheckResult(
        capability=check.capability,
        check_id=check.check_id,
        display_name=check.display_name,
        required=check.required,
        status=outcome.status,
        row_id=check.row_id,
        message=outcome.message,
        error_type=outcome.error_type,
        error_kind=outcome.error_kind,
        error_detail=outcome.error_detail,
        not_run_reason=outcome.not_run_reason,
        blocked_by=outcome.blocked_by,
        summary=outcome.summary,
        description=outcome.description,
        is_fallback=check.is_fallback,
        remediation=check.remediation,
        docs_link=check.docs_link,
        duration_ms=outcome.duration_ms,
        applicable=outcome.applicable,
        validates_binding=check.validates_binding,
        discovery=check.discovery,
        findings=outcome.findings,
        advisories=outcome.advisories,
    )


def _safe_error_detail(
    check: CapabilityCheck,
    context: CapabilityCheckContext,
    error: Exception,
    error_kind: CheckErrorKind,
) -> CheckErrorDetail | None:
    """The error's detail, or None when building it fails: a detail is for
    support, and must never fail the run."""
    try:
        return check_error_detail(
            error, error_kind, credential_strings(context.credential_json)
        )
    except Exception:
        logger.exception(
            "Could not build the error detail of capability check %s", check.check_id
        )
        return None


def _error_outcome(
    check: CapabilityCheck,
    context: CapabilityCheckContext,
    error: Exception,
    form_run: bool,
    message: str | None = None,
    duration_ms: int | None = None,
) -> _CheckOutcome:
    """Maps a check's exception to an outcome, per the check exception
    contract and the check's ``outcome_status``. The row text is the
    error's own, else the default of its kind."""
    error_kind = check_error_kind(error)
    summary, description = _DEFAULT_ROW_TEXT_BY_KIND.get(error_kind, (None, None))
    if isinstance(error, ValidationError):
        summary = error.summary or summary
        description = error.description or description
    return _CheckOutcome(
        status=check.outcome_status(error_kind, form_run),
        message=str(error) if message is None else message,
        summary=summary,
        description=description,
        error_type=type(error).__name__,
        error_kind=error_kind,
        error_detail=_safe_error_detail(check, context, error, error_kind),
        duration_ms=duration_ms,
    )


def _missing_instance_outcome(
    check: CapabilityCheck, context: CapabilityCheckContext, form_run: bool
) -> _CheckOutcome:
    """
    Maps a missing connector instance to an outcome for an instance-requiring
    check.

    A config-less run skips: most connectors cannot be constructed without
    configuration, and that is not a credential problem. A construction failure
    with a supplied config is real signal and follows the check exception
    contract.
    """
    if context.instantiation_error is None:
        return _CheckOutcome(
            status=CapabilityCheckStatus.SKIPPED,
            message=_SKIP_NEEDS_INSTANCE_MESSAGE,
        )
    return _error_outcome(check, context, context.instantiation_error, form_run)


def effective_check_timeout_seconds(check: CapabilityCheck[Any]) -> float:
    """The check's hang guard: its own timeout, else the default."""
    return check.timeout_seconds or CAPABILITY_CHECK_TIMEOUT_SECONDS


def _capped(timeout_seconds: float, cap_seconds: float | None) -> float:
    return timeout_seconds if cap_seconds is None else min(timeout_seconds, cap_seconds)


def _execute_check(
    check: CapabilityCheck,
    context: CapabilityCheckContext,
    timeout_cap_seconds: float | None,
    form_run: bool,
) -> _CheckOutcome:
    """
    Executes one check under its hang guard and maps the outcome to a status.

    A timeout is INCOMPLETE: a slow source is not proof of a broken credential.
    On a form run, a check that ``fails_when_unreachable`` FAILS instead.
    """
    timeout_seconds = _capped(
        effective_check_timeout_seconds(check), timeout_cap_seconds
    )
    start = time.monotonic()

    def elapsed_ms() -> int:
        return int((time.monotonic() - start) * 1000)

    try:
        output: CheckOutput | None = run_with_timeout(
            timeout_seconds, check.run, context
        )
    except CheckNotApplicableError as e:
        return _CheckOutcome(
            status=CapabilityCheckStatus.SKIPPED,
            message=str(e),
            error_type=type(e).__name__,
            applicable=False,
            duration_ms=elapsed_ms(),
        )
    except TimeoutError as e:
        # ``run_with_timeout`` abandons the probe thread on timeout -- Python
        # has no safe thread cancellation -- so the probe may still have a
        # request in flight. Check bodies must keep per-request timeouts below
        # ``timeout_seconds`` so an abandoned probe dies with its current
        # request instead of running on.
        logger.warning(
            "Capability check %s timed out after %.0fs; its probe thread is "
            "abandoned and may still have a request in-flight.",
            check.check_id,
            timeout_seconds,
        )
        return _error_outcome(
            check,
            context,
            e,
            form_run,
            message=_TIMEOUT_MESSAGE,
            duration_ms=elapsed_ms(),
        )
    except Exception as e:
        if check_error_kind(e) == CheckErrorKind.UNEXPECTED:
            logger.warning(
                "Capability check %s raised an unexpected error: %s",
                check.check_id,
                e,
            )
        return _error_outcome(check, context, e, form_run, duration_ms=elapsed_ms())
    output = output or CheckOutput()
    return _CheckOutcome(
        status=CapabilityCheckStatus.PASSED,
        summary=output.summary,
        duration_ms=elapsed_ms(),
        findings=_findings_for_source(output.findings, check, context.source),
        advisories=output.advisories,
    )


def _findings_for_source(
    findings: list[CheckFinding], check: CapabilityCheck, source: DocumentSource
) -> list[CheckFinding]:
    """Drops a finding whose ``field_name`` is not a field of the source's
    config: a form could not use it, so it is a bug in the check."""
    mapping = CONNECTOR_CLASS_MAP.get(source)
    fields: frozenset[str] = (
        frozenset(mapping.config_class.model_fields) if mapping else frozenset()
    )
    kept: list[CheckFinding] = []
    for finding in findings:
        if finding.field_name is not None and finding.field_name not in fields:
            logger.error(
                "Capability check %s returned a finding for %s, which is not a "
                "%s config field; the finding is dropped.",
                check.check_id,
                finding.field_name,
                source.value,
            )
            continue
        kept.append(finding)
    return kept


def _discovery_skip_outcome(
    validation_results: Iterable[CapabilityCheckResult], keep_findings: bool
) -> _CheckOutcome | None:
    """Why a discovery check does not run, or None when it runs."""
    if not keep_findings:
        return _CheckOutcome(
            status=CapabilityCheckStatus.SKIPPED,
            message=_SKIP_FINDINGS_OFF_MESSAGE,
            applicable=False,
        )
    if any(
        result.required and result.status == CapabilityCheckStatus.FAILED
        for result in validation_results
    ):
        return _CheckOutcome(
            status=CapabilityCheckStatus.SKIPPED,
            message=_SKIP_VALIDATION_FAILED_MESSAGE,
            applicable=False,
        )
    return None


def capability_check_run_ceiling_seconds(source: DocumentSource) -> int:
    """Upper bound on one run's legitimate execution time, in seconds.

    Checks run sequentially and mirrored checks (one check surfaced under
    several capabilities) execute once, so the bound sums the distinct per-check
    hang guards, plus the default guard connector instantiation runs under (it
    can itself probe the source; ``generate_capability_report`` enforces that
    guard).
    """
    timeout_by_check_id = {
        check.check_id: effective_check_timeout_seconds(check)
        for check in get_capability_checks(source)
    }
    return int(CAPABILITY_CHECK_TIMEOUT_SECONDS + sum(timeout_by_check_id.values()))


def capability_check_run_stale_after(source: DocumentSource) -> timedelta:
    """Age past which a RUNNING mark is a dead run, not a slow one.

    The mark is set at trigger time, so a legitimate run's wall clock is queue
    wait plus execution; the task expiry bounds the wait at one execution
    ceiling, leaving two ceilings in total. Both the re-trigger guard and the
    stale-run sweep use this cutoff.
    """
    return timedelta(seconds=2 * capability_check_run_ceiling_seconds(source))


def run_order(checks: Sequence[CapabilityCheck]) -> list[CapabilityCheck]:
    """The order the runner executes ``checks``: validation checks before
    discovery checks, and every check after the checks of ``checks`` it
    depends on; otherwise their given order.

    Raises:
        ValueError: The dependencies among ``checks`` form a cycle.
    """
    remaining: list[CapabilityCheck] = [
        check for check in checks if not check.discovery
    ] + [check for check in checks if check.discovery]
    present_ids: set[str] = {check.check_id for check in checks}
    ordered: list[CapabilityCheck] = []
    ordered_ids: set[str] = set()
    while remaining:
        ready = [
            check
            for check in remaining
            if all(
                dependency in ordered_ids or dependency not in present_ids
                for dependency in check.depends_on
            )
        ]
        if not ready:
            raise ValueError(
                "Capability check dependencies form a cycle among: "
                + ", ".join(sorted({check.check_id for check in remaining}))
            )
        # One check at a time keeps the given order wherever it is free.
        first = ready[0]
        ordered.append(first)
        ordered_ids.add(first.check_id)
        remaining.remove(first)
    return ordered


_NOT_RUN_REASON_BY_DEPENDENCY_STATUS: dict[CapabilityCheckStatus, CheckNotRunReason] = {
    CapabilityCheckStatus.FAILED: CheckNotRunReason.DEPENDENCY_FAILED,
    CapabilityCheckStatus.SKIPPED: CheckNotRunReason.DEPENDENCY_SKIPPED,
    **dict.fromkeys(INCOMPLETE_STATUSES, CheckNotRunReason.DEPENDENCY_INCOMPLETE),
}
_NOT_RUN_LINE_BY_REASON: dict[CheckNotRunReason, str] = {
    CheckNotRunReason.DEPENDENCY_FAILED: "Not run: {name} failed",
    CheckNotRunReason.DEPENDENCY_INCOMPLETE: "Not run: {name} incomplete",
    CheckNotRunReason.DEPENDENCY_SKIPPED: "Not run: {name} did not run",
}


def _dependency_not_run_outcome(
    check: CapabilityCheck,
    results_by_check_id: Mapping[str, CapabilityCheckResult],
) -> _CheckOutcome | None:
    """The outcome of a check that a dependency stops, or None when its
    dependencies let it run. A dependency without a result, or one that does
    not apply, does not stop it. The first stopping dependency, in the order
    the check lists them, names the cause. A dependency that a gate stopped
    passes its cause on, so a whole chain names the check that failed."""
    for dependency_id in check.depends_on:
        dependency = results_by_check_id.get(dependency_id)
        if dependency is None or not dependency.applicable:
            continue
        if dependency.not_run_reason is not None:
            return _CheckOutcome(
                status=CapabilityCheckStatus.SKIPPED,
                message=dependency.message,
                summary=dependency.summary,
                not_run_reason=dependency.not_run_reason,
                blocked_by=dependency.blocked_by,
            )
        reason = _NOT_RUN_REASON_BY_DEPENDENCY_STATUS.get(dependency.status)
        if reason is None:
            continue
        line = _NOT_RUN_LINE_BY_REASON[reason].format(name=dependency.display_name)
        return _CheckOutcome(
            status=CapabilityCheckStatus.SKIPPED,
            message=line,
            summary=line,
            not_run_reason=reason,
            blocked_by=dependency_id,
        )
    return None


def dependency_not_run_result(
    check: CapabilityCheck,
    results_by_check_id: Mapping[str, CapabilityCheckResult],
) -> CapabilityCheckResult | None:
    """The SKIPPED result of a check that a dependency stops, or None when
    its dependencies let it run."""
    outcome = _dependency_not_run_outcome(check, results_by_check_id)
    return _build_result(check, outcome) if outcome is not None else None


def stop_blocked_results(
    checks: Sequence[CapabilityCheck], results: Sequence[CapabilityCheckResult]
) -> list[CapabilityCheckResult]:
    """``results`` of checks that ran side by side, with each check that a
    dependency stops replaced by the result the sequential runner records for
    it. A check SKIPPED for its own reason keeps its result."""
    result_by_key: dict[tuple[str, CredentialCapability], CapabilityCheckResult] = {
        (result.check_id, result.capability): result for result in results
    }
    result_by_check_id: dict[str, CapabilityCheckResult] = {}
    for check in run_order(checks):
        key = (check.check_id, check.capability)
        result = result_by_key.get(key)
        if result is None:
            continue
        if result.status != CapabilityCheckStatus.SKIPPED and (
            not_run := dependency_not_run_result(check, result_by_check_id)
        ):
            result = not_run
            result_by_key[key] = result
        result_by_check_id[check.check_id] = result
    return [result_by_key[(result.check_id, result.capability)] for result in results]


def run_capability_checks(
    checks: Sequence[CapabilityCheck],
    context: CapabilityCheckContext,
    on_result: CapabilityCheckProgressCallback | None = None,
    timeout_cap_seconds: float | None = None,
    prior_results: Sequence[CapabilityCheckResult] = (),
    form_run: bool = False,
) -> list[CapabilityCheckResult]:
    """Runs checks sequentially, in ``run_order``, and maps their outcomes to
    statuses.

    Sequential on purpose: source APIs can rate limit aggressively, so
    concurrent probes against the same credential are counterproductive. Check
    failures become result rows; this function never raises for them.

    Checks sharing one check_id (the perm-sync fallback registered under both
    sync capabilities) are one check surfaced per capability: they execute once
    and the outcome mirrors onto each result. Distinct check_ids always execute
    independently, even when they share an implementation.

    ``on_result`` is called after every result row, skips included, with the
    rows recorded so far in run order. It is how a caller publishes per-check
    progress before the run completes; an exception from it propagates.

    ``timeout_cap_seconds`` caps each check's hang guard.

    ``form_run`` marks a run for a connector form (a draft run or a dry run of
    a pair): see ``CapabilityCheck.fails_when_unreachable``.

    A check whose dependency FAILED, is INCOMPLETE or did not run does not
    run: it is SKIPPED with the reason (``dependency_not_run_result``). Once
    the source rate limits a check, the checks after it do not run either.
    ``prior_results`` are results of checks outside this run, such as a draft
    run's cached results: they count as dependencies, and a required failure
    among them skips the discovery checks.
    """
    # A check_id may repeat only as one check mirrored across capabilities;
    # anything else is a registration bug, caught before it silently collapses
    # distinct checks into one execution.
    check_class_by_id: dict[str, type[CapabilityCheck]] = {}
    seen_capability_ids: set[tuple[str, CredentialCapability]] = set()
    for check in checks:
        capability_id = (check.check_id, check.capability)
        assert capability_id not in seen_capability_ids, (
            f"Duplicate check_id {check.check_id!r} within capability "
            f"{check.capability.value}."
        )
        seen_capability_ids.add(capability_id)
        check_class = check_class_by_id.setdefault(check.check_id, type(check))
        assert check_class is type(check), (
            f"check_id {check.check_id!r} is shared by {check_class.__name__} "
            f"and {type(check).__name__}; mirrored checks must be one class."
        )

    results: list[CapabilityCheckResult] = []
    outcome_by_check_id: dict[str, _CheckOutcome] = {}
    result_by_check_id: dict[str, CapabilityCheckResult] = {
        result.check_id: result for result in prior_results
    }
    rate_limited = False

    def record(check: CapabilityCheck, outcome: _CheckOutcome) -> None:
        # Read per result: a run can take minutes, and the setting can be
        # turned off meanwhile.
        if outcome.findings and not check_findings_enabled():
            outcome = outcome.model_copy(update={"findings": []})
        result = _build_result(check, outcome)
        results.append(result)
        result_by_check_id[check.check_id] = result
        if on_result is not None:
            # A snapshot: the callback must not observe later appends.
            on_result(tuple(results))

    # Discovery checks run after validation, and only when it found the
    # credential usable: they exist to show what a working credential reaches.
    for check in run_order(checks):
        if check.discovery:
            discovery_outcome: _CheckOutcome | None = _discovery_skip_outcome(
                [*prior_results, *results], check_findings_enabled()
            )
            if discovery_outcome is not None:
                record(check, discovery_outcome)
                continue
        unrunnable_outcome = _unrunnable_outcome(check, context, form_run)
        if unrunnable_outcome is not None:
            record(check, unrunnable_outcome)
            continue

        if check.check_id not in outcome_by_check_id:
            outcome_by_check_id[check.check_id] = _next_outcome(
                check,
                context,
                result_by_check_id,
                rate_limited=rate_limited,
                timeout_cap_seconds=timeout_cap_seconds,
                form_run=form_run,
            )
            rate_limited = rate_limited or (
                outcome_by_check_id[check.check_id].error_kind
                == CheckErrorKind.RATE_LIMITED
            )
        record(check, outcome_by_check_id[check.check_id])
    return results


def _next_outcome(
    check: CapabilityCheck,
    context: CapabilityCheckContext,
    result_by_check_id: Mapping[str, CapabilityCheckResult],
    *,
    rate_limited: bool,
    timeout_cap_seconds: float | None,
    form_run: bool,
) -> _CheckOutcome:
    """The outcome of a runnable check: not run when a dependency stops it or
    the run is rate limited, else what executing it gives."""
    dependency_outcome = _dependency_not_run_outcome(check, result_by_check_id)
    if dependency_outcome is not None:
        return dependency_outcome
    if rate_limited:
        return _CheckOutcome(
            status=CapabilityCheckStatus.SKIPPED,
            message=_RATE_LIMITED_NOT_RUN_MESSAGE,
            summary=_RATE_LIMITED_NOT_RUN_MESSAGE,
            not_run_reason=CheckNotRunReason.RATE_LIMITED,
        )
    return _execute_check(check, context, timeout_cap_seconds, form_run)


def decide_check_readiness(
    check: CapabilityCheck[Any], context: CapabilityCheckContext
) -> CheckReadiness:
    """Decides whether a check can run in this context. Order matters: a check
    that does not apply is excluded before its inputs are judged."""
    if (
        check.access_types is not None
        and context.access_type is not None
        and context.access_type not in check.access_types
    ):
        return CheckReadiness(
            kind=CheckReadinessKind.NOT_APPLICABLE,
            message=(
                f"Does not apply to connectors with {context.access_type.value} access."
            ),
        )
    if check.requires_connector_config and context.connector_specific_config is None:
        return CheckReadiness(
            kind=CheckReadinessKind.NEEDS_CONFIG, message=_SKIP_NEEDS_CONFIG_MESSAGE
        )
    form_state = context.form_state
    if check.reads_connector_config and form_state is not None:
        # A check that reads the config cannot trust it while a field is
        # invalid: the invalid value would silently read as the default.
        if form_state.errors:
            return CheckReadiness(
                kind=CheckReadinessKind.INVALID_FIELDS,
                fields=frozenset(form_state.errors),
                message="Invalid connector settings: "
                + "; ".join(
                    f"{name}: {message}"
                    for name, message in sorted(form_state.errors.items())
                ),
            )
        missing = form_state.missing(check.requires_fields)
        if missing:
            return CheckReadiness(
                kind=CheckReadinessKind.MISSING_FIELDS,
                fields=missing,
                message=f"Needs connector settings: {', '.join(sorted(missing))}.",
            )
        if not check.applies(form_state):
            return CheckReadiness(
                kind=CheckReadinessKind.NOT_APPLICABLE,
                message="Does not apply to these connector settings.",
            )
    if check.requires_connector_instance and context.connector is None:
        return CheckReadiness(
            kind=CheckReadinessKind.NEEDS_INSTANCE,
            message=_SKIP_NEEDS_INSTANCE_MESSAGE,
        )
    return CheckReadiness(kind=CheckReadinessKind.RUNNABLE)


def _unrunnable_outcome(
    check: CapabilityCheck[Any], context: CapabilityCheckContext, form_run: bool
) -> _CheckOutcome | None:
    """The outcome of a check that must not run in this context, or None when
    it can run."""
    readiness = decide_check_readiness(check, context)
    match readiness.kind:
        case CheckReadinessKind.RUNNABLE:
            return None
        case CheckReadinessKind.NEEDS_INSTANCE:
            return _missing_instance_outcome(check, context, form_run)
        case CheckReadinessKind.INVALID_FIELDS:
            return _CheckOutcome(
                status=CapabilityCheckStatus.FAILED,
                message=readiness.message,
                error_type=ConnectorValidationError.__name__,
                error_kind=CheckErrorKind.INVALID,
            )
        case CheckReadinessKind.NOT_APPLICABLE:
            return _CheckOutcome(
                status=CapabilityCheckStatus.SKIPPED,
                message=readiness.message,
                applicable=False,
            )
        case CheckReadinessKind.NEEDS_CONFIG | CheckReadinessKind.MISSING_FIELDS:
            return _CheckOutcome(
                status=CapabilityCheckStatus.SKIPPED, message=readiness.message
            )


def _instantiate_connector_isolated(
    *,
    source: DocumentSource,
    input_type: InputType | None,
    connector_specific_config: dict[str, Any],
    credential_id: int,
) -> tuple[BaseConnector, dict[str, Any]]:
    """Instantiates the connector on a session owned by the calling thread.

    ``run_with_timeout`` abandons its thread on timeout while the thread keeps
    executing, and instantiation can write: ``load_credentials`` may return
    refreshed tokens, which ``backend_update_credential_json`` persists with a
    commit. Owning the session and the credential instance here keeps an
    abandoned thread from committing through state the caller still uses.
    Returns the connector and the credential material as loaded after
    instantiation, so a refreshed token reaches checks instead of the caller's
    pre-refresh copy.
    """
    with get_session_with_current_tenant() as db_session:
        credential = fetch_credential_by_id(credential_id, db_session)
        if credential is None:
            raise RuntimeError(
                f"Credential {credential_id} was deleted while the run was in flight."
            )
        connector = instantiate_connector(
            db_session=db_session,
            source=source,
            input_type=input_type,
            connector_specific_config=connector_specific_config,
            credential=credential,
        )
        credential_json = to_source_credential_json(
            source,
            (
                credential.credential_json.get_value(apply_mask=False)
                if credential.credential_json
                else {}
            ),
        )
        return connector, credential_json


def generate_capability_report(
    credential: Credential,
    source: DocumentSource | None = None,
    connector_specific_config: dict[str, Any] | None = None,
    connector_id: int | None = None,
    input_type: InputType | None = None,
    trigger: CapabilityCheckTrigger = CapabilityCheckTrigger.MANUAL,
    access_type: AccessType | None = None,
    on_result: CapabilityCheckProgressCallback | None = None,
    check_ids: frozenset[str] | None = None,
    timeout_cap_seconds: float | None = None,
    prior_results: Sequence[CapabilityCheckResult] = (),
    form_run: bool = False,
) -> CredentialCapabilityReport:
    """Runs every capability check for a credential and packages a report.

    Check failures are report content; this raises only for programmer errors
    (e.g. a source with no connector class). Without a
    ``connector_specific_config``, instantiation is attempted with an empty
    config; when construction raises, instance-requiring checks are SKIPPED.
    When a supplied config fails to instantiate, the failure is surfaced on
    instance-requiring checks instead (see ``_missing_instance_outcome``).
    Unlike ``validate_ccpair_for_user``, no source is exempted: MOCK_CONNECTOR
    must run so integration tests can exercise the full pipeline. ``credential``
    may be a detached instance; only loaded columns are read. ``source`` picks
    the checks: the connector's source for a connector-scoped run, which for a
    family credential may not be the credential's own source. It defaults to the
    credential's source. ``on_result`` is forwarded to ``run_capability_checks``
    for per-check progress.

    ``check_ids`` limits the run to those checks. A limited run instantiates the
    connector only when a selected check needs the instance.

    ``timeout_cap_seconds`` caps every hang guard of the run: each check's and
    the connector instantiation's. ``prior_results`` and ``form_run`` are
    forwarded to ``run_capability_checks``.
    """
    source = source or credential.source
    checks = get_capability_checks(source)
    if check_ids is not None:
        checks = [check for check in checks if check.check_id in check_ids]
    # Fail loudly for programmer errors (a source with no connector class)
    # rather than degrading them to skips in the guarded instantiation below.
    identify_connector_class(source, input_type)

    # Config-less runs attempt instantiation with an empty config: some
    # connectors happen to construct with one, giving unmigrated sources a basic
    # credential-time probe. There is deliberately no per-connector extension
    # point for this.
    instantiation_config = (
        connector_specific_config if connector_specific_config is not None else {}
    )
    connector: BaseConnector | None = None
    fresh_credential_json: dict[str, Any] | None = None
    instantiation_error: Exception | None = None
    should_instantiate = check_ids is None or any(
        check.requires_connector_instance for check in checks
    )
    if should_instantiate:
        try:
            # Under the guard the run ceiling budgets for it: construction and
            # ``load_credentials`` can probe the source with no timeout of their
            # own, and the stale-run sweep trusts the ceiling.
            connector, fresh_credential_json = run_with_timeout(
                _capped(CAPABILITY_CHECK_TIMEOUT_SECONDS, timeout_cap_seconds),
                _instantiate_connector_isolated,
                source=source,
                input_type=input_type,
                connector_specific_config=instantiation_config,
                credential_id=credential.id,
            )
        except Exception as e:
            # A config-less probe construction fails routinely and stays a
            # skip; a failure with the real config is actionable and is
            # surfaced on instance-requiring checks.
            if connector_specific_config is not None:
                instantiation_error = e
            logger.warning(
                "Could not instantiate %s connector for capability checks: %s",
                source,
                e,
            )

    # Migrated sources always get their gateway constructed: construction is
    # lazy (no client build or decrypt until an operation runs), and checks
    # treat a registered-but-missing gateway as a programmer error.
    source_operations: SourceOperations | None = None
    source_operations_class = get_source_operations_class(source)
    if source_operations_class is not None:
        source_operations = source_operations_class(
            credentials_provider=build_db_credentials_provider(source, credential.id),
            connector_specific_config=connector_specific_config,
        )

    if credential.credential_json:
        # Audits the run's own decrypt of the material (the isolated
        # instantiation's post-load read, or the fallback below), a distinct
        # site from ``instantiate_connector``'s paths. Best-effort, never
        # raises.
        emit_credential_access(
            credential_type="connector",
            provider=str(source),
            row_id=credential.id,
        )
    # The isolated instantiation reports the material as loaded after a possible
    # token refresh; the caller's copy is the pre-refresh fallback.
    credential_json = (
        fresh_credential_json
        if fresh_credential_json is not None
        else to_source_credential_json(
            source,
            (
                credential.credential_json.get_value(apply_mask=False)
                if credential.credential_json
                else {}
            ),
        )
    )
    context = CapabilityCheckContext(
        source=source,
        credential_json=credential_json,
        connector=connector,
        # The supplied config only, never the empty instantiation config: checks
        # marked requires_connector_config must skip on config-less runs rather
        # than probe an empty dict.
        connector_specific_config=connector_specific_config,
        access_type=access_type,
        instantiation_error=instantiation_error,
        source_operations=source_operations,
    )
    results = run_capability_checks(
        checks,
        context,
        on_result=on_result,
        timeout_cap_seconds=timeout_cap_seconds,
        prior_results=prior_results,
        form_run=form_run,
    )
    return CredentialCapabilityReport(
        credential_id=credential.id,
        source=source,
        connector_id=connector_id,
        checked_at=datetime.now(timezone.utc),
        trigger=trigger,
        verdicts=compute_capability_verdicts(
            get_applicable_capabilities(source), results
        ),
        check_results=results,
    )


def merge_capability_results(
    report: CredentialCapabilityReport,
    prior_results: Sequence[CapabilityCheckResult],
) -> CredentialCapabilityReport:
    """The report of a limited run with ``prior_results`` added, for the checks
    the run left out. Results keep the registry order; the run's own result
    wins over a prior one for the same check."""
    by_key = {
        (result.check_id, result.capability): result
        for result in [*prior_results, *report.check_results]
    }
    results = [
        by_key[key]
        for check in get_capability_checks(report.source)
        if (key := (check.check_id, check.capability)) in by_key
    ]
    return report.model_copy(
        update={
            "check_results": results,
            "verdicts": compute_capability_verdicts(
                get_applicable_capabilities(report.source), results
            ),
        }
    )
