"""Microsoft Graph transport: the retry policies and the authenticated GET.

Two status sets live here because callers disagree about 5xx.
:data:`RETRYABLE_HTTP_STATUSES` is the narrow set, used only by
:func:`sleep_and_retry`. :data:`GRAPH_API_RETRYABLE_STATUSES` adds the gateway
5xx codes and is what every other caller uses. Reach for the narrow one only when
matching ``sleep_and_retry``.

This layer carries no source identity, so a connector composes it.
"""

import random
import time
from collections.abc import Callable
from typing import Any

import requests
from office365.runtime.client_request import ClientRequestException
from office365.runtime.queries.client_query import ClientQuery

from onyx.configs.app_configs import REQUEST_TIMEOUT_SECONDS
from onyx.utils.logger import setup_logger
from onyx.utils.retry_after import parse_retry_after_seconds

logger = setup_logger()

GRAPH_API_MAX_RETRIES = 5

# Rate limits plus the gateway 5xx codes. The default choice.
GRAPH_API_RETRYABLE_STATUSES: frozenset[int] = frozenset({429, 500, 502, 503, 504})

# The narrow set, for sleep_and_retry only.
RETRYABLE_HTTP_STATUSES: frozenset[int] = frozenset({429, 503})

# Transient transport failures, seen both bare and as the cause of a
# ClientRequestException. ChunkedEncodingError and ContentDecodingError are
# siblings of ConnectionError under RequestException, so each is listed.
TRANSIENT_TRANSPORT_EXCEPTIONS: tuple[type[BaseException], ...] = (
    requests.exceptions.ConnectionError,
    requests.exceptions.Timeout,
    requests.exceptions.ChunkedEncodingError,
    requests.exceptions.ContentDecodingError,
)


def backoff_seconds(attempt: int, retry_after: str | None) -> float:
    """Honor a server-provided Retry-After header (numeric seconds or HTTP-date)
    when present, otherwise fall back to capped exponential backoff with equal
    jitter.

    Base sequence is 5s, 10s, 20s, capped at 30s. The actual sleep is drawn
    from ``[base/2, base]`` so that many documents failing at the same instant
    (e.g. during a Graph throttling window) don't all retry on the same tick
    and re-create the thundering herd. Server-provided Retry-After values are
    used verbatim, since those are an explicit instruction rather than a guess.

    ``attempt`` is 0-indexed (0 for the first retry).
    """
    parsed = parse_retry_after_seconds(retry_after)
    if parsed is not None:
        return parsed
    base = min(30, (2**attempt) * 5)
    return base / 2 + random.uniform(0, base / 2)


def graph_error_code(response: requests.Response | None) -> str:
    if response is None:
        return "<no response>"
    try:
        return response.json().get("error", {}).get("code") or "<no code>"
    except Exception:
        logger.debug(
            "Failed to parse Graph error code from response body", exc_info=True
        )
        return "<no code>"


def log_and_raise_for_status(response: requests.Response) -> None:
    """Log the response text and raise for status."""
    try:
        response.raise_for_status()
    except Exception:
        logger.error("HTTP request failed: %s", response.text)
        raise


def sleep_and_retry(
    query_obj: ClientQuery, method_name: str, max_retries: int = 3
) -> Any:
    """
    Execute an office365 SDK query with retry logic for rate limiting and
    transient transport-level failures (e.g. ChunkedEncodingError when
    the server or an upstream gateway closes the connection mid-response).
    """
    for attempt in range(max_retries + 1):
        try:
            return query_obj.execute_query()
        except TRANSIENT_TRANSPORT_EXCEPTIONS as e:
            if attempt >= max_retries:
                logger.warning(
                    "Transport error on %s after %s attempts: %s: %s",
                    method_name,
                    max_retries + 1,
                    type(e).__name__,
                    e,
                )
                raise
            sleep_time = backoff_seconds(attempt, retry_after=None)
            logger.warning(
                "Transport error on %s, attempt %s/%s: %s: %s. "
                "Sleeping %.1fs before retry.",
                method_name,
                attempt + 1,
                max_retries + 1,
                type(e).__name__,
                e,
                sleep_time,
            )
            time.sleep(sleep_time)
            continue
        except ClientRequestException as e:
            status = e.response.status_code if e.response is not None else None

            # Some office365 versions wrap a transport error into a
            # ClientRequestException with no response, still retryable.
            wrapped_transport_error = e.response is None and isinstance(
                e.__cause__ or e.__context__, TRANSIENT_TRANSPORT_EXCEPTIONS
            )

            is_retryable = status in RETRYABLE_HTTP_STATUSES or wrapped_transport_error
            if is_retryable and attempt < max_retries:
                retry_after = (
                    e.response.headers.get("Retry-After")
                    if e.response is not None
                    else None
                )
                sleep_time = backoff_seconds(attempt, retry_after)
                logger.warning(
                    "Retryable error on %s, attempt %s/%s: status=%s. "
                    "Sleeping %.1fs before retry.",
                    method_name,
                    attempt + 1,
                    max_retries + 1,
                    status,
                    sleep_time,
                )
                time.sleep(sleep_time)
                continue

            # Callers swallow expected statuses themselves, such as a 404
            # for a deleted Entra group, so log at warning rather than make
            # this helper a source of Sentry events for handled conditions.
            if e.response is not None:
                logger.warning(
                    "Graph request failed for %s: status=%s, ", method_name, status
                )
            raise e


def graph_api_get_json(
    get_access_token: Callable[[], str],
    url: str,
    params: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Make an authenticated GET request to the Graph API with retry."""
    for attempt in range(GRAPH_API_MAX_RETRIES + 1):
        # Tokens can expire during long traversals, so re-acquire per attempt.
        access_token = get_access_token()
        headers = {"Authorization": f"Bearer {access_token}"}
        try:
            response = requests.get(
                url,
                headers=headers,
                params=params,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            if response.status_code in GRAPH_API_RETRYABLE_STATUSES:
                if attempt < GRAPH_API_MAX_RETRIES:
                    wait = backoff_seconds(attempt, response.headers.get("Retry-After"))
                    logger.warning(
                        "Graph API %s on attempt %s, retrying in %.1fs: %s",
                        response.status_code,
                        attempt + 1,
                        wait,
                        url,
                    )
                    time.sleep(wait)
                    continue
            log_and_raise_for_status(response)
            # ValueError covers the empty/non-JSON 2xx bodies Graph
            # intermittently returns under load.
            return response.json()
        except TRANSIENT_TRANSPORT_EXCEPTIONS + (ValueError,) as e:
            if attempt < GRAPH_API_MAX_RETRIES:
                wait = backoff_seconds(attempt, retry_after=None)
                logger.warning(
                    "Graph API transient error on attempt %s, retrying in %.1fs: %s (%r)",
                    attempt + 1,
                    wait,
                    url,
                    e,
                )
                time.sleep(wait)
                continue
            raise

    raise RuntimeError(
        f"Graph API request failed after {GRAPH_API_MAX_RETRIES + 1} attempts: {url}"
    )


class GraphApiClient:
    """The raw Graph REST surface: a token source plus the versioned Graph base.

    Held by a connector and passed to the drive-item helpers so they can call
    Graph without knowing how the token was obtained.
    """

    def __init__(
        self,
        get_access_token: Callable[[], str],
        graph_api_base: str,
    ) -> None:
        self.get_access_token = get_access_token
        self.graph_api_base = graph_api_base

    def get_json(
        self, url: str, params: dict[str, str] | None = None
    ) -> dict[str, Any]:
        return graph_api_get_json(self.get_access_token, url, params)
