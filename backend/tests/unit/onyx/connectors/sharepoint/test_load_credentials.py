"""Unit tests for SharepointConnector.load_credentials sp_tenant_domain resolution."""

from __future__ import annotations

import base64
from unittest.mock import MagicMock
from unittest.mock import patch

from onyx.connectors.sharepoint.connector import SharepointConnector

SITE_URL = "https://mytenant.sharepoint.com/sites/MySite"
EXPECTED_TENANT_DOMAIN = "mytenant"

CLIENT_SECRET_CREDS = {
    "authentication_method": "client_secret",
    "sp_client_id": "fake-client-id",
    "sp_client_secret": "fake-client-secret",
    "sp_directory_id": "fake-directory-id",
}

CERTIFICATE_CREDS = {
    "authentication_method": "certificate",
    "sp_client_id": "fake-client-id",
    "sp_directory_id": "fake-directory-id",
    "sp_private_key": base64.b64encode(b"fake-pfx-data").decode(),
    "sp_certificate_password": "fake-password",
}


def _make_mock_msal() -> MagicMock:
    mock_app = MagicMock()
    mock_app.acquire_token_for_client.return_value = {"access_token": "fake-token"}
    return mock_app


@patch("onyx.connectors.sharepoint.connector.msal.ConfidentialClientApplication")
@patch("onyx.connectors.sharepoint.connector.GraphClient")
def test_client_secret_with_site_pages_sets_tenant_domain(
    _mock_graph_client: MagicMock,
    mock_msal_cls: MagicMock,
) -> None:
    """client_secret auth + include_site_pages=True must resolve sp_tenant_domain."""
    mock_msal_cls.return_value = _make_mock_msal()
    connector = SharepointConnector(sites=[SITE_URL], include_site_pages=True)

    connector.load_credentials(CLIENT_SECRET_CREDS)

    assert connector.sp_tenant_domain == EXPECTED_TENANT_DOMAIN


@patch("onyx.connectors.sharepoint.connector.msal.ConfidentialClientApplication")
@patch("onyx.connectors.sharepoint.connector.GraphClient")
def test_client_secret_without_site_pages_still_sets_tenant_domain(
    _mock_graph_client: MagicMock,
    mock_msal_cls: MagicMock,
) -> None:
    """client_secret auth + include_site_pages=False must still resolve sp_tenant_domain
    because _create_rest_client_context is also called for drive items."""
    mock_msal_cls.return_value = _make_mock_msal()
    connector = SharepointConnector(sites=[SITE_URL], include_site_pages=False)

    connector.load_credentials(CLIENT_SECRET_CREDS)

    assert connector.sp_tenant_domain == EXPECTED_TENANT_DOMAIN


@patch("onyx.connectors.sharepoint.connector.load_certificate_from_pfx")
@patch("onyx.connectors.sharepoint.connector.msal.ConfidentialClientApplication")
@patch("onyx.connectors.sharepoint.connector.GraphClient")
def test_certificate_with_site_pages_sets_tenant_domain(
    _mock_graph_client: MagicMock,
    mock_msal_cls: MagicMock,
    mock_load_cert: MagicMock,
) -> None:
    """certificate auth + include_site_pages=True must resolve sp_tenant_domain."""
    mock_msal_cls.return_value = _make_mock_msal()
    mock_load_cert.return_value = MagicMock()
    connector = SharepointConnector(sites=[SITE_URL], include_site_pages=True)

    connector.load_credentials(CERTIFICATE_CREDS)

    assert connector.sp_tenant_domain == EXPECTED_TENANT_DOMAIN


@patch("onyx.connectors.sharepoint.connector.load_certificate_from_pfx")
@patch("onyx.connectors.sharepoint.connector.msal.ConfidentialClientApplication")
@patch("onyx.connectors.sharepoint.connector.GraphClient")
def test_certificate_without_site_pages_sets_tenant_domain(
    _mock_graph_client: MagicMock,
    mock_msal_cls: MagicMock,
    mock_load_cert: MagicMock,
) -> None:
    """certificate auth + include_site_pages=False must still resolve sp_tenant_domain
    because _create_rest_client_context is also called for drive items."""
    mock_msal_cls.return_value = _make_mock_msal()
    mock_load_cert.return_value = MagicMock()
    connector = SharepointConnector(sites=[SITE_URL], include_site_pages=False)

    connector.load_credentials(CERTIFICATE_CREDS)

    assert connector.sp_tenant_domain == EXPECTED_TENANT_DOMAIN
