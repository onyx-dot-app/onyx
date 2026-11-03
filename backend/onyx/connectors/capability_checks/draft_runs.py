"""Capability-check runs on an unsaved connector form.

A draft run is not a report: it lives in the cache backend under a short TTL
and never writes ``credential_capability_report`` rows. Each check gets a
draft state from the same readiness decision the persisted runner uses, and
terminal results are cached so that a form edit re-runs only the checks the
edit can change.

A draft run with a ``DraftRunPairScope`` is a dry run of a proposed state for
an existing cc-pair. Its results are cached apart from create-form runs and
from other pairs.
"""

import math
import time
from collections.abc import Iterable, Sequence
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, computed_field
from pydantic_core import to_jsonable_python

from onyx.cache.factory import get_cache_backend
from onyx.cache.interface import CacheLock
from onyx.configs.constants import DocumentSource
from onyx.connectors.capability_checks.applicability import (
    get_applicable_capabilities,
)
from onyx.connectors.capability_checks.findings_setting import (
    check_findings_enabled,
    hide_findings_if_disabled,
)
from onyx.connectors.capability_checks.models import (
    TRANSIENT_ERROR_KINDS,
    CachedDraftResult,
    CapabilityCheck,
    CapabilityCheckContext,
    CapabilityCheckResult,
    CapabilityCheckStatus,
    CapabilityVerdict,
    CheckNotApplicableError,
    CheckNotRunReason,
    CheckReadinessKind,
    CredentialCapability,
    DraftCheckState,
    DraftCheckStateKind,
    DraftRunPairScope,
    TwoStepEntry,
    TwoStepRow,
    compute_capability_verdicts,
)
from onyx.connectors.capability_checks.runner import (
    decide_check_readiness,
    dependency_not_run_result,
    run_order,
)
from onyx.connectors.capability_checks.two_step import (
    two_step_rows,
)
from onyx.connectors.config_hash import compute_connector_config_hash
from onyx.connectors.source_operations import get_source_operations_class
from onyx.db.enums import AccessType

DRAFT_RUN_TTL_SECONDS = 30 * 60
# Caps every hang guard of a draft run. A check that times out is INCOMPLETE,
# which does not block the form, unless it is a sign-in check
# (``fails_when_unreachable``). Stored runs keep their full guards.
DRAFT_CHECK_TIMEOUT_SECONDS = 5 * 60
# The run outlives its lease by this much, so a reader sees the lease run out
# before the run expires.
_DRAFT_RUN_TTL_LEASE_MARGIN_SECONDS = 60
# A queued draft task that has not started by then is dropped; the admin is
# waiting on the form.
DRAFT_RUN_QUEUE_EXPIRY_SECONDS = 5 * 60
_DRAFT_START_LOCK_TIMEOUT_SECONDS = 30
DRAFT_RESULT_CACHE_TTL_SECONDS = 10 * 60

_DRAFT_RUN_KEY_PREFIX = "capability_check_draft_run"
_DRAFT_LATEST_RUN_KEY_PREFIX = "capability_check_draft_latest_run"
_DRAFT_RESULT_KEY_PREFIX = "capability_check_draft_result"
_DRAFT_USER_CHOICE_KEY_PREFIX = "capability_check_draft_user_choice"
# Set on a result key while a draft run is still to write it.
_IN_FLIGHT_SUFFIX = ":in_flight"
_DRAFT_RESULT_POLL_SECONDS = 0.2
_DRAFT_START_LOCK_PREFIX = "capability_check_draft_start"
_CC_PAIR_KEY_PART = "cc_pair:"
# The config-hash part of the result cache key for checks that never read the
# config, so that their results survive form edits.
_CONFIG_INDEPENDENT_HASH = "config_independent"

_NEEDS_CONFIG_MESSAGE = "Needs connector settings."
_NEEDS_COMPLETE_CONFIG_MESSAGE = "Needs complete connector settings."
_USER_SKIP_REASONS = frozenset(
    {CheckNotRunReason.SKIPPED_BY_USER, CheckNotRunReason.STOPPED_BY_USER}
)
_SKIPPED_BY_USER_LINE = "Skipped by you"
_STOPPED_BY_USER_LINE = "Not run: stopped by user"


