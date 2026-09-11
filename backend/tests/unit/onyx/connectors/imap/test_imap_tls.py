import ssl
from unittest.mock import MagicMock, patch

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.credentials_provider import OnyxStaticCredentialsProvider
from onyx.connectors.imap.connector import _IMAP_OKAY_STATUS, ImapConnector


def _build_connector() -> ImapConnector:
    connector = ImapConnector(host="imap.example.com")
    connector.set_credentials_provider(
        OnyxStaticCredentialsProvider(
            tenant_id=None,
            connector_name=DocumentSource.IMAP,
            credential_json={
                "imap_username": "admin@example.com",
                "imap_password": "hunter2",
            },
        )
    )
    return connector


@patch("onyx.connectors.imap.connector.imaplib.IMAP4_SSL")
def test_mail_client_verifies_certificate_and_hostname(
    mock_imap4_ssl: MagicMock,
) -> None:
    mock_imap4_ssl.return_value.login.return_value = (_IMAP_OKAY_STATUS, [b""])

    _build_connector()._get_mail_client()

    ssl_context = mock_imap4_ssl.call_args.kwargs["ssl_context"]
    assert ssl_context.verify_mode is ssl.CERT_REQUIRED
    assert ssl_context.check_hostname is True


@patch(
    "onyx.connectors.imap.connector.imaplib.IMAP4_SSL",
    side_effect=ssl.SSLCertVerificationError("certificate verify failed"),
)
def test_mail_client_does_not_send_credentials_on_handshake_failure(
    mock_imap4_ssl: MagicMock,
) -> None:
    with pytest.raises(ssl.SSLCertVerificationError):
        _build_connector()._get_mail_client()

    mock_imap4_ssl.return_value.login.assert_not_called()
