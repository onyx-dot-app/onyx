from unittest.mock import MagicMock
from email.message import EmailMessage

from onyx.connectors.imap.connector import (
    _IMAP_OKAY_STATUS,
    _fetch_email_ids_in_mailbox,
    _fetch_email,
)


def test_fetch_email_ids_uses_uid_search() -> None:
    mock_client = MagicMock()
    mock_client.select.return_value = (_IMAP_OKAY_STATUS, [b"10"])
    mock_client.uid.return_value = (_IMAP_OKAY_STATUS, [b"101 102 103"])

    email_ids = _fetch_email_ids_in_mailbox(
        mail_client=mock_client,
        mailbox="INBOX",
        start=1000000,
        end=2000000,
    )

    assert email_ids == ["101", "102", "103"]
    mock_client.uid.assert_called_once()
    assert mock_client.uid.call_args[0][0] == "search"


def test_fetch_email_uses_uid_fetch() -> None:
    mock_client = MagicMock()
    raw_email = b"From: a@b.com\r\nSubject: Hi\r\n\r\nBody\r\n"
    mock_client.uid.return_value = (_IMAP_OKAY_STATUS, [(b"1 (UID 101 RFC822 {30}", raw_email)])

    msg = _fetch_email(mail_client=mock_client, email_id="101")

    assert msg is not None
    assert msg["Subject"] == "Hi"
    mock_client.uid.assert_called_once_with("fetch", "101", "(RFC822)")


def test_fetch_email_expunged_message_returns_none() -> None:
    mock_client = MagicMock()
    # Python 3.13 returns [None] when a message was expunged before UID FETCH
    mock_client.uid.return_value = (_IMAP_OKAY_STATUS, [None])

    msg = _fetch_email(mail_client=mock_client, email_id="102")
    assert msg is None


def test_legacy_checkpoint_version_migration() -> None:
    from onyx.connectors.imap.connector import (
        CurrentMailbox,
        ImapCheckpoint,
        ImapConnector,
    )
    from onyx.configs.constants import DocumentSource
    from onyx.connectors.credentials_provider import OnyxStaticCredentialsProvider

    connector = ImapConnector(host="mail.example.com")
    connector.set_credentials_provider(
        OnyxStaticCredentialsProvider(
            tenant_id=None,
            connector_name=DocumentSource.IMAP,
            credential_json={"imap_username": "tester@example.com", "imap_password": "pw"},
        )
    )

    mock_client = MagicMock()
    connector._get_mail_client = MagicMock(return_value=mock_client)  # type: ignore

    # Legacy checkpoint without version key in json/dict
    legacy_json = '{"has_more": true, "todo_mailboxes": ["Sent"], "current_mailbox": {"mailbox": "INBOX", "todo_email_ids": ["1", "2"]}}'
    legacy_ckpt = connector.validate_checkpoint_json(legacy_json)
    assert legacy_ckpt.version == 1

    mock_client.select.return_value = (_IMAP_OKAY_STATUS, [b"10"])
    mock_client.uid.return_value = (_IMAP_OKAY_STATUS, [b"101 102"])

    # Load from checkpoint should reset current_mailbox, preserve INBOX in todo, and bump version to 2
    gen = connector._load_from_checkpoint(start=0, end=1000, checkpoint=legacy_ckpt, include_perm_sync=False)
    try:
        while True:
            next(gen)
    except StopIteration as e:
        res = e.value

    assert res.version == 2
    assert res.current_mailbox is not None
    assert res.current_mailbox.mailbox == "INBOX"

