"""Hook executor — calls a customer's external HTTP endpoint for a given hook point.

Two public entry points are provided:
  - execute_hook      — async, for FastAPI request handlers (I/O concurrency benefit)
  - execute_hook_sync — sync,  for Celery tasks (thread-per-task; async adds no value)

Both share the same helpers for hook lookup, header building, DB persistence, and
outcome resolution. Only the HTTP client layer differs.

Usage (async):
    result = await execute_hook(
        db_session=db_session,
        hook_point=HookPoint.QUERY_PROCESSING,
        payload={"query": "...", "user_email": "...", "chat_session_id": "..."},
    )

Usage (sync, Celery):
    result = execute_hook_sync(
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
        # result is the response payload dict from the customer's endpoint
        ...

DB session design
-----------------
The executor uses three sessions:

  1. Caller's session (db_session) — used only for the hook lookup read. All
     needed fields are extracted from the Hook object before the HTTP call, so
     the caller's session is not held open during the external HTTP request.

  2. Log session — a separate short-lived session opened after the HTTP call
     completes to write the HookExecutionLog row. This is the primary audit
     record and is committed independently of everything else.

  3. Reachable session — a second short-lived session to update is_reachable on
     the Hook. Kept separate from the log session so a concurrent hook deletion
     (which causes update_hook__no_commit to raise OnyxError(NOT_FOUND)) cannot
     prevent the execution log from being written. This update is best-effort.
"""

import time
from typing import Any

import httpx
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
from onyx.hooks.utils import HOOKS_AVAILABLE
from onyx.utils.logger import setup_logger

logger = setup_logger()


class HookSkipped:
    """No active hook configured for this hook point."""


class HookSoftFailed:
    """Hook was called but failed with SOFT fail strategy — continuing."""


# ---------------------------------------------------------------------------
# Private helpers — shared by both the async and sync executors
# ---------------------------------------------------------------------------


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


def _build_headers(api_key: str | None) -> dict[str, str]:
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def _process_response(
    *,
    response: httpx.Response | None,
    exc: BaseException | None,
    timeout: float,
) -> tuple[bool, bool | None, int | None, str | None, dict[str, Any] | None]:
    """Process the result of an HTTP call and return a structured outcome tuple.

    Called after the client.post() try/except. If post() raised, exc is set and
    response is None. Otherwise response is set and exc is None. Handles
    raise_for_status(), JSON decoding, and the dict shape check.

    Returns:
        (is_success, is_reachable, status_code, error_message, response_payload)
        is_reachable: True on success, False on ConnectError, None otherwise (no change)
    """
    if exc is not None:
        if isinstance(exc, httpx.ConnectError):
            msg = f"Hook endpoint unreachable: {exc}"
            logger.warning(msg, exc_info=exc)
            return False, False, None, msg, None
        if isinstance(exc, httpx.TimeoutException):
            msg = f"Hook timed out after {timeout}s: {exc}"
            logger.warning(msg, exc_info=exc)
            return False, None, None, msg, None
        msg = f"Hook call failed: {exc}"
        logger.exception(msg, exc_info=exc)
        return False, None, None, msg, None

    assert response is not None
    status_code = response.status_code

    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as e:
        msg = f"Hook returned HTTP {e.response.status_code}: {e.response.text}"
        logger.warning(msg, exc_info=e)
        return False, None, status_code, msg, None

    try:
        response_payload = response.json()
    except Exception as e:
        msg = f"Hook returned non-JSON response: {e}"
        logger.warning(msg, exc_info=e)
        return False, None, status_code, msg, None

    if not isinstance(response_payload, dict):
        msg = f"Hook returned non-dict JSON (got {type(response_payload).__name__})"
        logger.warning(msg)
        return False, None, status_code, msg, None

    return True, True, status_code, None, response_payload


def _persist_result(
    *,
    hook_id: int,
    is_success: bool,
    error_message: str | None,
    status_code: int | None,
    duration_ms: int,
    is_reachable: bool | None,
) -> None:
    """Write the execution log on failure and optionally update is_reachable, each
    in its own session so a failure in one does not affect the other."""
    # Only write the execution log on failure — success runs are not recorded.
    # Must not be skipped if the is_reachable update fails (e.g. hook concurrently
    # deleted between the initial lookup and here).
    if not is_success:
        try:
            with get_session_with_current_tenant() as log_session:
                create_hook_execution_log__no_commit(
                    db_session=log_session,
                    hook_id=hook_id,
                    is_success=is_success,
                    error_message=error_message,
                    status_code=status_code,
                    duration_ms=duration_ms,
                )
                log_session.commit()
        except Exception:
            logger.exception(
                f"Failed to persist hook execution log for hook_id={hook_id}"
            )

    # Update is_reachable separately — best-effort, non-critical.
    # update_hook__no_commit can raise OnyxError(NOT_FOUND) if the hook was
    # concurrently deleted, so keep this isolated from the log write above.
    if is_reachable is not None:
        try:
            with get_session_with_current_tenant() as reachable_session:
                update_hook__no_commit(
                    db_session=reachable_session,
                    hook_id=hook_id,
                    is_reachable=is_reachable,
                )
                reachable_session.commit()
        except Exception:
            logger.warning(f"Failed to update is_reachable for hook_id={hook_id}")


