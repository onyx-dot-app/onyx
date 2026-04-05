import email
import hashlib
import uuid
from datetime import datetime
from datetime import timezone
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


def _extract_body_hash(email_msg: Message, max_chars: int = 1000) -> str:
    """
    Extract a hash of the email body (first max_chars characters) for use in
    generating unique IDs when Message-ID is missing.
    """
    try:
        for part in email_msg.walk():
            if part.is_multipart():
                continue
            raw_payload = part.get_payload(decode=True)
            if isinstance(raw_payload, bytes):
                # Try to decode, but use raw bytes if decoding fails
                try:
                    charset = part.get_content_charset() or "utf-8"
                    text = raw_payload.decode(charset, errors="replace")
                except (LookupError, UnicodeDecodeError):
                    text = raw_payload.decode("latin-1", errors="replace")
                # Hash the first max_chars characters
                return hashlib.sha256(text[:max_chars].encode("utf-8")).hexdigest()[:16]
        return ""
    except Exception:
        return ""


class EmailHeaders(BaseModel):
    """
    Model for email headers extracted from IMAP messages.
    """

    id: str
    subject: str
    sender: str
    recipients: str | None
    date: datetime

    @classmethod
    def from_email_msg(cls, email_msg: Message) -> "EmailHeaders":
        def _decode(header: str, default: str | None = None) -> str | None:
            value = email_msg.get(header, default)
            if not value:
                return None

            decoded_value, encoding = email.header.decode_header(value)[0]
            if isinstance(decoded_value, bytes):
                encoding = encoding or "utf-8"
                try:
                    return decoded_value.decode(encoding, errors="replace")
                except LookupError:
                    # Fallback for unknown encodings like "unknown-8bit"
                    return decoded_value.decode("latin-1", errors="replace")
            elif isinstance(decoded_value, str):
                return decoded_value
            else:
                return None

        def _parse_date(date_str: str | None) -> datetime | None:
            if not date_str:
                return None
            try:
                return email.utils.parsedate_to_datetime(date_str)
            except (TypeError, ValueError):
                return None

        message_id = _decode(header=Header.MESSAGE_ID_HEADER)
        # Store original values BEFORE applying fallback defaults
        # (needed to correctly detect truly empty emails for uuid4 fallback)
        raw_subject = _decode(header=Header.SUBJECT_HEADER)
        raw_from = _decode(header=Header.FROM_HEADER)
        # Apply fallbacks for display/storage
        subject = raw_subject or "Unknown Subject"
        from_ = raw_from or "Unknown Sender"
        to = _decode(header=Header.TO_HEADER)
        if not to:
            to = _decode(header=Header.DELIVERED_TO_HEADER)
        date_str = _decode(header=Header.DATE_HEADER)
        date = _parse_date(date_str=date_str)

        # Fallback for missing required fields to handle malformed/old emails
        if message_id is None:
            # Generate a unique ID using multiple fields to reduce collision risk
            # Include: subject, date, from, to, and a hash of the body content
            body_hash = _extract_body_hash(email_msg)
            
            # Use ORIGINAL values (before fallback defaults) to detect truly empty emails
            fallback_parts = [
                raw_subject or "",
                date_str or "",
                raw_from or "",
                to or "",
                body_hash,
            ]
            fallback_content = "-".join(fallback_parts)
            
            # Check if we have any meaningful content from ORIGINAL fields
            if all(not part for part in fallback_parts):
                # All fields empty - use random UUID to avoid collisions
                message_id = f"<generated-{uuid.uuid4()}>"
            else:
                message_id = f"<generated-{uuid.uuid5(uuid.NAMESPACE_DNS, fallback_content)}>"
        
        if date is None:
            # Use current time as fallback for missing/unparseable dates
            date = datetime.now(timezone.utc)

        return cls.model_validate(
            {
                "id": message_id,
                "subject": subject,
                "sender": from_,
                "recipients": to,
                "date": date,
            }
        )
