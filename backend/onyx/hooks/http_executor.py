"""Edition-agnostic HTTP execution for hooks.

This module makes the actual HTTP call to a hook endpoint, validates the
response, and applies the fail strategy. It operates on plain connection
settings (HookEndpointConfig) rather than the Hook ORM row, so it can be
driven by any configuration source — the EE executor resolves settings from
the hook table, and CE can supply them from environment configuration.

Persistence (execution logs, is_reachable) is deliberately not handled here;
callers that need it pass an ``on_result`` callback.

updated_is_reachable semantics on the outcome
---------------------------------------------
``updated_is_reachable`` carries signal about physical reachability of the
endpoint; ``None`` means "no signal — leave any stored value unchanged":

  NetworkError (DNS, connection refused)  → False  (cannot reach the server)
  HTTP 401 / 403                          → False  (api_key revoked or invalid)
  TimeoutException                        → None   (server may be slow)
  Other HTTP errors (4xx / 5xx)           → None   (server responded)
  Unknown exception                       → None   (no signal)
  Non-JSON / non-dict response            → None   (server responded)
  Success (2xx, valid dict)               → True   (confirmed reachable)
"""

import json
import time
from collections.abc import Callable
from typing import Any
from typing import TypeVar

import httpx
from pydantic import BaseModel
from pydantic import ValidationError

from onyx.db.enums import HookFailStrategy
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.hooks.executor import HookSoftFailed
from onyx.utils.logger import setup_logger

logger = setup_logger()


T = TypeVar("T", bound=BaseModel)


class HookEndpointConfig(BaseModel):
    """Connection settings for a hook endpoint, independent of where they
    were configured (hook DB row or environment variables).

    SSRF contract: ``endpoint_url`` must be validated with
    ``onyx.utils.url.validate_outbound_http_url(https_only=True)`` at
    configuration time, before it is ever passed here. The executor itself
    only refuses to follow redirects; it does not re-validate the URL.
    """

    endpoint_url: str
    api_key: str | None = None
    timeout_seconds: float
    fail_strategy: HookFailStrategy


class HookHTTPOutcome(BaseModel):
    """Structured result of an HTTP hook call, produced by _process_response."""

    is_success: bool
    updated_is_reachable: (
        bool | None
    )  # True/False = reachability signal, None = no signal
    status_code: int | None
    error_message: str | None
    response_payload: dict[str, Any] | None


def _process_response(
    *,
    response: httpx.Response | None,
    exc: Exception | None,
    timeout: float,
) -> HookHTTPOutcome:
    """Process the result of an HTTP call and return a structured outcome.

    Called after the client.post() try/except. If post() raised, exc is set and
    response is None. Otherwise response is set and exc is None. Handles
    raise_for_status(), JSON decoding, and the dict shape check.
    """
    if exc is not None:
        if isinstance(exc, httpx.NetworkError):
            msg = f"Hook network error (endpoint unreachable): {exc}"
            logger.warning(msg, exc_info=exc)
            return HookHTTPOutcome(
                is_success=False,
                updated_is_reachable=False,
                status_code=None,
                error_message=msg,
                response_payload=None,
            )
        if isinstance(exc, httpx.TimeoutException):
            msg = f"Hook timed out after {timeout}s: {exc}"
            logger.warning(msg, exc_info=exc)
            return HookHTTPOutcome(
                is_success=False,
                updated_is_reachable=None,  # timeout doesn't indicate unreachability
                status_code=None,
                error_message=msg,
                response_payload=None,
            )
        msg = f"Hook call failed: {exc}"
        logger.exception(msg, exc_info=exc)
        return HookHTTPOutcome(
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
        return HookHTTPOutcome(
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
        return HookHTTPOutcome(
            is_success=False,
            updated_is_reachable=None,  # server responded — reachability unchanged
            status_code=status_code,
            error_message=msg,
            response_payload=None,
        )

    if not isinstance(response_payload, dict):
        msg = f"Hook returned non-dict JSON (got {type(response_payload).__name__})"
        logger.warning(msg)
        return HookHTTPOutcome(
            is_success=False,
            updated_is_reachable=None,  # server responded — reachability unchanged
            status_code=status_code,
            error_message=msg,
            response_payload=None,
        )

    return HookHTTPOutcome(
        is_success=True,
        updated_is_reachable=True,
        status_code=status_code,
        error_message=None,
        response_payload=response_payload,
    )


def execute_hook_endpoint(
    *,
    config: HookEndpointConfig,
    payload: dict[str, Any],
    response_type: type[T],
    on_result: Callable[[HookHTTPOutcome, int], None] | None = None,
) -> T | HookSoftFailed:
    """Make the HTTP call, validate the response, and return a typed model.

    ``on_result`` is invoked with the final outcome and the call duration in
    milliseconds before the fail strategy is applied — the EE executor uses it
    to persist execution logs and is_reachable.

    Raises OnyxError on HARD failure. Returns HookSoftFailed on SOFT failure.
    """
    timeout = config.timeout_seconds

    start = time.monotonic()
    response: httpx.Response | None = None
    exc: Exception | None = None
    try:
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if config.api_key:
            headers["Authorization"] = f"Bearer {config.api_key}"
        with httpx.Client(
            timeout=timeout, follow_redirects=False
        ) as client:  # SSRF guard: never follow redirects
            response = client.post(config.endpoint_url, json=payload, headers=headers)
    except Exception as e:
        exc = e
    duration_ms = int((time.monotonic() - start) * 1000)

    outcome = _process_response(response=response, exc=exc, timeout=timeout)

    # Validate the response payload against response_type.
    # A validation failure downgrades the outcome to a failure so it is logged,
    # reachability signal is cleared (server responded — just a bad payload),
    # and fail_strategy is respected below.
    validated_model: T | None = None
    if outcome.is_success and outcome.response_payload is not None:
        try:
            validated_model = response_type.model_validate(outcome.response_payload)
        except ValidationError as e:
            msg = (
                f"Hook response failed validation against {response_type.__name__}: {e}"
            )
            outcome = HookHTTPOutcome(
                is_success=False,
                updated_is_reachable=None,  # server responded — reachability unchanged
                status_code=outcome.status_code,
                error_message=msg,
                response_payload=None,
            )

    if on_result is not None:
        on_result(outcome, duration_ms)

    if not outcome.is_success:
        if config.fail_strategy == HookFailStrategy.HARD:
            raise OnyxError(
                OnyxErrorCode.HOOK_EXECUTION_FAILED,
                outcome.error_message or "Hook execution failed.",
            )
        logger.warning(
            "Hook execution failed (soft fail) for endpoint=%s: %s",
            config.endpoint_url,
            outcome.error_message,
        )
        return HookSoftFailed()

    if validated_model is None:
        raise OnyxError(
            OnyxErrorCode.INTERNAL_ERROR,
            "validated_model is None for successful hook call "
            f"(endpoint={config.endpoint_url})",
        )
    return validated_model