_STATE_BY_STATUS: dict[CapabilityCheckStatus, DraftCheckStateKind] = {
    CapabilityCheckStatus.PASSED: DraftCheckStateKind.PASSED,
    CapabilityCheckStatus.FAILED: DraftCheckStateKind.FAILED,
    CapabilityCheckStatus.INCOMPLETE: DraftCheckStateKind.INCOMPLETE,
    CapabilityCheckStatus.INDETERMINATE: DraftCheckStateKind.INDETERMINATE,
    CapabilityCheckStatus.SKIPPED: DraftCheckStateKind.SKIPPED,
    CapabilityCheckStatus.STOPPED: DraftCheckStateKind.STOPPED,
}
_STATUS_BY_STATE = {state: status for status, state in _STATE_BY_STATUS.items()}
_UNFINISHED_STATES = frozenset(
    {DraftCheckStateKind.PENDING, DraftCheckStateKind.RUNNING}
)
# Incomplete results are transient, so they are not cached.
_CACHEABLE_STATES = frozenset(
    {
        DraftCheckStateKind.PASSED,
        DraftCheckStateKind.FAILED,
        DraftCheckStateKind.SKIPPED,
        DraftCheckStateKind.NOT_APPLICABLE,
    }
)


def _draft_state(result: CapabilityCheckResult) -> DraftCheckStateKind:
    """A check that found out at run time that it does not apply is
    NOT_APPLICABLE, as the same decision made before the run is."""
    if result.error_type == CheckNotApplicableError.__name__:
        return DraftCheckStateKind.NOT_APPLICABLE
    return _STATE_BY_STATUS[result.status]


def _result_status(state: DraftCheckStateKind) -> CapabilityCheckStatus:
    return _STATUS_BY_STATE.get(state, CapabilityCheckStatus.SKIPPED)


class DraftRunStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    # A newer run for the same draft key replaced this one.
    SUPERSEDED = "superseded"
    FAILED_TO_RUN = "failed_to_run"


class DraftRerunMode(str, Enum):
    """Which cached results a new draft run ignores."""

    NONE = "none"
    FAILED = "failed"
    ALL = "all"


class DraftCheckRunSnapshot(BaseModel):
    run_id: UUID
    draft_key: str
    source: DocumentSource
    credential_id: int
    access_type: AccessType | None
    status: DraftRunStatus
    # Field name to error message, for the form.
    form_errors: dict[str, str]
    unknown_fields: list[str]
    checks: list[DraftCheckState]

    @computed_field
    @property
    def verdicts(self) -> dict[CredentialCapability, CapabilityVerdict]:
        """Each capability's verdict, as a stored report computes it. A
        capability with a check that is still pending or running has none."""
        unfinished: set[CredentialCapability] = {
            check.capability
            for check in self.checks
            if check.state in _UNFINISHED_STATES
        }
        verdicts = compute_capability_verdicts(
            get_applicable_capabilities(self.source), settled_results(self)
        )
        return {
            capability: verdict
            for capability, verdict in verdicts.items()
            if capability not in unfinished
        }

    @computed_field
    @property
    def two_step_rows(self) -> list[TwoStepRow]:
        """How each two-step row shows, with "counting…" while its step
        runs."""
        return two_step_rows(
            [
                TwoStepEntry(
                    check_id=check.check_id,
                    row_id=check.row_id or check.check_id,
                    step=check.step,
                    status=(
                        None
                        if check.state in _UNFINISHED_STATES
                        else _result_status(check.state)
                    ),
                    applicable=check.state != DraftCheckStateKind.NOT_APPLICABLE,
                    partial=check.partial,
                    error_kind=check.error_kind,
                    not_run_reason=check.not_run_reason,
                    summary=check.summary,
                )
                for check in self.checks
            ]
        )


