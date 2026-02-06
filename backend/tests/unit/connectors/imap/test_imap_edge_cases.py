"""
Unit tests for IMAP connector edge cases.

These tests verify handling of malformed or unusual email messages:
- Emails with unknown-8bit encoding
- Emails with commas in display names (e.g., "Doe, John" <john@example.com>)
- Emails missing the From: header
- Emails missing the Message-ID header
- Emails missing the Date header
"""

import email
from datetime import datetime
from email.message import Message

import pytest

from onyx.connectors.imap.connector import _parse_addrs, _parse_singular_addr
from onyx.connectors.imap.models import EmailHeaders


def _create_email_message(
    subject: str | None = None,
    from_: str | None = None,
    to: str | None = None,
    date: str | None = None,
    message_id: str | None = None,
    body: str = "Test body content",
    charset: str = "utf-8",
    content_type: str = "text/plain",
) -> Message:
    """Helper function to create email messages for testing."""
    msg = email.message.EmailMessage()
    
    if subject is not None:
        msg["Subject"] = subject
    if from_ is not None:
        msg["From"] = from_
    if to is not None:
        msg["To"] = to
    if date is not None:
        msg["Date"] = date
    if message_id is not None:
        msg["Message-ID"] = message_id
    
    msg.set_content(body)
    
    return msg


def _create_raw_email_with_encoding(
    encoding: str,
    body_bytes: bytes,
    subject: str = "Test",
    from_: str = "test@example.com",
    to: str = "recipient@example.com",
    date: str = "Mon, 1 Jan 2024 12:00:00 +0000",
    message_id: str = "<test@example.com>",
) -> Message:
    """Create an email message with a specific Content-Type charset."""
    raw_email = f"""From: {from_}
To: {to}
Subject: {subject}
Date: {date}
Message-ID: {message_id}
Content-Type: text/plain; charset="{encoding}"
Content-Transfer-Encoding: 8bit

""".encode("utf-8") + body_bytes
    
    return email.message_from_bytes(raw_email)


class TestUnknown8BitEncoding:
    """Test handling of emails with unknown-8bit encoding."""
    
    def test_unknown_8bit_encoding_in_body(self) -> None:
        """Email body with unknown-8bit charset should be decoded gracefully."""
        # Create a message with unknown-8bit encoding
        body_bytes = b"Hello, this is a test with special chars: \xe9\xe8\xe0"
        msg = _create_raw_email_with_encoding(
            encoding="unknown-8bit",
            body_bytes=body_bytes,
        )
        
        headers = EmailHeaders.from_email_msg(email_msg=msg)
        
        assert headers.subject == "Test"
        assert headers.sender == "test@example.com"
        assert headers.id == "<test@example.com>"
    
    def test_unknown_8bit_encoding_in_header(self) -> None:
        """Headers with unknown-8bit encoding should be decoded gracefully."""
        # Create raw email with encoded header
        raw_email = b"""From: test@example.com
To: recipient@example.com
Subject: =?unknown-8bit?Q?Test_Subject?=
Date: Mon, 1 Jan 2024 12:00:00 +0000
Message-ID: <test@example.com>
Content-Type: text/plain; charset="utf-8"

Test body
"""
        msg = email.message_from_bytes(raw_email)
        
        headers = EmailHeaders.from_email_msg(email_msg=msg)
        
        # Should handle gracefully - exact output depends on fallback
        assert headers.sender == "test@example.com"
        assert headers.id == "<test@example.com>"


