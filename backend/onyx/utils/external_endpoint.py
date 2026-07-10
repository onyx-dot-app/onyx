"""Generic client for POSTing JSON payloads to external HTTP endpoints.

Used by any feature that delivers data to an operator- or customer-provided
endpoint (hooks, config-driven document push, ...). Handles the HTTP call,
response processing, and validation of the response body against a Pydantic
model. It has no opinion on failure policy — callers interpret the returned
outcome (e.g. the hook executor maps it to its fail strategy; fire-and-forget
callers just log).

SSRF contract: ``endpoint_url`` must be validated with
``onyx.utils.url.validate_outbound_http_url`` at configuration time, before it
is ever passed here. This client only refuses to follow redirects; it does not
re-validate the URL.

reachability_signal semantics on the outcome
--------------------------------------------
``reachability_signal`` carries signal about physical reachability of the
endpoint; ``None`` means "no signal":

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
from typing import Any
from typing import TypeVar

import httpx
from pydantic import BaseModel
from pydantic import ValidationError

from onyx.utils.logger import setup_logger

logger = setup_logger()


T = TypeVar("T", bound=BaseModel)


class ExternalEndpointConfig(BaseModel):
    """Connection settings for an external endpoint, independent of where they
    were configured (DB row or environment variables)."""

    endpoint_url: str
    api_key: str | None = None
    timeout_seconds: float


class ExternalEndpointOutcome(BaseModel):
    """Structured result of an HTTP call to an external endpoint."""

    is_success: bool
    reachability_signal: bool | None  # True/False = signal, None = no signal
    status_code: int | None
    error_message: str | None
    response_payload: dict[str, Any] | None
    duration_ms: int


def _process_response(
    *,
    response: httpx.Response | None,
    exc: Exception | None,
    timeout: float,
    duration_ms: int,
    parse_json: bool,
) -> ExternalEndpointOutcome:
    """Process the result of an HTTP call and return a structured outcome.

    Called after the client.post() try/except. If post() raised, exc is set and
    response is None. Otherwise response is set and exc is None. Handles
    raise_for_status(), JSON decoding, and the dict shape check.
    """
    if exc is not None:
        if isinstance(exc, httpx.NetworkError):
            msg = f"External endpoint network error (unreachable): {exc}"
            logger.warning(msg)
            return ExternalEndpointOutcome(
                is_success=False,
                reachability_signal=False,
                status_code=None,
                error_message=msg,
                response_payload=None,
                duration_ms=duration_ms,
            )
        if isinstance(exc, httpx.TimeoutException):
            msg = f"External endpoint timed out after {timeout}s: {exc}"
            logger.warning(msg)
            return ExternalEndpointOutcome(
                is_success=False,
                reachability_signal=None,  # timeout doesn't indicate unreachability
                status_code=None,
                error_message=msg,
                response_payload=None,
                duration_ms=duration_ms,
            )
        msg = f"External endpoint call failed: {exc}"
        logger.exception(msg, exc_info=exc)
        return ExternalEndpointOutcome(
            is_success=False,
            reachability_signal=None,  # unknown error — don't make assumptions
            status_code=None,
            error_message=msg,
            response_payload=None,
            duration_ms=duration_ms,
        )

    if response is None:
        raise ValueError(
            "exactly one of response or exc must be non-None; both are None"
        )
    status_code = response.status_code

    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as e:
        # Deliberately omit the response body — endpoints can echo request
        # data, secrets, or huge diagnostic pages, and this message flows into
        # logs, hook execution records, and user-facing error details.
        msg = f"External endpoint returned HTTP {e.response.status_code}"
        logger.warning(msg)
        # 401/403 means the api_key has been revoked or is invalid — signal
        # unreachable so the operator knows to update it. All other HTTP errors
        # carry no signal (server is up, the request just failed for
        # application reasons).
        auth_failed = e.response.status_code in (401, 403)
        return ExternalEndpointOutcome(
            is_success=False,
            reachability_signal=False if auth_failed else None,
            status_code=status_code,
            error_message=msg,
            response_payload=None,
            duration_ms=duration_ms,
        )

    if not parse_json:
        # Fire-and-forget: any 2xx is success — endpoints commonly ACK with
        # 204 or an empty body, so the body must not be required.
        return ExternalEndpointOutcome(
            is_success=True,
            reachability_signal=True,
            status_code=status_code,
            error_message=None,
            response_payload=None,
            duration_ms=duration_ms,
        )

    try:
        response_payload = response.json()
    except (json.JSONDecodeError, httpx.DecodingError) as e:
        msg = f"External endpoint returned non-JSON response: {e}"
        logger.warning(msg)
        return ExternalEndpointOutcome(
            is_success=False,
            reachability_signal=None,  # server responded — no signal
            status_code=status_code,
            error_message=msg,
            response_payload=None,
            duration_ms=duration_ms,
        )

    if not isinstance(response_payload, dict):
        msg = (
            "External endpoint returned non-dict JSON "
            f"(got {type(response_payload).__name__})"
        )
        logger.warning(msg)
        return ExternalEndpointOutcome(
            is_success=False,
            reachability_signal=None,  # server responded — no signal
            status_code=status_code,
            error_message=msg,
            response_payload=None,
            duration_ms=duration_ms,
        )

    return ExternalEndpointOutcome(
        is_success=True,
        reachability_signal=True,
        status_code=status_code,
        error_message=None,
        response_payload=response_payload,
        duration_ms=duration_ms,
    )


def post_json_to_endpoint(
    *,
    config: ExternalEndpointConfig,
    payload: dict[str, Any],
    response_type: type[T] | None = None,
) -> tuple[ExternalEndpointOutcome, T | None]:
    """POST the payload and validate the response body against response_type.

    Returns (outcome, validated_model). With a response_type, the body must be
    a JSON object that validates against it, and the model is non-None exactly
    when outcome.is_success is True. Without one (fire-and-forget), the body
    is ignored — any 2xx is success — and the model is always None. Never
    raises on HTTP or validation failures — they are reported through the
    outcome.
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

    outcome = _process_response(
        response=response,
        exc=exc,
        timeout=timeout,
        duration_ms=duration_ms,
        parse_json=response_type is not None,
    )

    # A validation failure downgrades the outcome to a failure. The
    # reachability signal is cleared: the server responded — just a bad payload.
    validated_model: T | None = None
    if (
        response_type is not None
        and outcome.is_success
        and outcome.response_payload is not None
    ):
        try:
            validated_model = response_type.model_validate(outcome.response_payload)
        except ValidationError as e:
            # Summarize per-field locations and messages only — str(e) embeds
            # input_value snippets of the response payload, which must not
            # reach logs, execution records, or user-facing error details.
            error_summary = "; ".join(
                f"{'.'.join(str(loc) for loc in err['loc'])}: {err['msg']}"
                for err in e.errors(include_input=False, include_url=False)
            )
            msg = (
                "External endpoint response failed validation against "
                f"{response_type.__name__}: {error_summary}"
            )
            # Log here like every other failure branch — fire-and-forget
            # callers discard the outcome and rely on the client's logging.
            logger.warning(msg)
            outcome = outcome.model_copy(
                update={
                    "is_success": False,
                    "reachability_signal": None,
                    "error_message": msg,
                    "response_payload": None,
                }
            )

    return outcome, validated_model