def _settled_result(check: DraftCheckState) -> CapabilityCheckResult:
    return CapabilityCheckResult(
        capability=check.capability,
        check_id=check.check_id,
        row_id=check.row_id,
        display_name=check.display_name,
        required=check.required,
        status=_result_status(check.state),
        message=check.message,
        summary=check.summary,
        error_kind=check.error_kind,
        not_run_reason=check.not_run_reason,
        blocked_by=check.blocked_by,
        partial=check.partial,
        applicable=check.state != DraftCheckStateKind.NOT_APPLICABLE,
        discovery=check.discovery,
    )


def settled_results(snapshot: DraftCheckRunSnapshot) -> list[CapabilityCheckResult]:
    """The run's checks that are not PENDING or RUNNING, as result rows. A
    waiting check has not verified anything, so it is SKIPPED."""
    return [
        _settled_result(check)
        for check in snapshot.checks
        if check.state not in _UNFINISHED_STATES
    ]


def stop_blocked_draft_checks(
    snapshot: DraftCheckRunSnapshot, checks: Sequence[CapabilityCheck[Any]]
) -> None:
    """Makes a settled check not run when a dependency stops it, as
    ``stop_blocked_results`` does for a stored run. This reaches the results
    the run reused from the cache or the latest run, which no runner decided.
    A check is left until all its dependencies settled, so an any-of group is
    decided on every member. The admin's own skips and stops stay. ``checks``
    are the source's registered checks."""
    state_by_key: dict[tuple[str, CredentialCapability], DraftCheckState] = {
        (state.check_id, state.capability): state for state in snapshot.checks
    }
    unfinished_ids: set[str] = {
        state.check_id for state in snapshot.checks if state.state in _UNFINISHED_STATES
    }
    result_by_check_id: dict[str, CapabilityCheckResult] = {}
    for check in run_order(checks):
        state = state_by_key.get((check.check_id, check.capability))
        if state is None or state.state in _UNFINISHED_STATES:
            continue
        if (
            # A check SKIPPED for its own reason keeps its result.
            _result_status(state.state) != CapabilityCheckStatus.SKIPPED
            and state.not_run_reason not in _USER_SKIP_REASONS
            and unfinished_ids.isdisjoint((*check.depends_on, *check.depends_on_any))
            and (not_run := dependency_not_run_result(check, result_by_check_id))
        ):
            apply_check_result(state, not_run)
            state.from_cache = False
        result_by_check_id[check.check_id] = _settled_result(state)


class StoredDraftRun(BaseModel):
    user_id: UUID
    snapshot: DraftCheckRunSnapshot
    # Set for a dry run of an existing pair. Kept out of the snapshot, so the
    # create-form endpoint's response does not change.
    pair_scope: DraftRunPairScope | None = None
    # check_id to its result cache key, for every check that could run when
    # the run started, also one filled from the cache or skipped.
    result_cache_keys: dict[str, str]
    # Start Now: the run task runs this check, and what it needs, first.
    first_check_id: str | None = None
    # While RUNNING: the time by which the task writes the run again. A RUNNING
    # run read after it has no live task.
    lease_expires_at: datetime | None = None

    def renew_lease(self, seconds: float) -> None:
        self.lease_expires_at = datetime.now(timezone.utc) + timedelta(seconds=seconds)


