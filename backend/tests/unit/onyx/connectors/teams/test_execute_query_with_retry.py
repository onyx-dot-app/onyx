"""Tests for the Microsoft Graph SDK retry helper used by the Teams connector.

These exercise `execute_query_with_retry`, Teams' policy on the shared
`sleep_and_retry`: it retries the wide Graph status set (rate limits + 5xx
gateway/server hiccups) and transport drops. A live daily-connector test cannot
reliably induce a 502, so the retry behaviour is verified here in isolation.
"""

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import requests
from office365.runtime.client_request_exception import ClientRequestException

from onyx.connectors.microsoft_utils.graph_client import (
    GRAPH_API_RETRYABLE_STATUSES,
    backoff_seconds,
)
from onyx.connectors.teams.utils import execute_query_with_retry

# The sleep lives in the shared loop, not in the Teams wrapper.
_SLEEP = "onyx.connectors.microsoft_utils.graph_client.time.sleep"


def _client_request_exception(
    status_code: int,
    headers: dict[str, str] | None = None,
) -> ClientRequestException:
    """Build a ClientRequestException carrying a response with the given status.

    `ClientRequestException.__init__` reads `response.headers` and
    `response.content`, so those must be present and well-formed.
    """
    response = MagicMock()
    response.status_code = status_code
    response.headers = headers or {}
    response.content = b""
    return ClientRequestException("error", response=response)


def _query_returning(*side_effects: Any) -> MagicMock:
    query = MagicMock()
    query.execute_query = MagicMock(side_effect=list(side_effects))
    return query


def test_returns_result_without_retry_on_success() -> None:
    sentinel = object()
    query = _query_returning(sentinel)

    with patch(_SLEEP) as mock_sleep:
        result = execute_query_with_retry(query, method_name="test")

    assert result is sentinel
    assert query.execute_query.call_count == 1
    mock_sleep.assert_not_called()


@pytest.mark.parametrize("status", sorted(GRAPH_API_RETRYABLE_STATUSES))
def test_retries_transient_status_then_succeeds(status: int) -> None:
    sentinel = object()
    query = _query_returning(_client_request_exception(status), sentinel)

    with patch(_SLEEP) as mock_sleep:
        result = execute_query_with_retry(query, method_name="test")

    assert result is sentinel
    assert query.execute_query.call_count == 2
    mock_sleep.assert_called_once()


@pytest.mark.parametrize("status", [400, 401, 403, 404])
def test_does_not_retry_non_retryable_status(status: int) -> None:
    query = _query_returning(_client_request_exception(status))

    with patch(_SLEEP) as mock_sleep:
        with pytest.raises(ClientRequestException):
            execute_query_with_retry(query, method_name="test")

    assert query.execute_query.call_count == 1
    mock_sleep.assert_not_called()


def test_reraises_after_exhausting_retries() -> None:
    # Always fails with a retryable status.
    query = MagicMock()
    query.execute_query = MagicMock(
        side_effect=_client_request_exception(502),
    )

    with patch(_SLEEP) as mock_sleep:
        with pytest.raises(ClientRequestException):
            execute_query_with_retry(query, method_name="test", max_retries=2)

    # max_retries=2 => 3 total attempts, sleeping between each of the first two.
    assert query.execute_query.call_count == 3
    assert mock_sleep.call_count == 2


def test_does_not_retry_when_response_is_missing() -> None:
    # A ClientRequestException with no response is not retryable unless a
    # transport error is chained as its cause. (The office365 ctor dereferences
    # response.headers, so build it normally then null the response.)
    exc = _client_request_exception(502)
    exc.response = None
    query = _query_returning(exc)

    with patch(_SLEEP) as mock_sleep:
        with pytest.raises(ClientRequestException):
            execute_query_with_retry(query, method_name="test")

    assert query.execute_query.call_count == 1
    mock_sleep.assert_not_called()


def test_retries_transport_drop_then_succeeds() -> None:
    """A connection reset mid-body is retried like a transient status."""
    sentinel = object()
    query = _query_returning(
        requests.exceptions.ChunkedEncodingError("reset"), sentinel
    )

    with patch(_SLEEP) as mock_sleep:
        result = execute_query_with_retry(query, method_name="test")

    assert result is sentinel
    assert query.execute_query.call_count == 2
    mock_sleep.assert_called_once()


def test_backoff_honors_numeric_retry_after() -> None:
    # An explicit Retry-After is used verbatim, not jittered.
    assert backoff_seconds(attempt=0, retry_after="7") == 7.0


def test_backoff_falls_back_to_capped_jittered_exponential() -> None:
    # Without a Retry-After, sleep stays within [base/2, base] for base=min(30, 5*2^n).
    for attempt, base in [(0, 5), (1, 10), (2, 20), (3, 30), (10, 30)]:
        delay = backoff_seconds(attempt=attempt, retry_after=None)
        assert base / 2 <= delay <= base


def test_backoff_honors_http_date_retry_after() -> None:
    # An already-elapsed HTTP-date Retry-After is honored verbatim (0s wait),
    # not treated as unparseable.
    assert backoff_seconds(attempt=0, retry_after="Wed, 21 Oct 2015 07:28:00 GMT") == 0


def test_backoff_ignores_unparseable_retry_after() -> None:
    # Genuinely unparseable values fall through to jittered exponential backoff.
    delay = backoff_seconds(attempt=0, retry_after="not-a-date")
    assert 2.5 <= delay <= 5