class TestCommaInDisplayName:
    """Test handling of emails with commas in display names."""
    
    def test_comma_in_from_display_name(self) -> None:
        """Display name with comma should be parsed correctly."""
        msg = _create_email_message(
            from_='"Doe, John" <john@example.com>',
            to="recipient@example.com",
            subject="Test",
            date="Mon, 1 Jan 2024 12:00:00 +0000",
            message_id="<test@example.com>",
        )
        
        headers = EmailHeaders.from_email_msg(email_msg=msg)
        
        assert headers.sender == '"Doe, John" <john@example.com>'
        assert headers.id == "<test@example.com>"
    
    def test_comma_in_to_display_name(self) -> None:
        """To header with comma in display name should be parsed correctly."""
        msg = _create_email_message(
            from_="sender@example.com",
            to='"Smith, Jane" <jane@example.com>',
            subject="Test",
            date="Mon, 1 Jan 2024 12:00:00 +0000",
            message_id="<test@example.com>",
        )
        
        headers = EmailHeaders.from_email_msg(email_msg=msg)
        
        assert headers.recipients == '"Smith, Jane" <jane@example.com>'
    
    def test_parse_addrs_with_comma_in_name(self) -> None:
        """_parse_addrs should correctly parse names with commas."""
        raw_header = '"Doe, John" <john@example.com>'
        
        result = _parse_addrs(raw_header=raw_header)
        
        assert len(result) == 1
        name, addr = result[0]
        assert addr == "john@example.com"
        assert "Doe" in name and "John" in name
    
    def test_parse_addrs_multiple_with_comma_in_name(self) -> None:
        """_parse_addrs should handle multiple addresses with commas in names."""
        raw_header = '"Doe, John" <john@example.com>, "Smith, Jane" <jane@example.com>'
        
        result = _parse_addrs(raw_header=raw_header)
        
        assert len(result) == 2
        emails = [addr for _, addr in result]
        assert "john@example.com" in emails
        assert "jane@example.com" in emails
    
    def test_parse_singular_addr_with_comma(self) -> None:
        """_parse_singular_addr should handle comma in display name."""
        raw_header = '"Doe, John" <john@example.com>'
        
        name, addr = _parse_singular_addr(raw_header=raw_header)
        
        assert addr == "john@example.com"
        assert "Doe" in name or "John" in name


class TestMissingFromHeader:
    """Test handling of emails without From: header."""
    
    def test_missing_from_header(self) -> None:
        """Email without From header should use 'Unknown Sender'."""
        msg = _create_email_message(
            from_=None,  # No From header
            to="recipient@example.com",
            subject="Test Subject",
            date="Mon, 1 Jan 2024 12:00:00 +0000",
            message_id="<test@example.com>",
        )
        
        headers = EmailHeaders.from_email_msg(email_msg=msg)
        
        assert headers.sender == "Unknown Sender"
        assert headers.subject == "Test Subject"
        assert headers.id == "<test@example.com>"
    
    def test_empty_from_header(self) -> None:
        """Email with empty From header should use 'Unknown Sender'."""
        raw_email = b"""From: 
To: recipient@example.com
Subject: Test Subject
Date: Mon, 1 Jan 2024 12:00:00 +0000
Message-ID: <test@example.com>
Content-Type: text/plain

Test body
"""
        msg = email.message_from_bytes(raw_email)
        
        headers = EmailHeaders.from_email_msg(email_msg=msg)
        
        assert headers.sender == "Unknown Sender"


class TestMissingMessageID:
    """Test handling of emails without Message-ID header."""
    
    def test_missing_message_id_generates_uuid(self) -> None:
        """Email without Message-ID should get a generated ID."""
        msg = _create_email_message(
            from_="sender@example.com",
            to="recipient@example.com",
            subject="Test Subject",
            date="Mon, 1 Jan 2024 12:00:00 +0000",
            message_id=None,  # No Message-ID
        )
        
        headers = EmailHeaders.from_email_msg(email_msg=msg)
        
        assert headers.id.startswith("<generated-")
        assert headers.id.endswith(">")
    
    def test_missing_message_id_is_deterministic(self) -> None:
        """Same email content should generate the same ID (uuid5)."""
        msg1 = _create_email_message(
            from_="sender@example.com",
            to="recipient@example.com",
            subject="Test Subject",
            date="Mon, 1 Jan 2024 12:00:00 +0000",
            message_id=None,
            body="Same body content",
        )
        msg2 = _create_email_message(
            from_="sender@example.com",
            to="recipient@example.com",
            subject="Test Subject",
            date="Mon, 1 Jan 2024 12:00:00 +0000",
            message_id=None,
            body="Same body content",
        )
        
        headers1 = EmailHeaders.from_email_msg(email_msg=msg1)
        headers2 = EmailHeaders.from_email_msg(email_msg=msg2)
        
        assert headers1.id == headers2.id
    
    def test_different_content_generates_different_ids(self) -> None:
        """Different email content should generate different IDs."""
        msg1 = _create_email_message(
            from_="sender@example.com",
            to="recipient@example.com",
            subject="Subject 1",
            date="Mon, 1 Jan 2024 12:00:00 +0000",
            message_id=None,
            body="Body content 1",
        )
        msg2 = _create_email_message(
            from_="sender@example.com",
            to="recipient@example.com",
            subject="Subject 2",
            date="Mon, 1 Jan 2024 12:00:00 +0000",
            message_id=None,
            body="Body content 2",
        )
        
        headers1 = EmailHeaders.from_email_msg(email_msg=msg1)
        headers2 = EmailHeaders.from_email_msg(email_msg=msg2)
        
        assert headers1.id != headers2.id
    
    def test_all_fields_empty_uses_random_uuid(self) -> None:
        """Email with no usable fields should get a random UUID4."""
        # Create a minimal message with no headers
        msg = Message()
        msg.set_payload("", charset="utf-8")
        
        headers1 = EmailHeaders.from_email_msg(email_msg=msg)
        headers2 = EmailHeaders.from_email_msg(email_msg=msg)
        
        # Both should be generated but different (uuid4)
        assert headers1.id.startswith("<generated-")
        assert headers2.id.startswith("<generated-")
        # uuid4 should be different each time
        assert headers1.id != headers2.id


