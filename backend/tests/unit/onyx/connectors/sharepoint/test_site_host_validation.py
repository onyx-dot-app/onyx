"""The SharePoint REST token is minted for one tenant host. Any other host that
receives it, an attacker domain or another tenant under the same cloud suffix,
gets a credential it has no claim to."""

import pytest

from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.microsoft_utils.config import (
    DEFAULT_AUTHORITY_HOST,
    DEFAULT_GRAPH_API_HOST,
)
from onyx.connectors.sharepoint.connector import SharepointConnector
from onyx.connectors.sharepoint.connector_utils import validate_site_url_host
from tests.unit.onyx.connectors.sharepoint.sharepoint_gateway_fakes import (
    connector_with_gateway,
)

SITE_URL = "https://tenant.sharepoint.com/sites/MySite"
ONEDRIVE_URL = "https://tenant-my.sharepoint.com/personal/alice_tenant_com"
SUFFIX = "sharepoint.com"


def test_accepts_the_configured_tenant_host() -> None:
    validate_site_url_host(SITE_URL, SUFFIX, "tenant")


def test_accepts_the_onedrive_my_host() -> None:
    """OneDrive lives on '<tenant>-my.<suffix>' and shares the tenant's token."""
    validate_site_url_host(ONEDRIVE_URL, SUFFIX, "tenant")

    # A connector whose first site is the OneDrive host resolves the tenant
    # domain as 'tenant-my'; both forms must still be accepted.
    validate_site_url_host(ONEDRIVE_URL, SUFFIX, "tenant-my")
    validate_site_url_host(SITE_URL, SUFFIX, "tenant-my")


def test_rejects_another_tenant_under_the_same_suffix() -> None:
    """A suffix-only check would let 'victim.sharepoint.com' take our token."""
    with pytest.raises(ConnectorValidationError, match="tenant's SharePoint host"):
        validate_site_url_host(
            "https://victim.sharepoint.com/sites/Payroll", SUFFIX, "tenant"
        )


def test_rejects_an_unrelated_host() -> None:
    with pytest.raises(ConnectorValidationError, match="sharepoint.com"):
        validate_site_url_host(
            "https://tenant.sharepoint.com.attacker.example/sites/MySite",
            SUFFIX,
            "tenant",
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
    connector = SharepointConnector(
        sites=[site_url], graph_api_host=graph_api_host, authority_host=authority_host
    )
    connector_with_gateway(connector)

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
    connector = SharepointConnector(
        sites=[SITE_URL],
        graph_api_host=DEFAULT_GRAPH_API_HOST,
        authority_host=DEFAULT_AUTHORITY_HOST,
    )

    connector._validate_site_url_host("https://any.sharepoint.com/sites/MySite")
    with pytest.raises(ConnectorValidationError):
        connector._validate_site_url_host("https://attacker.example/sites/MySite")


def test_tenant_host_is_enforced_once_credentials_load() -> None:
    connector = SharepointConnector(sites=[SITE_URL])
    connector_with_gateway(connector)

    connector._validate_site_url_host(SITE_URL)
    with pytest.raises(ConnectorValidationError, match="tenant's SharePoint host"):
        connector._validate_site_url_host("https://any.sharepoint.com/sites/MySite")
