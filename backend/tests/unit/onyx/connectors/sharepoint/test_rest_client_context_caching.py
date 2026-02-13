"""Unit tests for SharepointConnector._create_rest_client_context caching."""

from __future__ import annotations

from unittest.mock import MagicMock
from unittest.mock import patch

from onyx.connectors.sharepoint.connector import _REST_CTX_MAX_AGE_S
from onyx.connectors.sharepoint.connector import SharepointConnector

SITE_A = "https://tenant.sharepoint.com/sites/SiteA"
SITE_B = "https://tenant.sharepoint.com/sites/SiteB"

FAKE_CREDS = {"sp_client_id": "x", "sp_directory_id": "y"}


def _make_connector() -> SharepointConnector:
    """Return a SharepointConnector with minimal credentials wired up."""
    connector = SharepointConnector(sites=[SITE_A])
    connector.msal_app = MagicMock()
    connector.sp_tenant_domain = "tenant"
    connector._credential_json = FAKE_CREDS
    return connector


def _noop_load_credentials(connector: SharepointConnector) -> MagicMock:
    """Patch load_credentials to just swap in a fresh MagicMock for msal_app."""

    def _fake_load(creds: dict) -> None:  # noqa: ARG001, ARG002
        connector.msal_app = MagicMock()

    mock = MagicMock(side_effect=_fake_load)
    connector.load_credentials = mock  # type: ignore[method-assign]
    return mock


def _fresh_client_context() -> MagicMock:
    """Return a MagicMock for ClientContext that produces a distinct object per call."""
    mock_cls = MagicMock()
    # Each ClientContext(url).with_access_token(cb) returns a unique sentinel
    mock_cls.side_effect = lambda url: MagicMock()  # noqa: ARG005
    return mock_cls


@patch("onyx.connectors.sharepoint.connector.acquire_token_for_rest")
@patch("onyx.connectors.sharepoint.connector.ClientContext")
def test_returns_cached_context_within_max_age(
    mock_client_ctx_cls: MagicMock,
    _mock_acquire: MagicMock,
) -> None:
    """Repeated calls with the same site_url within the TTL return the same object."""
    mock_client_ctx_cls.side_effect = lambda url: MagicMock()  # noqa: ARG005
    connector = _make_connector()
    _noop_load_credentials(connector)

    ctx1 = connector._create_rest_client_context(SITE_A)
    ctx2 = connector._create_rest_client_context(SITE_A)

    assert ctx1 is ctx2
    assert mock_client_ctx_cls.call_count == 1


@patch("onyx.connectors.sharepoint.connector.time")
@patch("onyx.connectors.sharepoint.connector.acquire_token_for_rest")
@patch("onyx.connectors.sharepoint.connector.ClientContext")
def test_rebuilds_context_after_max_age(
    mock_client_ctx_cls: MagicMock,
    _mock_acquire: MagicMock,
    mock_time: MagicMock,
) -> None:
    """After _REST_CTX_MAX_AGE_S the cached context is replaced."""
    mock_client_ctx_cls.side_effect = lambda url: MagicMock()  # noqa: ARG005
    connector = _make_connector()
    _noop_load_credentials(connector)

    mock_time.monotonic.return_value = 0.0
    ctx1 = connector._create_rest_client_context(SITE_A)

    # Just past the boundary — should rebuild
    mock_time.monotonic.return_value = _REST_CTX_MAX_AGE_S + 1
    ctx2 = connector._create_rest_client_context(SITE_A)

    assert ctx1 is not ctx2
    assert mock_client_ctx_cls.call_count == 2


@patch("onyx.connectors.sharepoint.connector.acquire_token_for_rest")
@patch("onyx.connectors.sharepoint.connector.ClientContext")
def test_rebuilds_context_on_site_change(
    mock_client_ctx_cls: MagicMock,
    _mock_acquire: MagicMock,
) -> None:
    """Switching to a different site_url forces a new context."""
    mock_client_ctx_cls.side_effect = lambda url: MagicMock()  # noqa: ARG005
    connector = _make_connector()
    _noop_load_credentials(connector)

    ctx_a = connector._create_rest_client_context(SITE_A)
    ctx_b = connector._create_rest_client_context(SITE_B)

    assert ctx_a is not ctx_b
    assert mock_client_ctx_cls.call_count == 2


@patch("onyx.connectors.sharepoint.connector.time")
@patch("onyx.connectors.sharepoint.connector.acquire_token_for_rest")
@patch("onyx.connectors.sharepoint.connector.ClientContext")
def test_load_credentials_called_on_rebuild(
    _mock_client_ctx_cls: MagicMock,
    _mock_acquire: MagicMock,
    mock_time: MagicMock,
) -> None:
    """load_credentials is called every time the context is rebuilt."""
    _mock_client_ctx_cls.side_effect = lambda url: MagicMock()  # noqa: ARG005
    connector = _make_connector()
    mock_load = _noop_load_credentials(connector)

    # First call — rebuild (no cache yet)
    mock_time.monotonic.return_value = 0.0
    connector._create_rest_client_context(SITE_A)
    assert mock_load.call_count == 1

    # Second call — cache hit, no rebuild
    mock_time.monotonic.return_value = 100.0
    connector._create_rest_client_context(SITE_A)
    assert mock_load.call_count == 1

    # Third call — expired, rebuild
    mock_time.monotonic.return_value = _REST_CTX_MAX_AGE_S + 1
    connector._create_rest_client_context(SITE_A)
    assert mock_load.call_count == 2

    # Fourth call — site change, rebuild
    mock_time.monotonic.return_value = _REST_CTX_MAX_AGE_S + 2
    connector._create_rest_client_context(SITE_B)
    assert mock_load.call_count == 3