def decide_draft_check_state(
    check: CapabilityCheck[Any], context: CapabilityCheckContext
) -> DraftCheckState:
    """The check's state before the run: PENDING when it can run, else WAITING
    or NOT_APPLICABLE. An admin is still typing, so invalid fields wait instead
    of failing. ``context`` carries no connector instance; an instance-requiring
    check is PENDING only when the form holds a complete config."""
    readiness = decide_check_readiness(check, context)
    state = DraftCheckState(
        check_id=check.check_id,
        row_id=check.row_id,
        step=check.step,
        display_name=check.display_name,
        capability=check.capability,
        required=check.required,
        state=DraftCheckStateKind.PENDING,
        remediation=check.remediation,
        docs_link=check.docs_link,
        is_fallback=check.is_fallback,
        validates_binding=check.validates_binding,
        discovery=check.discovery,
        reports_field=check.reports_field,
    )
    match readiness.kind:
        case CheckReadinessKind.RUNNABLE:
            pass
        case CheckReadinessKind.NOT_APPLICABLE:
            state.state = DraftCheckStateKind.NOT_APPLICABLE
            state.message = readiness.message
        case CheckReadinessKind.MISSING_FIELDS:
            state.state = DraftCheckStateKind.WAITING
            state.message = readiness.message
            state.missing_fields = sorted(readiness.fields)
        case CheckReadinessKind.INVALID_FIELDS:
            state.state = DraftCheckStateKind.WAITING
            state.message = readiness.message
            state.invalid_fields = sorted(readiness.fields)
        case CheckReadinessKind.NEEDS_CONFIG:
            state.state = DraftCheckStateKind.WAITING
            state.message = _NEEDS_CONFIG_MESSAGE
        case CheckReadinessKind.NEEDS_INSTANCE:
            form_state = context.form_state
            if form_state is None or form_state.complete is None:
                state.state = DraftCheckStateKind.WAITING
                state.message = _NEEDS_COMPLETE_CONFIG_MESSAGE
    return state


def wait_for_dependencies(
    planned: Sequence[tuple[CapabilityCheck[Any], DraftCheckState]],
) -> None:
    """Makes a PENDING check wait while a check it depends on waits, for the
    same fields, so a chain of checks waits on the field its first check
    needs. Its any-of group makes it wait only while no member that applies
    can run."""
    state_by_check_id: dict[str, DraftCheckState] = {}
    for check, state in planned:
        state_by_check_id.setdefault(check.check_id, state)
    state_by_check: dict[int, DraftCheckState] = {
        id(check): state for check, state in planned
    }
    for check in run_order([check for check, _ in planned]):
        state = state_by_check[id(check)]
        if state.state != DraftCheckStateKind.PENDING:
            continue
        waiting: list[DraftCheckState] = [
            dependency
            for dependency_id in check.depends_on
            if (dependency := state_by_check_id.get(dependency_id)) is not None
            and dependency.state == DraftCheckStateKind.WAITING
        ]
        members: list[DraftCheckState] = [
            member
            for member_id in check.depends_on_any
            if (member := state_by_check_id.get(member_id)) is not None
            and member.state != DraftCheckStateKind.NOT_APPLICABLE
        ]
        if members and all(
            member.state == DraftCheckStateKind.WAITING for member in members
        ):
            waiting.extend(members)
        if not waiting:
            continue
        state.state = DraftCheckStateKind.WAITING
        state.message = waiting[0].message
        state.missing_fields = sorted(
            {name for dependency in waiting for name in dependency.missing_fields}
        )
        state.invalid_fields = sorted(
            {name for dependency in waiting for name in dependency.invalid_fields}
        )


def draft_result_cache_key(
    *,
    credential_id: int,
    credential_updated_at: datetime,
    source: DocumentSource,
    access_type: AccessType | None,
    check: CapabilityCheck[Any],
    form_values: dict[str, Any] | None,
    cc_pair_id: int | None,
) -> str:
    """The result cache key of one check. A check that reads the config
    through a connector instance, or without declaring ``config_fields``, keys
    on the validated form values. Any other check keys on its
    ``config_fields`` and the form values that the source's gateway reads, and
    on the credential. A dry run of a pair also keys on the pair."""
    config_hash = _CONFIG_INDEPENDENT_HASH
    if form_values is not None:
        if check.requires_connector_instance or (
            check.reads_connector_config and check.config_fields is None
        ):
            config_hash = _config_hash(form_values)
        else:
            gateway_class = get_source_operations_class(source)
            gateway_keys = (
                gateway_class.config_keys if gateway_class is not None else frozenset()
            )
            check_fields = check.config_fields or frozenset()
            read_values = (
                form_values
                if gateway_keys is None
                else {
                    key: value
                    for key, value in form_values.items()
                    if key in check_fields
                    or (key in gateway_keys and value not in (None, ""))
                }
            )
            if read_values:
                config_hash = _config_hash(read_values)
    access = access_type.value if access_type is not None else "none"
    key = (
        f"{_DRAFT_RESULT_KEY_PREFIX}:{credential_id}:"
        f"{credential_updated_at.isoformat()}:{source.value}:{check.check_id}:"
        f"{access}:{config_hash}"
    )
    return key if cc_pair_id is None else f"{key}:{_CC_PAIR_KEY_PART}{cc_pair_id}"