class TestMissingDateHeader:
    """Test handling of emails without Date header."""
    
    def test_missing_date_header(self) -> None:
        """Email without Date header should use current time."""
        msg = _create_email_message(
            from_="sender@example.com",
            to="recipient@example.com",
            subject="Test Subject",
            date=None,  # No Date header
            message_id="<test@example.com>",
        )
        
        before = datetime.now()
        headers = EmailHeaders.from_email_msg(email_msg=msg)
        after = datetime.now()
        
        # Date should be set to approximately now
        assert before.replace(tzinfo=None) <= headers.date.replace(tzinfo=None) <= after.replace(tzinfo=None)
    
    def test_invalid_date_format(self) -> None:
        """Email with unparseable Date should use current time."""
        raw_email = b"""From: sender@example.com
To: recipient@example.com
Subject: Test Subject
Date: not-a-valid-date
Message-ID: <test@example.com>
Content-Type: text/plain

Test body
"""
        msg = email.message_from_bytes(raw_email)
        
        before = datetime.now()
        headers = EmailHeaders.from_email_msg(email_msg=msg)
        after = datetime.now()
        
        # Should fall back to current time
        assert before.replace(tzinfo=None) <= headers.date.replace(tzinfo=None) <= after.replace(tzinfo=None)
    
    def test_valid_date_is_preserved(self) -> None:
        """Email with valid Date should preserve it."""
        msg = _create_email_message(
            from_="sender@example.com",
            to="recipient@example.com",
            subject="Test Subject",
            date="Mon, 1 Jan 2024 12:00:00 +0000",
            message_id="<test@example.com>",
        )
        
        headers = EmailHeaders.from_email_msg(email_msg=msg)
        
        assert headers.date.year == 2024
        assert headers.date.month == 1
        assert headers.date.day == 1


class TestCombinedEdgeCases:
    """Test combinations of edge cases."""
    
    def test_missing_all_optional_headers(self) -> None:
        """Email with only a body should still be processed."""
        msg = Message()
        msg.set_payload("Just a body, no headers")
        
        headers = EmailHeaders.from_email_msg(email_msg=msg)
        
        assert headers.sender == "Unknown Sender"
        assert headers.subject == "Unknown Subject"
        assert headers.id.startswith("<generated-")
        # Date should be set to now
        assert headers.date is not None
    
    def test_comma_in_name_with_missing_message_id(self) -> None:
        """Email with comma in name and no Message-ID should work."""
        msg = _create_email_message(
            from_='"Doe, John" <john@example.com>',
            to='"Smith, Jane" <jane@example.com>',
            subject="Meeting Notes",
            date="Mon, 1 Jan 2024 12:00:00 +0000",
            message_id=None,
        )
        
        headers = EmailHeaders.from_email_msg(email_msg=msg)
        
        assert headers.sender == '"Doe, John" <john@example.com>'
        assert headers.recipients == '"Smith, Jane" <jane@example.com>'
        assert headers.id.startswith("<generated-")
