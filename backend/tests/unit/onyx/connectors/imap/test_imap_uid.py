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