def _config_hash(values: dict[str, Any]) -> str:
    config_hash = compute_connector_config_hash(to_jsonable_python(values))
    if config_hash is None:
        raise ValueError("A config hash needs a config.")
    return config_hash


def get_cached_draft_result(key: str) -> CachedDraftResult | None:
    raw = get_cache_backend().get(key)
    return CachedDraftResult.model_validate_json(raw) if raw is not None else None


def cache_draft_result(key: str, result: CapabilityCheckResult) -> None:
    """Caches a terminal result; INCOMPLETE is not cached, nor a sign-in check
    FAILED by a timeout or an unreachable source. A check that did not run
    because of a dependency or a rate limit, or a SKIPPED discovery check (a
    failed required check, findings turned off), drops its cached result: the
    skip says nothing about the check once the cause is gone, and an older
    result would return without its cause."""
    state = _draft_state(result)
    if result.not_run_reason is not None or (
        result.discovery and state == DraftCheckStateKind.SKIPPED
    ):
        get_cache_backend().delete(key)
        return
    if state not in _CACHEABLE_STATES or result.error_kind in TRANSIENT_ERROR_KINDS:
        return
    cached = CachedDraftResult(
        state=state,
        message=result.message,
        duration_ms=result.duration_ms,
        error_type=result.error_type,
        error_kind=result.error_kind,
        error_detail=result.error_detail,
        summary=result.summary,
        description=result.description,
        findings=result.findings,
        advisories=result.advisories,
    )
    get_cache_backend().set(
        key, cached.model_dump_json(), ex=DRAFT_RESULT_CACHE_TTL_SECONDS
    )


def form_draft_result_keys(
    checks: Iterable[CapabilityCheck[Any]],
    *,
    credential_id: int,
    credential_updated_at: datetime,
    source: DocumentSource,
    access_type: AccessType | None,
    form_values: dict[str, Any] | None,
    cc_pair_id: int | None,
) -> dict[str, str]:
    """check_id to its result cache key, for a form's draft results."""
    return {
        check.check_id: draft_result_cache_key(
            credential_id=credential_id,
            credential_updated_at=credential_updated_at,
            source=source,
            access_type=access_type,
            check=check,
            form_values=form_values,
            cc_pair_id=cc_pair_id,
        )
        for check in checks
    }


def _in_flight_key(result_key: str) -> str:
    return f"{result_key}{_IN_FLIGHT_SUFFIX}"


def mark_draft_results_in_flight(result_keys: Iterable[str], ttl_seconds: int) -> None:
    """Marks results that a draft run is still to write, so a validation of
    the same form waits for them instead of running the checks again."""
    cache = get_cache_backend()
    for result_key in result_keys:
        cache.set(_in_flight_key(result_key), "1", ex=ttl_seconds)


def clear_draft_result_in_flight(result_key: str) -> None:
    get_cache_backend().delete(_in_flight_key(result_key))


def is_draft_result_in_flight(result_key: str) -> bool:
    return get_cache_backend().get(_in_flight_key(result_key)) is not None


def wait_for_draft_result(
    result_key: str, timeout_seconds: float
) -> CachedDraftResult | None:
    """The result a draft run writes under ``result_key``, once it lands.
    ``None`` when it does not land within ``timeout_seconds``, or the run
    stops without it (an INCOMPLETE result is not cached)."""
    deadline = time.monotonic() + timeout_seconds
    while True:
        cached = get_cached_draft_result(result_key)
        if cached is not None:
            return cached
        if not is_draft_result_in_flight(result_key):
            # The run may have written the result just before clearing.
            return get_cached_draft_result(result_key)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None
        time.sleep(min(_DRAFT_RESULT_POLL_SECONDS, remaining))


