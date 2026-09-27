"""Unit tests for SharepointConnector._validate_site_url_host.

The SharePoint REST token is minted for one tenant host. Any other host that
receives it — an attacker domain, or another tenant under the same cloud
suffix — gets a credential it has no claim to.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.sharepoint.connector import (
    DEFAULT_AUTHORITY_HOST,
    DEFAULT_GRAPH_API_HOST,
    SharepointConnector,
)

SITE_URL = "https://tenant.sharepoint.com/sites/MySite"
ONEDRIVE_URL = "https://tenant-my.sharepoint.com/personal/alice_tenant_com"


def _make_connector(
    site_url: str = SITE_URL,
    tenant_domain: str | None = "tenant",
    graph_api_host: str = DEFAULT_GRAPH_API_HOST,
    authority_host: str = DEFAULT_AUTHORITY_HOST,
) -> SharepointConnector:
    connector = SharepointConnector(
        sites=[site_url],
        graph_api_host=graph_api_host,
        authority_host=authority_host,
    )
    connector.msal_app = MagicMock()
    connector.sp_tenant_domain = tenant_domain
    connector._credential_json = {"sp_client_id": "x", "sp_directory_id": "y"}
    return connector


def test_accepts_the_configured_tenant_host() -> None:
    _make_connector()._validate_site_url_host(SITE_URL)


def test_accepts_the_onedrive_my_host() -> None:
    """OneDrive lives on '<tenant>-my.<suffix>' and shares the tenant's token."""
    connector = _make_connector()
    connector._validate_site_url_host(ONEDRIVE_URL)

    # A connector whose first site is the OneDrive host resolves the tenant
    # domain as 'tenant-my'; both forms must still be accepted.
    onedrive_first = _make_connector(ONEDRIVE_URL, tenant_domain="tenant-my")
    onedrive_first._validate_site_url_host(ONEDRIVE_URL)
    onedrive_first._validate_site_url_host(SITE_URL)


def test_rejects_another_tenant_under_the_same_suffix() -> None:
    """A suffix-only check would let 'victim.sharepoint.com' take our token."""
    connector = _make_connector()

    with pytest.raises(ConnectorValidationError, match="tenant's SharePoint host"):
        connector._validate_site_url_host("https://victim.sharepoint.com/sites/Payroll")


def test_rejects_an_unrelated_host() -> None:
    connector = _make_connector()

    with pytest.raises(ConnectorValidationError, match="sharepoint.com"):
        connector._validate_site_url_host(
            "https://tenant.sharepoint.com.attacker.example/sites/MySite"
        )


@pytest.mark.parametrize(
    "graph_api_host,authority_host,suffix",
    [
        (
            "https://graph.microsoft.us",
            "https://login.microsoftonline.us",
            "sharepoint.us",
        ),
        (
            "https://microsoftgraph.chinacloudapi.cn",
            "https://login.chinacloudapi.cn",
            "sharepoint.cn",
        ),
    ],
)
def test_national_clouds_keep_working(
    graph_api_host: str, authority_host: str, suffix: str
) -> None:
    """The suffix is environment-derived, so gov/CN tenants validate normally."""
    site_url = f"https://tenant.{suffix}/sites/MySite"
    connector = _make_connector(
        site_url, graph_api_host=graph_api_host, authority_host=authority_host
    )

    assert connector.sharepoint_domain_suffix == suffix
    connector._validate_site_url_host(site_url)
    connector._validate_site_url_host(f"https://tenant-my.{suffix}/personal/alice")

    with pytest.raises(ConnectorValidationError):
        connector._validate_site_url_host(f"https://victim.{suffix}/sites/MySite")
    # The commercial cloud host is a different tenant boundary.
    with pytest.raises(ConnectorValidationError):
        connector._validate_site_url_host(SITE_URL)


def test_suffix_is_enforced_before_credentials_load() -> None:
    """Without a resolved tenant domain the suffix check still applies."""
    connector = _make_connector(tenant_domain=None)

    connector._validate_site_url_host("https://any.sharepoint.com/sites/MySite")
    with pytest.raises(ConnectorValidationError):
        connector._validate_site_url_host("https://attacker.example/sites/MySite")


@patch("onyx.connectors.sharepoint.connector.acquire_token_for_rest")
@patch("onyx.connectors.sharepoint.connector.ClientContext")
def test_rest_context_is_never_built_for_a_foreign_tenant(
    mock_client_ctx_cls: MagicMock,
    _mock_acquire: MagicMock,
) -> None:
    """The token-minting path refuses the host before any client is created."""
    connector = _make_connector()
    connector.load_credentials = MagicMock()

    with pytest.raises(ConnectorValidationError):
        connector._create_rest_client_context(
            "https://victim.sharepoint.com/sites/Payroll"
        )

    mock_client_ctx_cls.assert_not_called()
