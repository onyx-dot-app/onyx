"""The shared MSAL builder must not validate the client and directory ids.

Teams passes its credential straight through and expects an ordinary failure.
Raising ``ConnectorValidationError`` here would cancel the index attempt for
every caller, which is SharePoint's behaviour, not Teams'. SharePoint keeps its
own presence checks in ``load_credentials``.
"""

from __future__ import annotations

import base64
from unittest.mock import patch

import pytest

from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.microsoft_utils.graph_auth import (
    CertificateData,
    MicrosoftAuthMethod,
    build_msal_app,
)

AUTHORITY_HOST = "https://login.microsoftonline.com"


@pytest.mark.parametrize(
    ("client_id", "directory_id"),
    [("", "tenant-id"), ("client-id", ""), ("", "")],
)
def test_empty_ids_reach_msal_instead_of_raising_validation(
    client_id: str, directory_id: str
) -> None:
    with patch(
        "onyx.connectors.microsoft_utils.graph_auth.msal.ConfidentialClientApplication"
    ) as msal_app:
        build_msal_app(
            client_id=client_id,
            directory_id=directory_id,
            authority_host=AUTHORITY_HOST,
            client_secret="secret",
        )

    msal_app.assert_called_once()
    assert msal_app.call_args.kwargs["client_id"] == client_id


def test_certificate_path_still_rejects_a_missing_key() -> None:
    with pytest.raises(ConnectorValidationError):
        build_msal_app(
            client_id="client-id",
            directory_id="tenant-id",
            authority_host=AUTHORITY_HOST,
            auth_method=MicrosoftAuthMethod.CERTIFICATE.value,
        )


def test_unknown_auth_method_is_rejected() -> None:
    with pytest.raises(ConnectorValidationError):
        build_msal_app(
            client_id="client-id",
            directory_id="tenant-id",
            authority_host=AUTHORITY_HOST,
            auth_method="kerberos",
        )


def test_client_secret_context_reports_its_method() -> None:
    with patch(
        "onyx.connectors.microsoft_utils.graph_auth.msal.ConfidentialClientApplication"
    ):
        auth = build_msal_app(
            client_id="client-id",
            directory_id="tenant-id",
            authority_host=AUTHORITY_HOST,
            client_secret="secret",
        )

    assert auth.method is MicrosoftAuthMethod.CLIENT_SECRET
    assert auth.supports_sharepoint_rest is False


def test_certificate_context_reports_its_method() -> None:
    with (
        patch(
            "onyx.connectors.microsoft_utils.graph_auth.msal.ConfidentialClientApplication"
        ),
        patch(
            "onyx.connectors.microsoft_utils.graph_auth.load_certificate_from_pfx"
        ) as load_cert,
    ):
        load_cert.return_value = CertificateData(private_key=b"pem", thumbprint="ab")
        auth = build_msal_app(
            client_id="client-id",
            directory_id="tenant-id",
            authority_host=AUTHORITY_HOST,
            auth_method=MicrosoftAuthMethod.CERTIFICATE.value,
            private_key_b64=base64.b64encode(b"pfx").decode(),
            certificate_password="pw",
        )

    assert auth.method is MicrosoftAuthMethod.CERTIFICATE
    assert auth.supports_sharepoint_rest is True