def cached_check_result(
    check: CapabilityCheck[Any], cached: CachedDraftResult
) -> CapabilityCheckResult:
    """A cached draft result as a report row, for a run that reuses it."""
    return CapabilityCheckResult(
        capability=check.capability,
        check_id=check.check_id,
        row_id=check.row_id,
        step=check.step,
        display_name=check.display_name,
        required=check.required,
        status=_result_status(cached.state),
        message=cached.message,
        error_type=cached.error_type,
        error_kind=cached.error_kind,
        error_detail=cached.error_detail,
        summary=cached.summary,
        description=cached.description,
        not_run_reason=cached.not_run_reason,
        is_fallback=check.is_fallback,
        remediation=check.remediation,
        docs_link=check.docs_link,
        duration_ms=cached.duration_ms,
        applicable=cached.state != DraftCheckStateKind.NOT_APPLICABLE,
        validates_binding=check.validates_binding,
        discovery=check.discovery,
        # Cached before the workspace turned findings off.
        findings=cached.findings if check_findings_enabled() else [],
        advisories=cached.advisories,
    )


def apply_check_result(
    check_state: DraftCheckState, result: CapabilityCheckResult
) -> None:
    check_state.state = _draft_state(result)
    check_state.message = result.message
    check_state.error_type = result.error_type
    check_state.error_kind = result.error_kind
    check_state.error_detail = result.error_detail
    check_state.not_run_reason = result.not_run_reason
    check_state.blocked_by = result.blocked_by
    check_state.partial = result.partial
    check_state.summary = result.summary
    check_state.description = result.description
    check_state.duration_ms = result.duration_ms
    check_state.findings = result.findings
    check_state.advisories = result.advisories


def apply_cached_result(
    check_state: DraftCheckState, cached: CachedDraftResult
) -> None:
    check_state.state = cached.state
    check_state.message = cached.message
    check_state.error_type = cached.error_type
    check_state.error_kind = cached.error_kind
    check_state.error_detail = cached.error_detail
    check_state.summary = cached.summary
    check_state.description = cached.description
    check_state.not_run_reason = cached.not_run_reason
    check_state.duration_ms = cached.duration_ms
    check_state.findings = cached.findings if check_findings_enabled() else []
    check_state.advisories = cached.advisories
    check_state.from_cache = True


def skip_draft_check(check_state: DraftCheckState) -> None:
    """Marks a check the admin skipped: an optional check is SKIPPED, a
    required one STOPPED, so it still holds Create."""
    if check_state.required:
        check_state.state = DraftCheckStateKind.STOPPED
        check_state.not_run_reason = CheckNotRunReason.STOPPED_BY_USER
        line = _STOPPED_BY_USER_LINE
    else:
        check_state.state = DraftCheckStateKind.SKIPPED
        check_state.not_run_reason = CheckNotRunReason.SKIPPED_BY_USER
        line = _SKIPPED_BY_USER_LINE
    check_state.message = line
    check_state.summary = line


def _user_choice_key(user_id: UUID, result_key: str) -> str:
    return f"{_DRAFT_USER_CHOICE_KEY_PREFIX}:{user_id}:{result_key}"


def cache_user_skip(
    user_id: UUID, result_key: str, check_state: DraftCheckState
) -> None:
    """Caches the admin's skip or stop of a check for that admin only, apart
    from the shared result under ``result_key``: creation by the same admin on
    the same form reuses a skip, and runs a stopped check."""
    cached = CachedDraftResult(
        state=check_state.state,
        message=check_state.message,
        duration_ms=None,
        summary=check_state.summary,
        not_run_reason=check_state.not_run_reason,
    )
    get_cache_backend().set(
        _user_choice_key(user_id, result_key),
        cached.model_dump_json(),
        ex=DRAFT_RESULT_CACHE_TTL_SECONDS,
    )


def clear_user_skip(user_id: UUID, result_key: str) -> None:
    get_cache_backend().delete(_user_choice_key(user_id, result_key))


