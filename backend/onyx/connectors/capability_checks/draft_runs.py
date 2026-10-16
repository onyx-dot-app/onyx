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

from pydantic import BaseModel, computed_field, field_validator
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
    CapabilityCheck,
    CapabilityCheckContext,
    CapabilityCheckResult,
    CapabilityCheckStatus,
    CapabilityVerdict,
    CheckAdvisory,
    CheckErrorDetail,
    CheckErrorKind,
    CheckFinding,
    CheckNotApplicableError,
    CheckNotRunReason,
    CredentialCapability,
    compute_capability_verdicts,
    parse_known_findings,
)
from onyx.connectors.capability_checks.runner import (
    CheckReadinessKind,
    decide_check_readiness,
    run_order,
)
from onyx.connectors.config_hash import compute_connector_config_hash
from onyx.connectors.models import InputType
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


class DraftCheckStateKind(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    INCOMPLETE = "incomplete"
    # Legacy: INCOMPLETE in runs started before it had its own value.
    INDETERMINATE = "indeterminate"
    SKIPPED = "skipped"
    # A required field is missing or invalid; the check runs once it is valid.
    WAITING = "waiting"
    # The access type or the check's ``applies`` excludes it.
    NOT_APPLICABLE = "not_applicable"


_STATE_BY_STATUS: dict[CapabilityCheckStatus, DraftCheckStateKind] = {
    CapabilityCheckStatus.PASSED: DraftCheckStateKind.PASSED,
    CapabilityCheckStatus.FAILED: DraftCheckStateKind.FAILED,
    CapabilityCheckStatus.INCOMPLETE: DraftCheckStateKind.INCOMPLETE,
    CapabilityCheckStatus.INDETERMINATE: DraftCheckStateKind.INDETERMINATE,
    CapabilityCheckStatus.SKIPPED: DraftCheckStateKind.SKIPPED,
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


class DraftCheckState(BaseModel):
    check_id: str
    # The row the check shows on (``CapabilityCheck.row_id``). None in runs
    # started before rows, which read it as the check_id.
    row_id: str | None = None
    display_name: str
    capability: CredentialCapability
    required: bool
    state: DraftCheckStateKind
    message: str = ""
    # Exception class name of a failure, for support diagnosis.
    error_type: str | None = None
    error_kind: CheckErrorKind | None = None
    error_detail: CheckErrorDetail | None = None
    # Why a SKIPPED check did not run, and the dependency that stopped it.
    not_run_reason: CheckNotRunReason | None = None
    blocked_by: str | None = None
    # The row's short line and description.
    summary: str | None = None
    description: str | None = None
    is_fallback: bool = False
    missing_fields: list[str] = []
    invalid_fields: list[str] = []
    remediation: str | None = None
    docs_link: str | None = None
    duration_ms: int | None = None
    from_cache: bool = False
    # The check proves the credential works with the credential-bound fields.
    validates_binding: bool = False
    # A discovery check: it finds what the credential reaches and never
    # gates the form.
    discovery: bool = False
    # What the check found, once it passed.
    findings: list[CheckFinding] = []
    advisories: list[CheckAdvisory] = []

    @field_validator("findings", mode="before")
    @classmethod
    def _known_findings(cls, findings: Any) -> Any:
        return parse_known_findings(findings)


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


def settled_results(snapshot: DraftCheckRunSnapshot) -> list[CapabilityCheckResult]:
    """The run's checks that are not PENDING or RUNNING, as result rows. A
    waiting check has not verified anything, so it is SKIPPED."""
    return [
        CapabilityCheckResult(
            capability=check.capability,
            check_id=check.check_id,
            row_id=check.row_id,
            display_name=check.display_name,
            required=check.required,
            status=_result_status(check.state),
            error_kind=check.error_kind,
            not_run_reason=check.not_run_reason,
            blocked_by=check.blocked_by,
            applicable=check.state != DraftCheckStateKind.NOT_APPLICABLE,
            discovery=check.discovery,
        )
        for check in snapshot.checks
        if check.state not in _UNFINISHED_STATES
    ]


class DraftCheckPlan(BaseModel):
    """The checks a draft run would hold for a form, each in its state before
    anything runs: pending, waiting or not applicable."""

    source: DocumentSource
    access_type: AccessType | None
    # Field name to error message, for the form.
    form_errors: dict[str, str]
    unknown_fields: list[str]
    checks: list[DraftCheckState]


class DraftRunPairScope(BaseModel):
    """The existing cc-pair that a dry run proposes a state for."""

    cc_pair_id: int
    connector_id: int
    input_type: InputType | None


class StoredDraftRun(BaseModel):
    user_id: UUID
    snapshot: DraftCheckRunSnapshot
    # Set for a dry run of an existing pair. Kept out of the snapshot, so the
    # create-form endpoint's response does not change.
    pair_scope: DraftRunPairScope | None = None
    # check_id to its result cache key, for the checks the run task executes.
    result_cache_keys: dict[str, str]
    # While RUNNING: the time by which the task writes the run again. A RUNNING
    # run read after it has no live task.
    lease_expires_at: datetime | None = None

    def renew_lease(self, seconds: float) -> None:
        self.lease_expires_at = datetime.now(timezone.utc) + timedelta(seconds=seconds)


class CachedDraftResult(BaseModel):
    state: DraftCheckStateKind
    message: str
    duration_ms: int | None
    error_type: str | None = None
    error_kind: CheckErrorKind | None = None
    error_detail: CheckErrorDetail | None = None
    summary: str | None = None
    description: str | None = None
    findings: list[CheckFinding] = []
    advisories: list[CheckAdvisory] = []

    @field_validator("findings", mode="before")
    @classmethod
    def _known_findings(cls, findings: Any) -> Any:
        return parse_known_findings(findings)


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
        display_name=check.display_name,
        capability=check.capability,
        required=check.required,
        state=DraftCheckStateKind.PENDING,
        remediation=check.remediation,
        docs_link=check.docs_link,
        is_fallback=check.is_fallback,
        validates_binding=check.validates_binding,
        discovery=check.discovery,
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
    needs."""
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
    """The result cache key of one check. A check that reads the config,
    directly or through a connector instance, keys on the validated form
    values. Any other check keys on the form values that the source's gateway
    reads, and on the credential. A dry run of a pair also keys on the pair."""
    config_hash = _CONFIG_INDEPENDENT_HASH
    if form_values is not None:
        if check.reads_connector_config or check.requires_connector_instance:
            config_hash = _config_hash(form_values)
        else:
            gateway_class = get_source_operations_class(source)
            gateway_keys = (
                gateway_class.config_keys if gateway_class is not None else frozenset()
            )
            gateway_values = (
                form_values
                if gateway_keys is None
                else {
                    key: value
                    for key, value in form_values.items()
                    if key in gateway_keys and value not in (None, "")
                }
            )
            if gateway_values:
                config_hash = _config_hash(gateway_values)
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
        display_name=check.display_name,
        required=check.required,
        status=_result_status(cached.state),
        message=cached.message,
        error_type=cached.error_type,
        error_kind=cached.error_kind,
        error_detail=cached.error_detail,
        summary=cached.summary,
        description=cached.description,
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
    check_state.duration_ms = cached.duration_ms
    check_state.findings = cached.findings if check_findings_enabled() else []
    check_state.advisories = cached.advisories
    check_state.from_cache = True


def pending_in_run_order(
    snapshot: DraftCheckRunSnapshot, checks: Sequence[CapabilityCheck[Any]]
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
        for check in run_order(checks)
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
