"""Tests for `_retry`, the raw Microsoft Graph request path in the Teams
connector (`execute_request_direct`), used by `fetch_messages`/`fetch_replies`.

`_retry` retries transient Graph errors (rate limits + 5xx gateway/server
hiccups) with backoff and surfaces everything else immediately. A live
daily-connector test cannot reliably induce a 5xx, so the behaviour is verified
here in isolation.
"""

from typing import Any
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from requests.exceptions import HTTPError

from onyx.connectors.teams.utils import _retry
from onyx.connectors.teams.utils import GRAPH_API_RETRYABLE_STATUSES


def _response(
    ok: bool,
    status_code: int = 200,
    json_value: Any = None,
    headers: dict[str, str] | None = None,
) -> MagicMock:
    response = MagicMock()
    response.ok = ok
    response.status_code = status_code
    response.headers = headers or {}
    response.json = MagicMock(return_value={} if json_value is None else json_value)
    if not ok:
        response.raise_for_status = MagicMock(
            side_effect=HTTPError(f"{status_code} error")
        )
    return response


def _graph_client(*responses: MagicMock) -> MagicMock:
    graph_client = MagicMock()
    graph_client.execute_request_direct = MagicMock(side_effect=list(responses))
    return graph_client


def test_returns_json_without_retry_on_success() -> None:
    payload = {"value": [1, 2, 3]}
    graph_client = _graph_client(_response(ok=True, json_value=payload))

    with patch("onyx.connectors.teams.utils.time.sleep") as mock_sleep:
        result = _retry(graph_client=graph_client, request_url="teams")

    assert result == payload
    assert graph_client.execute_request_direct.call_count == 1
    mock_sleep.assert_not_called()


@pytest.mark.parametrize("status", sorted(GRAPH_API_RETRYABLE_STATUSES))
def test_retries_transient_status_then_succeeds(status: int) -> None:
    payload = {"ok": True}
    graph_client = _graph_client(
        _response(ok=False, status_code=status),
        _response(ok=True, json_value=payload),
    )

    with patch("onyx.connectors.teams.utils.time.sleep") as mock_sleep:
        result = _retry(graph_client=graph_client, request_url="teams")

    assert result == payload
    assert graph_client.execute_request_direct.call_count == 2
    mock_sleep.assert_called_once()


@pytest.mark.parametrize("status", [400, 401, 403, 404])
def test_does_not_retry_non_retryable_status(status: int) -> None:
    graph_client = _graph_client(_response(ok=False, status_code=status))

    with patch("onyx.connectors.teams.utils.time.sleep") as mock_sleep:
        with pytest.raises(HTTPError):
            _retry(graph_client=graph_client, request_url="teams")

    assert graph_client.execute_request_direct.call_count == 1
    mock_sleep.assert_not_called()


def test_raises_when_json_is_not_an_object() -> None:
    # A 200 whose body is a JSON array (not an object) is a contract violation.
    graph_client = _graph_client(_response(ok=True, json_value=[1, 2, 3]))

    with patch("onyx.connectors.teams.utils.time.sleep"):
        with pytest.raises(RuntimeError):
            _retry(graph_client=graph_client, request_url="teams")


def test_raises_runtime_error_after_exhausting_retries() -> None:
    # Always returns a retryable status; _retry caps at MAX_RETRIES (10) attempts
    # and then raises rather than looping forever.
    graph_client = MagicMock()
    graph_client.execute_request_direct = MagicMock(
        return_value=_response(ok=False, status_code=503),
    )

    with patch("onyx.connectors.teams.utils.time.sleep") as mock_sleep:
        with pytest.raises(RuntimeError, match="Max number of retries"):
            _retry(graph_client=graph_client, request_url="teams")

    # 10 attempts are made, but the final (exhausted) attempt raises immediately
    # instead of sleeping, so there are only 9 backoff sleeps.
    assert graph_client.execute_request_direct.call_count == 10
    assert mock_sleep.call_count == 9