def get_user_skip(user_id: UUID, result_key: str) -> CachedDraftResult | None:
    """The admin's cached skip or stop of the check under ``result_key``."""
    raw = get_cache_backend().get(_user_choice_key(user_id, result_key))
    return CachedDraftResult.model_validate_json(raw) if raw is not None else None


# Results a run keeps from the latest run of its draft key. A check that a
# gate or the admin stopped has no result of its own: it runs again, so it
# sees the new result of its dependency, or the request's skips decide it.
_KEPT_STATES = frozenset(
    {
        DraftCheckStateKind.PASSED,
        DraftCheckStateKind.FAILED,
        DraftCheckStateKind.INCOMPLETE,
        DraftCheckStateKind.INDETERMINATE,
        DraftCheckStateKind.SKIPPED,
    }
)


def kept_draft_state(
    prior: StoredDraftRun | None, check_state: DraftCheckState, cache_key: str
) -> DraftCheckState | None:
    """The check's result in ``prior``, the latest run of the draft key, for a
    run that does not run the check again. None when ``prior`` ran it on
    another credential or form, or holds no result of its own for it. A
    SKIPPED discovery check runs again, as ``cache_draft_result`` drops it."""
    if prior is None or prior.result_cache_keys.get(check_state.check_id) != cache_key:
        return None
    for prior_state in prior.snapshot.checks:
        if (
            prior_state.check_id == check_state.check_id
            and prior_state.capability == check_state.capability
            and prior_state.state in _KEPT_STATES
            and prior_state.not_run_reason in (None, CheckNotRunReason.NOTHING_IN_SCOPE)
            and not (
                prior_state.discovery
                and prior_state.state == DraftCheckStateKind.SKIPPED
            )
        ):
            return prior_state.model_copy(update={"from_cache": True})
    return None


def pending_in_run_order(
    snapshot: DraftCheckRunSnapshot,
    checks: Sequence[CapabilityCheck[Any]],
    first_check_id: str | None = None,
) -> list[DraftCheckState]:
    """The run's PENDING checks in the order the runner executes them
    (``run_order``). ``checks`` are the source's registered checks."""
    pending: dict[tuple[str, CredentialCapability], DraftCheckState] = {
        (check.check_id, check.capability): check
        for check in snapshot.checks
        if check.state == DraftCheckStateKind.PENDING
    }
    return [
        pending[key]
        for check in run_order(checks, first_check_id)
        if (key := (check.check_id, check.capability)) in pending
    ]


def cc_pair_draft_key(cc_pair_id: int) -> str:
    """The draft key of a pair's dry runs: one latest run per user and pair.
    The ":" keeps it apart from client-chosen create-form keys, which cannot
    contain one."""
    return f"{_CC_PAIR_KEY_PART}{cc_pair_id}"


def _run_key(run_id: UUID) -> str:
    return f"{_DRAFT_RUN_KEY_PREFIX}:{run_id}"


def _latest_run_key(user_id: UUID, draft_key: str) -> str:
    return f"{_DRAFT_LATEST_RUN_KEY_PREFIX}:{user_id}:{draft_key}"


def _draft_run_ttl_seconds(run: StoredDraftRun) -> int:
    """At least ``DRAFT_RUN_TTL_SECONDS``, and always past the lease, so a run
    with a live task cannot expire."""
    if run.lease_expires_at is None:
        return DRAFT_RUN_TTL_SECONDS
    lease_left = (run.lease_expires_at - datetime.now(timezone.utc)).total_seconds()
    return max(
        DRAFT_RUN_TTL_SECONDS,
        math.ceil(lease_left) + _DRAFT_RUN_TTL_LEASE_MARGIN_SECONDS,
    )


def save_draft_run(run: StoredDraftRun) -> None:
    """Stores the run. While the run is the latest of its draft key, this also
    renews the latest-run marker, so the marker lives as long as the run."""
    cache = get_cache_backend()
    ttl_seconds = _draft_run_ttl_seconds(run)
    cache.set(_run_key(run.snapshot.run_id), run.model_dump_json(), ex=ttl_seconds)
    cache.renew_if_value(
        _latest_run_key(run.user_id, run.snapshot.draft_key),
        str(run.snapshot.run_id).encode(),
        ttl_seconds,
    )


