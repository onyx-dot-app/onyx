"""Unit tests for the credential checks SharepointConnector.load_credentials
owns and for tenant-domain resolution through the gateway."""

from __future__ import annotations

import base64
from unittest.mock import MagicMock, patch

import pytest

from onyx.connectors.credentials_provider import OnyxStaticCredentialsProvider
from onyx.connectors.exceptions import ConnectorValidationError
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


@pytest.mark.parametrize("creds", [CLIENT_SECRET_CREDS, CERTIFICATE_CREDS])
def test_tenant_domain_resolves_from_the_site_urls(creds: dict[str, str]) -> None:
    """Both credential kinds resolve the tenant from the configured site URL,
    which the REST reads for drive items and pages need."""
    connector = SharepointConnector(sites=[SITE_URL])

    connector.load_credentials(creds)

    assert connector.ops.resolve_tenant_domain() == EXPECTED_TENANT_DOMAIN


@pytest.mark.parametrize("missing_field", ["sp_private_key", "sp_certificate_password"])
def test_certificate_credential_needs_both_secrets(missing_field: str) -> None:
    creds = dict(CERTIFICATE_CREDS)
    del creds[missing_field]
    connector = SharepointConnector(sites=[SITE_URL])

    with pytest.raises(ConnectorValidationError, match="certificate password"):
        connector.load_credentials(creds)


@patch("onyx.connectors.microsoft_utils.graph_auth.msal.ConfidentialClientApplication")
def test_unknown_auth_method_is_rejected_before_msal(mock_msal_cls: MagicMock) -> None:
    """The credential string is parsed at the connector boundary, so a typo
    fails with the value named and never reaches MSAL."""
    creds = dict(CLIENT_SECRET_CREDS, authentication_method="kerberos")
    connector = SharepointConnector(sites=[SITE_URL])

    with pytest.raises(ConnectorValidationError, match="kerberos"):
        connector.load_credentials(creds)

    mock_msal_cls.assert_not_called()


@pytest.mark.parametrize("missing_field", ["sp_client_id", "sp_directory_id"])
def test_missing_id_is_a_validation_error(missing_field: str) -> None:
    """SharePoint owns these checks, so an absent or blank id must still cancel
    the attempt rather than reach MSAL."""
    for blank in ("", None):
        creds = dict(CLIENT_SECRET_CREDS)
        if blank is None:
            del creds[missing_field]
        else:
            creds[missing_field] = blank

        connector = SharepointConnector(sites=[SITE_URL])
        with pytest.raises(ConnectorValidationError):
            connector.load_credentials(creds)


@pytest.mark.parametrize("missing_field", ["sp_client_id", "sp_directory_id"])
def test_provider_path_checks_the_same_fields(missing_field: str) -> None:
    """The factory hands the connector a credentials provider instead of a
    dict, and a bad credential must fail pairing on that path too."""
    creds = dict(CLIENT_SECRET_CREDS)
    del creds[missing_field]
    connector = SharepointConnector(sites=[SITE_URL])

    with pytest.raises(ConnectorValidationError):
        connector.set_credentials_provider(
            OnyxStaticCredentialsProvider(None, "sharepoint", creds)
        )
