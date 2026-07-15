"""Unit tests for the LumApps client's retry/auth behavior (mocked HTTP)."""

import time
from typing import Any
from unittest.mock import MagicMock

import pytest
import requests

from onyx.connectors.lumapps.client import LumAppsClientError
from onyx.connectors.lumapps.client import OnyxLumApps


def _client_with_token() -> tuple[OnyxLumApps, MagicMock]:
    client = OnyxLumApps(
        base_url="https://example.cell.lumapps.com",
        organization_id="org-1",
        application_id="app",
        api_key="key",
        service_user="svc@example.com",
    )
    client._token = "cached-token"
    client._token_expiry_monotonic = time.monotonic() + 3600
    session = MagicMock()
    client._session = session
    return client, session


def _response(status_code: int, body: dict[str, Any] | None = None) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.headers = {}
    response.json.return_value = body if body is not None else {}
    response.text = "error-body"
    return response


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "onyx.connectors.lumapps.client.time.sleep", lambda _seconds: None
    )


def test_network_errors_are_retried() -> None:
    """Connection resets / timeouts back off and retry like a 5xx instead of
    aborting the indexing attempt."""
    client, session = _client_with_token()
    session.request.side_effect = [
        requests.ConnectionError("reset by peer"),
        requests.Timeout("timed out"),
        _response(200, {"items": [], "more": False}),
    ]

    assert client.list_content({}) == {"items": [], "more": False}
    assert session.request.call_count == 3


def test_exhausted_network_errors_raise_client_error() -> None:
    """After all retries fail, the network error surfaces as LumAppsClientError
    so callers (validation included) can translate it."""
    client, session = _client_with_token()
    session.request.side_effect = requests.ConnectionError("down")

    with pytest.raises(LumAppsClientError) as exc_info:
        client.list_content({})
    assert exc_info.value.status_code == 503
    assert "down" in exc_info.value.message


def test_exhausted_http_errors_preserve_upstream_status() -> None:
    """When retries are exhausted on an HTTP error, the real upstream status is
    surfaced (not a generic 503) so callers can translate 429/5xx correctly."""
    client, session = _client_with_token()
    session.request.side_effect = [_response(503) for _ in range(5)]

    with pytest.raises(LumAppsClientError) as exc_info:
        client.list_content({})
    assert exc_info.value.status_code == 503

    client, session = _client_with_token()
    session.request.side_effect = [_response(429) for _ in range(5)]
    with pytest.raises(LumAppsClientError) as exc_info:
        client.list_content({})
    assert exc_info.value.status_code == 429


def test_429_retry_does_not_remint_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """Rate-limit/server-error retries must reuse the cached token; only a 401
    invalidates it."""
    client, session = _client_with_token()
    mint_mock = MagicMock()
    monkeypatch.setattr(client, "_mint_token", mint_mock)
    session.request.side_effect = [
        _response(429),
        _response(200, {"items": [], "more": False}),
    ]

    assert client.list_content({}) == {"items": [], "more": False}
    mint_mock.assert_not_called()


def test_401_invalidates_token_and_remints_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, session = _client_with_token()

    def _mint() -> None:
        client._token = "fresh-token"
        client._token_expiry_monotonic = time.monotonic() + 3600

    mint_mock = MagicMock(side_effect=_mint)
    monkeypatch.setattr(client, "_mint_token", mint_mock)
    session.request.side_effect = [
        _response(401),
        _response(200, {"items": [], "more": False}),
    ]

    assert client.list_content({}) == {"items": [], "more": False}
    mint_mock.assert_called_once()
    sent_auth = session.request.call_args_list[1].kwargs["headers"]["Authorization"]
    assert sent_auth == "Bearer fresh-token"


def test_malformed_data_response_raises_client_error() -> None:
    """A 200 with an empty/non-JSON body surfaces as LumAppsClientError (not a raw
    JSONDecodeError) so validation/indexing translate it consistently."""
    client, session = _client_with_token()
    bad = MagicMock()
    bad.status_code = 200
    bad.headers = {}
    bad.text = "<html>not json</html>"
    bad.json.side_effect = ValueError("no json")
    session.request.side_effect = [bad]

    with pytest.raises(LumAppsClientError) as exc_info:
        client.list_content({})
    assert exc_info.value.status_code == 200


def test_malformed_token_response_raises_client_error() -> None:
    """A 200 token response missing access_token surfaces as LumAppsClientError
    (not a KeyError), keeping validate_connector_settings() able to translate it."""
    client = OnyxLumApps(
        base_url="https://example.cell.lumapps.com",
        organization_id="org-1",
        application_id="app",
        api_key="key",
        service_user="svc@example.com",
    )
    session = MagicMock()
    client._session = session
    token_resp = MagicMock()
    token_resp.status_code = 200
    token_resp.json.return_value = {}  # missing access_token
    session.post.return_value = token_resp

    with pytest.raises(LumAppsClientError):
        client.list_content({})  # triggers token mint via _bearer()


def test_401_after_transient_retry_still_remints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 401 that lands after an earlier transient 5xx retry must still trigger the
    one-time token refresh (not gated to the first loop iteration)."""
    client, session = _client_with_token()

    def _mint() -> None:
        client._token = "fresh-token"
        client._token_expiry_monotonic = time.monotonic() + 3600

    mint_mock = MagicMock(side_effect=_mint)
    monkeypatch.setattr(client, "_mint_token", mint_mock)
    session.request.side_effect = [
        _response(503),  # transient retry
        _response(401),  # token rejected AFTER the retry
        _response(200, {"items": [], "more": False}),
    ]

    assert client.list_content({}) == {"items": [], "more": False}
    mint_mock.assert_called_once()


def test_no_backoff_sleep_on_final_attempt(monkeypatch: pytest.MonkeyPatch) -> None:
    """Exhausted retries must not sleep after the last attempt — no wasted delay."""
    sleep_mock = MagicMock()
    monkeypatch.setattr("onyx.connectors.lumapps.client.time.sleep", sleep_mock)
    client, session = _client_with_token()
    session.request.side_effect = [_response(503) for _ in range(5)]

    with pytest.raises(LumAppsClientError):
        client.list_content({})
    # 5 attempts, but only 4 backoff sleeps (none after the final attempt).
    assert sleep_mock.call_count == 4
