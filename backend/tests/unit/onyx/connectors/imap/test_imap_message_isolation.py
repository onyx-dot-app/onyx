import email
from email.message import Message
from unittest.mock import MagicMock, patch

import pytest

from onyx.connectors.imap import connector as imap_connector
from onyx.connectors.imap.connector import (
    CurrentMailbox,
    ImapCheckpoint,
    ImapConnector,
)
from onyx.connectors.imap.models import EmailHeaders, message_document_id
from onyx.connectors.models import ConnectorFailure, Document


def _msg(message_id: str, from_: str = "Alice <alice@example.com>") -> Message:
    return email.message_from_string(
        f"From: {from_}\nTo: bob@example.com\nSubject: s\n"
        f"Message-ID: {message_id}\nDate: Fri, 9 Oct 2026 10:00:00 +0000\n\nhi\n"
    )


def test_missing_from_and_date_headers_do_not_raise() -> None:
    msg = email.message_from_string("Subject: no sender\n\nbody\n")

    headers = EmailHeaders.from_email_msg(email_msg=msg)

    assert headers.sender is None
    assert headers.date is None
    assert headers.id == message_document_id(msg)


def test_one_bad_message_yields_failure_and_run_continues(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    messages = {"1": _msg("<bad@example.com>"), "2": _msg("<good@example.com>")}
    real_convert = imap_connector._convert_email_headers_and_body_into_document

    def convert(
        email_msg: Message, email_headers: EmailHeaders, include_perm_sync: bool
    ) -> Document:
        if email_headers.id == "<bad@example.com>":
            raise ValueError("boom")
        return real_convert(
            email_msg=email_msg,
            email_headers=email_headers,
            include_perm_sync=include_perm_sync,
        )

    monkeypatch.setattr(
        imap_connector, "_convert_email_headers_and_body_into_document", convert
    )
    connector = ImapConnector(host="imap.example.com")
    checkpoint = ImapCheckpoint(
        has_more=True,
        todo_mailboxes=[],
        current_mailbox=CurrentMailbox(mailbox='"INBOX"', todo_email_ids=["1", "2"]),
    )

    with (
        patch.object(ImapConnector, "_get_mail_client", return_value=MagicMock()),
        patch.object(imap_connector, "_select_mailbox"),
        patch.object(
            imap_connector,
            "_fetch_email",
            side_effect=lambda **kwargs: messages[kwargs["email_id"]],
        ),
    ):
        outputs = list(
            connector.load_from_checkpoint(start=0, end=1, checkpoint=checkpoint)
        )

    assert len(outputs) == 2
    failure, document = outputs
    assert isinstance(failure, ConnectorFailure)
    assert failure.failed_document is not None
    assert failure.failed_document.document_id == "<bad@example.com>"
    assert isinstance(document, Document)
    assert document.id == "<good@example.com>"


def test_undecodable_message_id_does_not_raise() -> None:
    msg = email.message_from_string(
        "From: a@example.com\nMessage-ID: =?x-bogus-charset?q?abc?=\n\nbody\n"
    )

    headers = EmailHeaders.from_email_msg(email_msg=msg)

    assert headers.id == "=?x-bogus-charset?q?abc?="
    assert message_document_id(msg) == headers.id


def test_expunged_message_fetch_returns_none() -> None:
    mail_client = MagicMock()
    mail_client.fetch.return_value = ("OK", [None])

    assert imap_connector._fetch_email(mail_client=mail_client, email_id="1") is None
