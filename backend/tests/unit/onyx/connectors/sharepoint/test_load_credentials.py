"""Unit tests for SharePoint connector load_credentials method."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from onyx.connectors.sharepoint.connector import SharepointConnector


class MockVerifiedDomain:
    def __init__(self, name: str) -> None:
        self.name = name


class MockOrganization:
    def __init__(self, verified_domains: list[MockVerifiedDomain]) -> None:
        self.verified_domains = verified_domains


class MockOrganizationQuery:
    def __init__(self, organizations: list[MockOrganization]) -> None:
        self._organizations = organizations

    def get(self) -> MockOrganizationQuery:
        return self

    def execute_query(self) -> list[MockOrganization]:
        return self._organizations


class MockGraphClient:
    def __init__(self, organizations: list[MockOrganization]) -> None:
        self.organization = MockOrganizationQuery(organizations)


def _create_mock_msal_app() -> MagicMock:
    """Create a mock MSAL ConfidentialClientApplication."""
    mock_app = MagicMock()
    mock_app.acquire_token_for_client.return_value = {
        "access_token": "fake_token",
        "token_type": "Bearer",
    }
    return mock_app


@pytest.fixture
def client_secret_credentials() -> dict[str, Any]:
    """Credentials for client secret authentication."""
    return {
        "authentication_method": "client_secret",
        "sp_client_id": "test-client-id",
        "sp_client_secret": "test-client-secret",
        "sp_directory_id": "test-directory-id",
    }


@pytest.fixture
def certificate_credentials() -> dict[str, Any]:
    """Credentials for certificate authentication."""
    return {
        "authentication_method": "certificate",
        "sp_client_id": "test-client-id",
        "sp_directory_id": "test-directory-id",
        "sp_private_key": "dGVzdA==",  # base64("test")
        "sp_certificate_password": "test-password",
    }


@patch("onyx.connectors.sharepoint.connector.GraphClient")
@patch("onyx.connectors.sharepoint.connector.msal.ConfidentialClientApplication")
def test_load_credentials_client_secret_sets_tenant_domain(
    mock_msal_class: MagicMock,
    mock_graph_client_class: MagicMock,
    client_secret_credentials: dict[str, Any],
) -> None:
    """Test that load_credentials sets sp_tenant_domain when using client secret auth."""
    # Setup mocks
    mock_msal_class.return_value = _create_mock_msal_app()

    mock_org = MockOrganization([MockVerifiedDomain("contoso.onmicrosoft.com")])
    mock_graph_client = MockGraphClient([mock_org])
    mock_graph_client_class.return_value = mock_graph_client

    # Create connector and load credentials
    connector = SharepointConnector()
    connector.load_credentials(client_secret_credentials)

    # Verify msal_app is set
    assert connector.msal_app is not None

    # Verify sp_tenant_domain is set (should be "contoso" - the part before the first dot)
    assert connector.sp_tenant_domain == "contoso"


@patch("onyx.connectors.sharepoint.connector.GraphClient")
@patch("onyx.connectors.sharepoint.connector.msal.ConfidentialClientApplication")
@patch("onyx.connectors.sharepoint.connector.load_certificate_from_pfx")
def test_load_credentials_certificate_sets_tenant_domain(
    mock_load_cert: MagicMock,
    mock_msal_class: MagicMock,
    mock_graph_client_class: MagicMock,
    certificate_credentials: dict[str, Any],
) -> None:
    """Test that load_credentials sets sp_tenant_domain when using certificate auth."""
    # Setup mocks
    mock_cert_data = MagicMock()
    mock_cert_data.model_dump.return_value = {
        "private_key": "key",
        "thumbprint": "thumb",
    }
    mock_load_cert.return_value = mock_cert_data

    mock_msal_class.return_value = _create_mock_msal_app()

    mock_org = MockOrganization([MockVerifiedDomain("fabrikam.onmicrosoft.com")])
    mock_graph_client = MockGraphClient([mock_org])
    mock_graph_client_class.return_value = mock_graph_client

    # Create connector and load credentials
    connector = SharepointConnector()
    connector.load_credentials(certificate_credentials)

    # Verify msal_app is set
    assert connector.msal_app is not None

    # Verify sp_tenant_domain is set (should be "fabrikam" - the part before the first dot)
    assert connector.sp_tenant_domain == "fabrikam"


@patch("onyx.connectors.sharepoint.connector.GraphClient")
@patch("onyx.connectors.sharepoint.connector.msal.ConfidentialClientApplication")
def test_load_credentials_tenant_domain_extracted_correctly(
    mock_msal_class: MagicMock,
    mock_graph_client_class: MagicMock,
    client_secret_credentials: dict[str, Any],
) -> None:
    """Test that tenant domain is extracted correctly from verified domain name."""
    mock_msal_class.return_value = _create_mock_msal_app()

    # Test with a more complex domain name
    mock_org = MockOrganization([MockVerifiedDomain("my-company.sharepoint.com")])
    mock_graph_client = MockGraphClient([mock_org])
    mock_graph_client_class.return_value = mock_graph_client

    connector = SharepointConnector()
    connector.load_credentials(client_secret_credentials)

    # Should extract only the first part before the dot
    assert connector.sp_tenant_domain == "my-company"