def _resolve_outcome(
    *,
    is_success: bool,
    fail_strategy: HookFailStrategy,
    hook_id: int,
    error_message: str | None,
    response_payload: dict[str, Any] | None,
) -> dict[str, Any] | HookSoftFailed:
    """Return the response payload on success, HookSoftFailed on soft failure,
    or raise OnyxError on hard failure."""
    if not is_success:
        if fail_strategy == HookFailStrategy.HARD:
            raise OnyxError(
                OnyxErrorCode.HOOK_EXECUTION_FAILED,
                error_message or "Hook execution failed.",
            )
        logger.warning(
            f"Hook execution failed (soft fail) for hook_id={hook_id}: {error_message}"
        )
        return HookSoftFailed()
    assert response_payload is not None
    return response_payload


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def execute_hook(
    *,
    db_session: Session,
    hook_point: HookPoint,
    payload: dict[str, Any],
) -> dict[str, Any] | HookSkipped | HookSoftFailed:
    """Async executor — use from FastAPI request handlers."""
    hook = _lookup_hook(db_session, hook_point)
    if isinstance(hook, HookSkipped):
        return hook

    api_key: str | None = (
        hook.api_key.get_value(apply_mask=False) if hook.api_key else None
    )
    timeout = hook.timeout_seconds
    hook_id = hook.id
    fail_strategy = hook.fail_strategy
    endpoint_url = hook.endpoint_url
    assert endpoint_url  # guaranteed non-None/empty by _lookup_hook
    headers = _build_headers(api_key)

    start = time.monotonic()
    response: httpx.Response | None = None
    exc: BaseException | None = None
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(endpoint_url, json=payload, headers=headers)
    except Exception as e:
        exc = e
    duration_ms = int((time.monotonic() - start) * 1000)

    is_success, is_reachable, status_code, error_message, response_payload = (
        _process_response(response=response, exc=exc, timeout=timeout)
    )
    _persist_result(
        hook_id=hook_id,
        is_success=is_success,
        error_message=error_message,
        status_code=status_code,
        duration_ms=duration_ms,
        is_reachable=is_reachable,
    )
    return _resolve_outcome(
        is_success=is_success,
        fail_strategy=fail_strategy,
        hook_id=hook_id,
        error_message=error_message,
        response_payload=response_payload,
    )


def execute_hook_sync(
    *,
    db_session: Session,
    hook_point: HookPoint,
    payload: dict[str, Any],
) -> dict[str, Any] | HookSkipped | HookSoftFailed:
    """Sync executor — use from Celery tasks (thread-per-task; async adds no value)."""
    hook = _lookup_hook(db_session, hook_point)
    if isinstance(hook, HookSkipped):
        return hook

    api_key: str | None = (
        hook.api_key.get_value(apply_mask=False) if hook.api_key else None
    )
    timeout = hook.timeout_seconds
    hook_id = hook.id
    fail_strategy = hook.fail_strategy
    endpoint_url = hook.endpoint_url
    assert endpoint_url  # guaranteed non-None/empty by _lookup_hook
    headers = _build_headers(api_key)

    start = time.monotonic()
    response: httpx.Response | None = None
    exc: BaseException | None = None
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.post(endpoint_url, json=payload, headers=headers)
    except Exception as e:
        exc = e
    duration_ms = int((time.monotonic() - start) * 1000)

    is_success, is_reachable, status_code, error_message, response_payload = (
        _process_response(response=response, exc=exc, timeout=timeout)
    )
    _persist_result(
        hook_id=hook_id,
        is_success=is_success,
        error_message=error_message,
        status_code=status_code,
        duration_ms=duration_ms,
        is_reachable=is_reachable,
    )
    return _resolve_outcome(
        is_success=is_success,
        fail_strategy=fail_strategy,
        hook_id=hook_id,
        error_message=error_message,
        response_payload=response_payload,
    )
