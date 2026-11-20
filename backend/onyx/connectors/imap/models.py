import email.errors
import email.header
import email.utils
import hashlib
from datetime import datetime
from email.message import Message
from enum import Enum

from pydantic import BaseModel


class Header(str, Enum):
    SUBJECT_HEADER = "subject"
    FROM_HEADER = "from"
    TO_HEADER = "to"
    DELIVERED_TO_HEADER = (
        "Delivered-To"  # Used in mailing lists instead of the "to" header.
    )
    DATE_HEADER = "date"
    MESSAGE_ID_HEADER = "Message-ID"


def _decode_header(email_msg: Message, header: str) -> str | None:
    value = email_msg.get(header)
    if not value:
        return None

    try:
        decoded_value, encoding = email.header.decode_header(value)[0]
        if isinstance(decoded_value, bytes):
            return decoded_value.decode(encoding or "utf-8", errors="replace")
    except (LookupError, ValueError, email.errors.HeaderParseError):
        # Unknown charset or broken encoded-word: keep the raw header text.
        return str(value)
    if isinstance(decoded_value, str):
        return decoded_value
    return None


def message_document_id(email_msg: Message) -> str:
    """Document id for a message: its `Message-ID`, or a hash of the message.

    RFC 5322 makes `Message-ID` a SHOULD, not a MUST. Sequence numbers shift
    when mail is deleted, so the fallback hashes the message content to stay the
    same on every run.
    """
    message_id = _decode_header(email_msg, Header.MESSAGE_ID_HEADER)
    if message_id and message_id.strip():
        return message_id

    digest = hashlib.sha256()
    try:
        digest.update(email_msg.as_bytes())
    except Exception:
        digest.update(repr(sorted(email_msg.items())).encode("utf-8", "replace"))
    return f"imap-no-message-id-{digest.hexdigest()}"


class EmailHeaders(BaseModel):
    """
    Model for email headers extracted from IMAP messages.
    """

    id: str
    subject: str
    sender: str | None
    recipients: str | None
    date: datetime | None

    @classmethod
    def from_email_msg(cls, email_msg: Message) -> "EmailHeaders":
        def _parse_date(date_str: str | None) -> datetime | None:
            if not date_str:
                return None
            try:
                return email.utils.parsedate_to_datetime(date_str)
            except (TypeError, ValueError):
                return None

        # It's possible for the subject line to not exist or be an empty string.
        subject = _decode_header(email_msg, Header.SUBJECT_HEADER) or "Unknown Subject"
        to = _decode_header(email_msg, Header.TO_HEADER) or _decode_header(
            email_msg, Header.DELIVERED_TO_HEADER
        )

        return cls(
            id=message_document_id(email_msg),
            subject=subject,
            sender=_decode_header(email_msg, Header.FROM_HEADER),
            recipients=to,
            date=_parse_date(_decode_header(email_msg, Header.DATE_HEADER)),
        )
