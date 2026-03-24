"""Hook executor — calls a customer's external HTTP endpoint for a given hook point.

Usage (Celery tasks and FastAPI handlers):
    result = execute_hook(
        db_session=db_session,
        hook_point=HookPoint.QUERY_PROCESSING,
        payload={"query": "...", "user_email": "...", "chat_session_id": "..."},
    )

    if isinstance(result, HookSkipped):
        # no active hook configured — continue with original behavior
        ...
    elif isinstance(result, HookSoftFailed):
        # hook failed but fail strategy is SOFT — continue with original behavior
        ...
    else:
        # result is a validated Pydantic model instance (spec.response_model)
        ...

is_reachable update policy
--------------------------
``is_reachable`` on the Hook row is updated selectively — only when the outcome
carries meaningful signal about physical reachability:

  NetworkError (DNS, connection refused)  → False  (cannot reach the server)
  HTTP 401 / 403                          → False  (api_key revoked or invalid)
  TimeoutException                        → None   (server may be slow, skip write)
  Other HTTP errors (4xx / 5xx)           → None   (server responded, skip write)
  Unknown exception                       → None   (no signal, skip write)
  Non-JSON / non-dict response            → None   (server responded, skip write)
  Success (2xx, valid dict)               → True   (confirmed reachable)

None means "leave the current value unchanged" — no DB round-trip is made.

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

import json
import time
from typing import Any
from typing import TypeAlias

import httpx
from pydantic import BaseModel
from pydantic import ValidationError
from sqlalchemy.orm import Session

from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import HookFailStrategy
from onyx.db.enums import HookPoint
from onyx.db.hook import create_hook_execution_log__no_commit
from onyx.db.hook import get_non_deleted_hook_by_hook_point
from onyx.db.hook import update_hook__no_commit
from onyx.db.models import Hook
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.hooks.registry import get_hook_point_spec
from onyx.hooks.utils import HOOKS_AVAILABLE
from onyx.utils.logger import setup_logger

logger = setup_logger()


class HookSkipped:
    """No active hook configured for this hook point."""


class HookSoftFailed:
    """Hook was called but failed with SOFT fail strategy — continuing."""


# The return type of execute_hook: a validated response model, or a sentinel
# indicating the hook was skipped or soft-failed.
HookResult: TypeAlias = BaseModel | HookSkipped | HookSoftFailed


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


class _HttpOutcome(BaseModel):
    """Structured result of an HTTP hook call, returned by _process_response."""

    is_success: bool
    updated_is_reachable: (
        bool | None
    )  # True/False = write to DB, None = unchanged (skip write)
    status_code: int | None
    error_message: str | None
    response_payload: dict[str, Any] | None


def _lookup_hook(
    db_session: Session,
    hook_point: HookPoint,
) -> Hook | HookSkipped:
    """Return the active Hook or HookSkipped if hooks are unavailable/unconfigured.

    No HTTP call is made and no DB writes are performed for any HookSkipped path.
    There is nothing to log and no reachability information to update.
    """
    if not HOOKS_AVAILABLE:
        return HookSkipped()
    hook = get_non_deleted_hook_by_hook_point(
        db_session=db_session, hook_point=hook_point
    )
    if hook is None or not hook.is_active:
        return HookSkipped()
    if not hook.endpoint_url:
        return HookSkipped()
    return hook


def _process_response(
    *,
    response: httpx.Response | None,
    exc: Exception | None,
    timeout: float,
) -> _HttpOutcome:
    """Process the result of an HTTP call and return a structured outcome.

    Called after the client.post() try/except. If post() raised, exc is set and
    response is None. Otherwise response is set and exc is None. Handles
    raise_for_status(), JSON decoding, and the dict shape check.
    """
    if exc is not None:
        if isinstance(exc, httpx.NetworkError):
            msg = f"Hook network error (endpoint unreachable): {exc}"
            logger.warning(msg, exc_info=exc)
            return _HttpOutcome(
                is_success=False,
                updated_is_reachable=False,
                status_code=None,
                error_message=msg,
                response_payload=None,
            )
        if isinstance(exc, httpx.TimeoutException):
            msg = f"Hook timed out after {timeout}s: {exc}"
            logger.warning(msg, exc_info=exc)
            return _HttpOutcome(
                is_success=False,
                updated_is_reachable=None,  # timeout doesn't indicate unreachability
                status_code=None,
                error_message=msg,
                response_payload=None,
            )
        msg = f"Hook call failed: {exc}"
        logger.exception(msg, exc_info=exc)
        return _HttpOutcome(
            is_success=False,
            updated_is_reachable=None,  # unknown error — don't make assumptions
            status_code=None,
            error_message=msg,
            response_payload=None,
        )

    if response is None:
        raise ValueError(
            "exactly one of response or exc must be non-None; both are None"
        )
    status_code = response.status_code

    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as e:
        msg = f"Hook returned HTTP {e.response.status_code}: {e.response.text}"
        logger.warning(msg, exc_info=e)
        # 401/403 means the api_key has been revoked or is invalid — mark unreachable
        # so the operator knows to update it. All other HTTP errors keep is_reachable
        # as-is (server is up, the request just failed for application reasons).
        auth_failed = e.response.status_code in (401, 403)
        return _HttpOutcome(
            is_success=False,
            updated_is_reachable=False if auth_failed else None,
            status_code=status_code,
            error_message=msg,
            response_payload=None,
        )

    try:
        response_payload = response.json()
    except (json.JSONDecodeError, httpx.DecodingError) as e:
        msg = f"Hook returned non-JSON response: {e}"
        logger.warning(msg, exc_info=e)
        return _HttpOutcome(
            is_success=False,
            updated_is_reachable=None,  # server responded — reachability unchanged
            status_code=status_code,
            error_message=msg,
            response_payload=None,
        )

    if not isinstance(response_payload, dict):
        msg = f"Hook returned non-dict JSON (got {type(response_payload).__name__})"
        logger.warning(msg)
        return _HttpOutcome(
            is_success=False,
            updated_is_reachable=None,  # server responded — reachability unchanged
            status_code=status_code,
            error_message=msg,
            response_payload=None,
        )

    return _HttpOutcome(
        is_success=True,
        updated_is_reachable=True,
        status_code=status_code,
        error_message=None,
        response_payload=response_payload,
    )


def _persist_result(
    *,
    hook_id: int,
    outcome: _HttpOutcome,
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
                f"Failed to persist hook execution log for hook_id={hook_id}"
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
            logger.warning(f"Failed to update is_reachable for hook_id={hook_id}")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _execute_hook_inner(
    hook: Hook,
    payload: dict[str, Any],
) -> BaseModel | HookSoftFailed:
    """Make the HTTP call, validate the response, and return a typed model.

    Raises OnyxError on HARD failure. Returns HookSoftFailed on SOFT failure.
    """
    timeout = hook.timeout_seconds
    hook_id = hook.id
    fail_strategy = hook.fail_strategy
    endpoint_url = hook.endpoint_url
    current_is_reachable: bool | None = hook.is_reachable
    hook_point = hook.hook_point  # extract before HTTP call per design intent

    if not endpoint_url:
        raise ValueError(
            f"hook_id={hook_id} is active but has no endpoint_url — "
            "active hooks without an endpoint_url must be rejected by _lookup_hook"
        )

    start = time.monotonic()
    response: httpx.Response | None = None
    exc: Exception | None = None
    try:
        api_key: str | None = (
            hook.api_key.get_value(apply_mask=False) if hook.api_key else None
        )
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        with httpx.Client(
            timeout=timeout, follow_redirects=False
        ) as client:  # SSRF guard: never follow redirects
            response = client.post(endpoint_url, json=payload, headers=headers)
    except Exception as e:
        exc = e
    duration_ms = int((time.monotonic() - start) * 1000)

    outcome = _process_response(response=response, exc=exc, timeout=timeout)

    # Validate the response payload against the spec's response_model.
    # A validation failure downgrades the outcome to a failure so it is logged,
    # is_reachable is left unchanged (server responded — just a bad payload),
    # and fail_strategy is respected below.
    validated_model: BaseModel | None = None
    if outcome.is_success and outcome.response_payload is not None:
        spec = get_hook_point_spec(hook_point)
        try:
            validated_model = spec.response_model.model_validate(
                outcome.response_payload
            )
        except ValidationError as e:
            msg = f"Hook response failed validation against {spec.response_model.__name__}: {e}"
            outcome = _HttpOutcome(
                is_success=False,
                updated_is_reachable=None,  # server responded — reachability unchanged
                status_code=outcome.status_code,
                error_message=msg,
                response_payload=None,
            )

    # Skip the is_reachable write when the value would not change — avoids a
    # no-op DB round-trip on every call when the hook is already in the expected state.
    if outcome.updated_is_reachable == current_is_reachable:
        outcome = outcome.model_copy(update={"updated_is_reachable": None})
    _persist_result(hook_id=hook_id, outcome=outcome, duration_ms=duration_ms)

    if not outcome.is_success:
        if fail_strategy == HookFailStrategy.HARD:
            raise OnyxError(
                OnyxErrorCode.HOOK_EXECUTION_FAILED,
                outcome.error_message or "Hook execution failed.",
            )
        logger.warning(
            f"Hook execution failed (soft fail) for hook_id={hook_id}: {outcome.error_message}"
        )
        return HookSoftFailed()

    if validated_model is None:
        raise OnyxError(
            OnyxErrorCode.INTERNAL_ERROR,
            f"validated_model is None for successful hook call (hook_id={hook_id})",
        )
    return validated_model


def execute_hook(
    *,
    db_session: Session,
    hook_point: HookPoint,
    payload: dict[str, Any],
) -> HookResult:
    """Execute the hook for the given hook point synchronously.

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
        return _execute_hook_inner(hook, payload)
    except Exception:
        if fail_strategy == HookFailStrategy.SOFT:
            logger.exception(
                f"Unexpected error in hook execution (soft fail) for hook_id={hook_id}"
            )
            return HookSoftFailed()
        raise
