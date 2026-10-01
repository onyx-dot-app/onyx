"""Capability-check runs on an unsaved connector form.

A draft run is not a report: it lives in the cache backend under a short TTL
and never writes ``credential_capability_report`` rows. Each check gets a
draft state from the same readiness decision the persisted runner uses, and
terminal results are cached so that a form edit re-runs only the checks the
edit can change.
"""

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel
from pydantic_core import to_jsonable_python

from onyx.cache.factory import get_cache_backend
from onyx.configs.constants import DocumentSource
from onyx.connectors.capability_checks.models import (
    CapabilityCheck,
    CapabilityCheckContext,
    CapabilityCheckResult,
    CapabilityCheckStatus,
    CredentialCapability,
    compute_connector_config_hash,
)
from onyx.connectors.capability_checks.runner import (
    CheckReadinessKind,
    decide_check_readiness,
)
from onyx.db.enums import AccessType

DRAFT_RUN_TTL_SECONDS = 30 * 60
DRAFT_RESULT_CACHE_TTL_SECONDS = 10 * 60

_DRAFT_RUN_KEY_PREFIX = "capability_check_draft_run"
_DRAFT_LATEST_RUN_KEY_PREFIX = "capability_check_draft_latest_run"
_DRAFT_RESULT_KEY_PREFIX = "capability_check_draft_result"
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


class StoredDraftRun(BaseModel):
    user_id: UUID
    snapshot: DraftCheckRunSnapshot
    # check_id to its result cache key, for the checks the run task executes.
    result_cache_keys: dict[str, str]


class CachedDraftResult(BaseModel):
    state: DraftCheckStateKind
    message: str
    duration_ms: int | None


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
) -> str:
    """The result cache key of one check. A check that reads the config,
    directly or through a connector instance, keys on the validated form
    values; any other check keys on the credential alone."""
    reads_config = check.requires_connector_config or check.requires_connector_instance
    config_hash = (
        compute_connector_config_hash(to_jsonable_python(form_values))
        if reads_config and form_values is not None
        else _CONFIG_INDEPENDENT_HASH
    )
    access = access_type.value if access_type is not None else "none"
    return (
        f"{_DRAFT_RESULT_KEY_PREFIX}:{credential_id}:"
        f"{credential_updated_at.isoformat()}:{source.value}:{check.check_id}:"
        f"{access}:{config_hash}"
    )


def get_cached_draft_result(key: str) -> CachedDraftResult | None:
    raw = get_cache_backend().get(key)
    return CachedDraftResult.model_validate_json(raw) if raw is not None else None


def cache_draft_result(key: str, result: CapabilityCheckResult) -> None:
    """Caches a terminal result; INDETERMINATE is not cached."""
    state = _STATE_BY_STATUS[result.status]
    if state not in _CACHEABLE_STATES:
        return
    cached = CachedDraftResult(
        state=state, message=result.message, duration_ms=result.duration_ms
    )
    get_cache_backend().set(
        key, cached.model_dump_json(), ex=DRAFT_RESULT_CACHE_TTL_SECONDS
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


def _run_key(run_id: UUID) -> str:
    return f"{_DRAFT_RUN_KEY_PREFIX}:{run_id}"


def _latest_run_key(user_id: UUID, draft_key: str) -> str:
    return f"{_DRAFT_LATEST_RUN_KEY_PREFIX}:{user_id}:{draft_key}"


def save_draft_run(run: StoredDraftRun) -> None:
    get_cache_backend().set(
        _run_key(run.snapshot.run_id),
        run.model_dump_json(),
        ex=DRAFT_RUN_TTL_SECONDS,
    )


def load_draft_run(run_id: UUID) -> StoredDraftRun | None:
    raw = get_cache_backend().get(_run_key(run_id))
    return StoredDraftRun.model_validate_json(raw) if raw is not None else None


def set_latest_draft_run(user_id: UUID, draft_key: str, run_id: UUID) -> None:
    get_cache_backend().set(
        _latest_run_key(user_id, draft_key), str(run_id), ex=DRAFT_RUN_TTL_SECONDS
    )


def is_superseded(run: StoredDraftRun) -> bool:
    """True when a newer run for the same user and draft key has started."""
    latest = get_cache_backend().get(
        _latest_run_key(run.user_id, run.snapshot.draft_key)
    )
    return latest is not None and latest.decode() != str(run.snapshot.run_id)


def read_draft_run_for_user(
    run_id: UUID, user_id: UUID
) -> DraftCheckRunSnapshot | None:
    """The run's snapshot, or None when it expired or another user started it.
    A RUNNING run that a newer run replaced reads as SUPERSEDED, also before its
    task notices."""
    run = load_draft_run(run_id)
    if run is None or run.user_id != user_id:
        return None
    snapshot = run.snapshot
    if snapshot.status == DraftRunStatus.RUNNING and is_superseded(run):
        snapshot.status = DraftRunStatus.SUPERSEDED
    return snapshot
