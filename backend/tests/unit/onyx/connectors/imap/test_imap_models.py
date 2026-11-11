from email.message import EmailMessage
from datetime import datetime, timezone
from onyx.connectors.imap.models import EmailHeaders


def test_email_headers_with_valid_message_id() -> None:
    msg = EmailMessage()
    msg["Message-ID"] = "<unique-12345@domain.com>"
    msg["Subject"] = "Test Subject"
    msg["From"] = "sender@example.com"
    msg["To"] = "recipient@example.com"
    msg["Date"] = "Wed, 11 Nov 2026 12:00:00 +0000"
    msg.set_content("Hello World")

    headers = EmailHeaders.from_email_msg(msg)
    assert headers.id == "<unique-12345@domain.com>"
    assert headers.subject == "Test Subject"
    assert headers.sender == "sender@example.com"
    assert headers.recipients == "recipient@example.com"
    assert headers.date == datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)


def test_email_headers_missing_message_id_with_fallback() -> None:
    msg = EmailMessage()
    msg["Subject"] = "No Message ID Subject"
    msg["From"] = "sender@example.com"
    msg["To"] = "recipient@example.com"
    msg["Date"] = "Wed, 11 Nov 2026 12:00:00 +0000"
    msg.set_content("Message without message ID")

    headers = EmailHeaders.from_email_msg(msg, fallback_id="INBOX:42")
    assert headers.id == "INBOX:42"
    assert headers.subject == "No Message ID Subject"
    assert headers.sender == "sender@example.com"


def test_email_headers_missing_message_id_without_fallback() -> None:
    msg = EmailMessage()
    msg["Subject"] = "Fallback Hash Subject"
    msg["From"] = "sender@example.com"
    msg["To"] = "recipient@example.com"
    msg["Date"] = "Wed, 11 Nov 2026 12:00:00 +0000"
    msg.set_content("Message without message ID or fallback")

    headers = EmailHeaders.from_email_msg(msg)
    assert headers.id.startswith("fallback-msg-")
    assert len(headers.id) > 15
    assert headers.subject == "Fallback Hash Subject"


def test_email_headers_empty_message_id() -> None:
    msg = EmailMessage()
    msg["Message-ID"] = "   "
    msg["Subject"] = "Whitespace Message ID"
    msg["From"] = "sender@example.com"
    msg["To"] = "recipient@example.com"
    msg["Date"] = "Wed, 11 Nov 2026 12:00:00 +0000"
    msg.set_content("Message with whitespace message ID")

    headers = EmailHeaders.from_email_msg(msg, fallback_id="INBOX:99")
    assert headers.id == "INBOX:99"
