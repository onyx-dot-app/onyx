import email
import uuid
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
        # It's possible for the subject line to not exist or be an empty string.
        subject = _decode(header=Header.SUBJECT_HEADER) or "Unknown Subject"
        # It's possible for the from header to not exist (e.g., malformed emails).
        from_ = _decode(header=Header.FROM_HEADER) or "Unknown Sender"
        to = _decode(header=Header.TO_HEADER)
        if not to:
            to = _decode(header=Header.DELIVERED_TO_HEADER)
        date_str = _decode(header=Header.DATE_HEADER)
        date = _parse_date(date_str=date_str)

        # Fallback for missing required fields to handle malformed/old emails
        if message_id is None:
            # Generate a unique ID based on subject and date, or fallback to UUID
            fallback_content = f"{subject or ''}-{date_str or ''}"
            message_id = f"<generated-{uuid.uuid5(uuid.NAMESPACE_DNS, fallback_content)}>"
        
        if date is None:
            # Use current time as fallback for missing/unparseable dates
            date = datetime.now()

        return cls.model_validate(
            {
                "id": message_id,
                "subject": subject,
                "sender": from_,
                "recipients": to,
                "date": date,
            }
        )
