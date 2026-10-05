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
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel
from pydantic_core import to_jsonable_python

from onyx.cache.factory import get_cache_backend
from onyx.cache.interface import CacheLock
from onyx.configs.constants import DocumentSource
from onyx.connectors.capability_checks.models import (
    CapabilityCheck,
    CapabilityCheckContext,
    CapabilityCheckResult,
    CapabilityCheckStatus,
    CredentialCapability,
)
from onyx.connectors.capability_checks.runner import (
    CheckReadinessKind,
    decide_check_readiness,
)
from onyx.connectors.config_hash import compute_connector_config_hash
from onyx.connectors.models import InputType
from onyx.connectors.source_operations import get_source_operations_class
from onyx.db.enums import AccessType

DRAFT_RUN_TTL_SECONDS = 30 * 60
# Caps every hang guard of a draft run. A check that times out is
# INDETERMINATE, which does not block the form. Stored runs keep their full
# guards.
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
    INDETERMINATE = "indeterminate"
    SKIPPED = "skipped"
    # A required field is missing or invalid; the check runs once it is valid.
    WAITING = "waiting"
    # The access type or the check's ``applies`` excludes it.
    NOT_APPLICABLE = "not_applicable"


_STATE_BY_STATUS: dict[CapabilityCheckStatus, DraftCheckStateKind] = {
    CapabilityCheckStatus.PASSED: DraftCheckStateKind.PASSED,
    CapabilityCheckStatus.FAILED: DraftCheckStateKind.FAILED,
    CapabilityCheckStatus.INDETERMINATE: DraftCheckStateKind.INDETERMINATE,
    CapabilityCheckStatus.SKIPPED: DraftCheckStateKind.SKIPPED,
}
_STATUS_BY_STATE = {state: status for status, state in _STATE_BY_STATUS.items()}
# Indeterminate results are transient, so they are not cached.
_CACHEABLE_STATES = frozenset(
    {
        DraftCheckStateKind.PASSED,
        DraftCheckStateKind.FAILED,
        DraftCheckStateKind.SKIPPED,
    }
)


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
    display_name: str
    capability: CredentialCapability
    required: bool
    state: DraftCheckStateKind
    message: str = ""
    missing_fields: list[str] = []
    invalid_fields: list[str] = []
    remediation: str | None = None
    docs_link: str | None = None
    duration_ms: int | None = None
    from_cache: bool = False
    # The check proves the credential works with the credential-bound fields.
    validates_binding: bool = False


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
        display_name=check.display_name,
        capability=check.capability,
        required=check.required,
        state=DraftCheckStateKind.PENDING,
        remediation=check.remediation,
        docs_link=check.docs_link,
        validates_binding=check.validates_binding,
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
    """Caches a terminal result; INDETERMINATE is not cached."""
    state = _STATE_BY_STATUS[result.status]
    if state not in _CACHEABLE_STATES:
        return
    cached = CachedDraftResult(
        state=state,
        message=result.message,
        duration_ms=result.duration_ms,
        error_type=result.error_type,
    )
    get_cache_backend().set(
        key, cached.model_dump_json(), ex=DRAFT_RESULT_CACHE_TTL_SECONDS
    )


def cached_check_result(
    check: CapabilityCheck[Any], cached: CachedDraftResult
) -> CapabilityCheckResult:
    """A cached draft result as a report row, for a run that reuses it."""
    return CapabilityCheckResult(
        capability=check.capability,
        check_id=check.check_id,
        display_name=check.display_name,
        required=check.required,
        status=_STATUS_BY_STATE[cached.state],
        message=cached.message,
        error_type=cached.error_type,
        is_fallback=check.is_fallback,
        remediation=check.remediation,
        docs_link=check.docs_link,
        duration_ms=cached.duration_ms,
        validates_binding=check.validates_binding,
    )


def apply_check_result(
    check_state: DraftCheckState, result: CapabilityCheckResult
) -> None:
    check_state.state = _STATE_BY_STATUS[result.status]
    check_state.message = result.message
    check_state.duration_ms = result.duration_ms


def apply_cached_result(
    check_state: DraftCheckState, cached: CachedDraftResult
) -> None:
    check_state.state = cached.state
    check_state.message = cached.message
    check_state.duration_ms = cached.duration_ms
    check_state.from_cache = True


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
    return snapshot
