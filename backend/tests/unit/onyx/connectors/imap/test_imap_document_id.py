from email.message import EmailMessage
from unittest.mock import MagicMock, patch

from onyx.configs.constants import DocumentSource
from onyx.connectors.credentials_provider import OnyxStaticCredentialsProvider
from onyx.connectors.imap.connector import (
    _IMAP_OKAY_STATUS,
    ImapCheckpoint,
    ImapConnector,
)
from onyx.connectors.models import Document

_JIRA_DOC_ID = "https://example.atlassian.net/browse/KEY-1"


def _load_document_ids(username: str) -> list[str]:
    message = EmailMessage()
    message["Message-ID"] = _JIRA_DOC_ID
    message["Subject"] = "KEY-1"
    message["From"] = "attacker@example.org"
    message["To"] = "inbox@example.com"
    message["Date"] = "Mon, 1 Jan 2024 00:00:00 +0000"
    message.set_content("injected text")

    connector = ImapConnector(host="imap.example.com", mailboxes=["INBOX"])
    connector.set_credentials_provider(
        OnyxStaticCredentialsProvider(
            tenant_id=None,
            connector_name=DocumentSource.IMAP,
            credential_json={"imap_username": username, "imap_password": "pw"},
        )
    )
    with patch("onyx.connectors.imap.connector.imaplib.IMAP4_SSL") as mock_imap:
        client: MagicMock = mock_imap.return_value
        client.login.return_value = (_IMAP_OKAY_STATUS, [b""])
        client.select.return_value = (_IMAP_OKAY_STATUS, [b"1"])
        client.search.return_value = (_IMAP_OKAY_STATUS, [b"1"])
        client.fetch.return_value = (
            _IMAP_OKAY_STATUS,
            [(b"1 (RFC822)", message.as_bytes())],
        )
        outputs = list(
            connector.load_from_checkpoint(
                start=0,
                end=1_800_000_000,
                checkpoint=ImapCheckpoint(has_more=True, todo_mailboxes=['"INBOX"']),
            )
        )
    return [output.id for output in outputs if isinstance(output, Document)]


def test_message_id_cannot_choose_the_document_id() -> None:
    [first_account_id] = _load_document_ids("first@example.com")
    [second_account_id] = _load_document_ids("second@example.com")

    assert first_account_id.startswith(f"{DocumentSource.IMAP.value}:")
    assert _JIRA_DOC_ID not in first_account_id
    assert first_account_id != second_account_id
    assert _load_document_ids("first@example.com") == [first_account_id]
