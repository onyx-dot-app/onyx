"""The shared MSAL builder must not validate the client and directory ids.

Teams passes its credential straight through and expects a plain MSAL failure.
Raising ``ConnectorValidationError`` here would cancel the index attempt and
mark the credential invalid, which is SharePoint's behaviour, not Teams'.
SharePoint keeps its own presence checks in ``load_credentials``.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.microsoft_utils.graph_auth import (
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
