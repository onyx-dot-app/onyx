"""Hook executor — calls a customer's external HTTP endpoint for a given hook point.

Usage (Celery tasks and FastAPI handlers):
    result = execute_hook(
        db_session=db_session,
        hook_point=HookPoint.QUERY_PROCESSING,
        payload={"query": "...", "user_email": "...", "chat_session_id": "..."},
        response_type=QueryProcessingResponse,
    )

    if isinstance(result, HookSkipped):
        # no active hook configured — continue with original behavior
        ...
    elif isinstance(result, HookSoftFailed):
        # hook failed but fail strategy is SOFT — continue with original behavior
        ...
    else:
        # result is a validated Pydantic model instance (response_type)
        ...

The HTTP call, response validation, and fail-strategy handling live in the
edition-agnostic ``onyx.hooks.http_executor``. This module resolves the hook
configuration from the DB and persists execution results.

is_reachable update policy
--------------------------
``is_reachable`` on the Hook row is updated selectively — only when the outcome
carries a reachability signal (``HookHTTPOutcome.updated_is_reachable`` is
non-None; see ``onyx.hooks.http_executor`` for the per-outcome semantics).
Writes are additionally skipped when the value would not change.

DB session design
-----------------
The executor uses three sessions:

  1. Caller's session (db_session) — used only for the hook lookup read. All
     needed fields are extracted from the Hook object before the HTTP call, so
     the caller's session is not held open during the external HTTP request.

  2. Log session — a separate short-lived session opened after the HTTP call
     completes to write the HookExecutionLog row on failure. Success runs are
     not recorded. Committed independently of everything else.

  3. Reachable session — a second short-lived session to update is_reachable on
     the Hook. Kept separate from the log session so a concurrent hook deletion
     (which causes update_hook__no_commit to raise OnyxError(NOT_FOUND)) cannot
     prevent the execution log from being written. This update is best-effort.
"""

from typing import Any
from typing import TypeVar

from pydantic import BaseModel
from sqlalchemy.orm import Session

from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import HookFailStrategy
from onyx.db.enums import HookPoint
from onyx.db.hook import create_hook_execution_log__no_commit
from onyx.db.hook import get_non_deleted_hook_by_hook_point
from onyx.db.hook import update_hook__no_commit
from onyx.db.models import Hook
from onyx.hooks.executor import HookSkipped
from onyx.hooks.executor import HookSoftFailed
from onyx.hooks.http_executor import execute_hook_endpoint
from onyx.hooks.http_executor import HookEndpointConfig
from onyx.hooks.http_executor import HookHTTPOutcome
from onyx.utils.logger import setup_logger
from shared_configs.configs import MULTI_TENANT

logger = setup_logger()


T = TypeVar("T", bound=BaseModel)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _lookup_hook(
    db_session: Session,
    hook_point: HookPoint,
) -> Hook | HookSkipped:
    """Return the active Hook or HookSkipped if hooks are unavailable/unconfigured.

    No HTTP call is made and no DB writes are performed for any HookSkipped path.
    There is nothing to log and no reachability information to update.
    """
    if MULTI_TENANT:
        return HookSkipped()
    hook = get_non_deleted_hook_by_hook_point(
        db_session=db_session, hook_point=hook_point
    )
    if hook is None or not hook.is_active:
        return HookSkipped()
    if not hook.endpoint_url:
        return HookSkipped()
    return hook


def _persist_result(
    *,
    hook_id: int,
    outcome: HookHTTPOutcome,
    duration_ms: int,
) -> None:
    """Write the execution log on failure and optionally update is_reachable, each
    in its own session so a failure in one does not affect the other."""
    # Only write the execution log on failure — success runs are not recorded.
    # Must not be skipped if the is_reachable update fails (e.g. hook concurrently
    # deleted between the initial lookup and here).
    if not outcome.is_success:
        try:
            with get_session_with_current_tenant() as log_session:
                create_hook_execution_log__no_commit(
                    db_session=log_session,
                    hook_id=hook_id,
                    is_success=False,
                    error_message=outcome.error_message,
                    status_code=outcome.status_code,
                    duration_ms=duration_ms,
                )
                log_session.commit()
        except Exception:
            logger.exception(
                "Failed to persist hook execution log for hook_id=%s", hook_id
            )

    # Update is_reachable separately — best-effort, non-critical.
    # None means the value is unchanged (set by the caller to skip the no-op write).
    # update_hook__no_commit can raise OnyxError(NOT_FOUND) if the hook was
    # concurrently deleted, so keep this isolated from the log write above.
    if outcome.updated_is_reachable is not None:
        try:
            with get_session_with_current_tenant() as reachable_session:
                update_hook__no_commit(
                    db_session=reachable_session,
                    hook_id=hook_id,
                    is_reachable=outcome.updated_is_reachable,
                )
                reachable_session.commit()
        except Exception:
            logger.warning("Failed to update is_reachable for hook_id=%s", hook_id)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _execute_hook_inner(
    hook: Hook,
    payload: dict[str, Any],
    response_type: type[T],
) -> T | HookSoftFailed:
    """Extract config from the Hook row, run the HTTP call, and persist the result.

    Raises OnyxError on HARD failure. Returns HookSoftFailed on SOFT failure.
    """
    hook_id = hook.id
    endpoint_url = hook.endpoint_url
    current_is_reachable: bool | None = hook.is_reachable

    if not endpoint_url:
        raise ValueError(
            f"hook_id={hook_id} is active but has no endpoint_url — "
            "active hooks without an endpoint_url must be rejected by _lookup_hook"
        )

    config = HookEndpointConfig(
        endpoint_url=endpoint_url,
        api_key=hook.api_key.get_value(apply_mask=False) if hook.api_key else None,
        timeout_seconds=hook.timeout_seconds,
        fail_strategy=hook.fail_strategy,
    )

    def _on_result(outcome: HookHTTPOutcome, duration_ms: int) -> None:
        # Skip the is_reachable write when the value would not change — avoids a
        # no-op DB round-trip on every call when the hook is already in the
        # expected state.
        if outcome.updated_is_reachable == current_is_reachable:
            outcome = outcome.model_copy(update={"updated_is_reachable": None})
        _persist_result(hook_id=hook_id, outcome=outcome, duration_ms=duration_ms)

    return execute_hook_endpoint(
        config=config,
        payload=payload,
        response_type=response_type,
        on_result=_on_result,
    )


def _execute_hook_impl(
    *,
    db_session: Session,
    hook_point: HookPoint,
    payload: dict[str, Any],
    response_type: type[T],
) -> T | HookSkipped | HookSoftFailed:
    """EE implementation — loaded by CE's execute_hook via fetch_versioned_implementation.

    Returns HookSkipped if no active hook is configured, HookSoftFailed if the
    hook failed with SOFT fail strategy, or a validated response model on success.
    Raises OnyxError on HARD failure or if the hook is misconfigured.
    """
    hook = _lookup_hook(db_session, hook_point)
    if isinstance(hook, HookSkipped):
        return hook

    fail_strategy = hook.fail_strategy
    hook_id = hook.id

    try:
        return _execute_hook_inner(hook, payload, response_type)
    except Exception:
        if fail_strategy == HookFailStrategy.SOFT:
            logger.exception(
                "Unexpected error in hook execution (soft fail) for hook_id=%s", hook_id
            )
            return HookSoftFailed()
        raise
