from unittest.mock import MagicMock, patch

from onyx.configs.constants import DocumentSource
from onyx.connectors.credentials_provider import OnyxStaticCredentialsProvider
from onyx.connectors.imap.connector import _IMAP_OKAY_STATUS, ImapConnector
from onyx.connectors.models import Document
from tests.unit.onyx.connectors.utils import load_everything_from_checkpoint_connector

# RFC 2047 encoded words next to plain text, as mail clients send them for
# non-ASCII names and subjects.
_RAW_EMAIL = b"""Message-ID: <encoded-headers@example.com>
Subject: Re: =?utf-8?q?caf=C3=A9?= plans
From: =?utf-8?q?J=C3=B6rg_M=C3=BCller?= <jorg@example.com>
To: =?utf-8?q?Zo=C3=AB?= <zoe@example.com>, Ana <ana@example.com>
Date: Wed, 24 Sep 2026 10:00:00 +0000
Content-Type: text/plain; charset=utf-8

See you there.
"""


def _mail_client() -> MagicMock:
    client = MagicMock()
    client.login.return_value = (_IMAP_OKAY_STATUS, [b""])
    client.select.return_value = (_IMAP_OKAY_STATUS, [b"1"])
    client.search.return_value = (_IMAP_OKAY_STATUS, [b"1"])
    client.fetch.return_value = (_IMAP_OKAY_STATUS, [(b"1 (RFC822)", _RAW_EMAIL)])
    return client


@patch("onyx.connectors.imap.connector.imaplib.IMAP4_SSL")
def test_encoded_word_headers_are_fully_decoded(mock_imap4_ssl: MagicMock) -> None:
    mock_imap4_ssl.return_value = _mail_client()
    connector = ImapConnector(host="imap.example.com", mailboxes=["INBOX"])
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

    outputs = load_everything_from_checkpoint_connector(connector, 0, 1_800_000_000)
    docs = [item for output in outputs for item in output.items]
    assert len(docs) == 1
    doc = docs[0]
    assert isinstance(doc, Document)

    assert doc.title == "Re: café plans"
    owners = {owner.email: owner.display_name for owner in doc.primary_owners or []}
    assert owners == {
        "jorg@example.com": "Jörg Müller",
        "zoe@example.com": "Zoë",
        "ana@example.com": "Ana",
    }