def load_draft_run(run_id: UUID) -> StoredDraftRun | None:
    raw = get_cache_backend().get(_run_key(run_id))
    return StoredDraftRun.model_validate_json(raw) if raw is not None else None


def load_latest_draft_run(user_id: UUID, draft_key: str) -> StoredDraftRun | None:
    """The user's latest run of the draft key, while it has not expired."""
    latest = get_cache_backend().get(_latest_run_key(user_id, draft_key))
    return load_draft_run(UUID(latest.decode())) if latest is not None else None


def draft_run_start_lock(user_id: UUID, draft_key: str) -> CacheLock:
    """Serializes the save and the latest-run update of concurrent starts for
    one draft key, so the run saved last is also the latest."""
    return get_cache_backend().lock(
        f"{_DRAFT_START_LOCK_PREFIX}:{user_id}:{draft_key}",
        timeout=_DRAFT_START_LOCK_TIMEOUT_SECONDS,
    )


def set_latest_draft_run(run: StoredDraftRun) -> None:
    get_cache_backend().set(
        _latest_run_key(run.user_id, run.snapshot.draft_key),
        str(run.snapshot.run_id),
        ex=_draft_run_ttl_seconds(run),
    )


def is_superseded(run: StoredDraftRun) -> bool:
    """True when a newer run for the same user and draft key has started. A
    missing marker counts too: while a run is the latest, each save renews the
    marker with the run, so the marker is missing only after a newer run took
    it and then expired."""
    latest = get_cache_backend().get(
        _latest_run_key(run.user_id, run.snapshot.draft_key)
    )
    return latest is None or latest.decode() != str(run.snapshot.run_id)


def _latest_run_skips(run: StoredDraftRun, check_id: str) -> bool:
    """True when the latest run of ``run``'s draft key skipped or stopped the
    check on the same result cache key."""
    latest = load_latest_draft_run(run.user_id, run.snapshot.draft_key)
    if latest is None or latest.result_cache_keys.get(
        check_id
    ) != run.result_cache_keys.get(check_id):
        return False
    return any(
        state.check_id == check_id and state.not_run_reason in _USER_SKIP_REASONS
        for state in latest.snapshot.checks
    )


def cache_run_result(run: StoredDraftRun, result: CapabilityCheckResult) -> None:
    """Caches a result of ``run``. A superseded run keeps off the result of a
    check that the latest run skipped or stopped, so the admin's skip holds.
    Holds the start lock, under which a new run saves its skips."""
    with draft_run_start_lock(run.user_id, run.snapshot.draft_key):
        if is_superseded(run) and _latest_run_skips(run, result.check_id):
            return
        cache_draft_result(run.result_cache_keys[result.check_id], result)


def clear_latest_draft_run(run: StoredDraftRun) -> None:
    """Drops the run's draft key's latest-run marker, so the run reads as
    superseded. Hold ``draft_run_start_lock`` and check ``is_superseded``
    first, or a newer run's marker goes too."""
    get_cache_backend().delete(_latest_run_key(run.user_id, run.snapshot.draft_key))


def read_draft_run_for_user(
    run_id: UUID, user_id: UUID
) -> DraftCheckRunSnapshot | None:
    """The run's snapshot, or None when it expired or another user started it.
    A RUNNING run that a newer run replaced reads as SUPERSEDED, also before its
    task notices. A RUNNING run whose lease ran out reads as FAILED_TO_RUN: its
    task stopped or never started."""
    run = load_draft_run(run_id)
    if run is None or run.user_id != user_id:
        return None
    snapshot = run.snapshot
    if snapshot.status == DraftRunStatus.RUNNING:
        if is_superseded(run):
            snapshot.status = DraftRunStatus.SUPERSEDED
        elif (
            run.lease_expires_at is not None
            and datetime.now(timezone.utc) > run.lease_expires_at
        ):
            snapshot.status = DraftRunStatus.FAILED_TO_RUN
    hide_findings_if_disabled(snapshot.checks)
    return snapshot
