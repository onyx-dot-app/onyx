import email.header
import email.utils
import hashlib
from datetime import datetime, timezone
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

            parts: list[str] = []
            for decoded_value, encoding in email.header.decode_header(value):
                if isinstance(decoded_value, bytes):
                    encoding = encoding or "utf-8"
                    try:
                        parts.append(
                            decoded_value.decode(encoding, errors="replace")
                        )
                    except LookupError:
                        # Bogus charset labels such as "unknown-8bit" are not
                        # registered Python codecs and raise LookupError, which
                        # errors="replace" does not cover.
                        parts.append(
                            decoded_value.decode("utf-8", errors="replace")
                        )
                elif isinstance(decoded_value, str):
                    parts.append(decoded_value)
            return "".join(parts) or None

        def _parse_date(date_str: str | None) -> datetime:
            try:
                parsed = (
                    email.utils.parsedate_to_datetime(date_str)
                    if date_str
                    else None
                )
            except (TypeError, ValueError):
                parsed = None
            # Mails without a parseable Date still need a value; the epoch
            # keeps them sortable rather than dropping them.
            return parsed or datetime.fromtimestamp(0, tz=timezone.utc)

        message_id = _decode(header=Header.MESSAGE_ID_HEADER)
        # It's possible for the subject line to not exist or be an empty string.
        subject = _decode(header=Header.SUBJECT_HEADER) or "Unknown Subject"
        from_ = _decode(header=Header.FROM_HEADER)
        to = _decode(header=Header.TO_HEADER)
        if not to:
            to = _decode(header=Header.DELIVERED_TO_HEADER)
        date = _parse_date(date_str=_decode(header=Header.DATE_HEADER))

        if not message_id:
            # Mails without Message-ID must still get a stable document id;
            # derive one from the raw message so re-fetches dedupe correctly.
            message_id = "generated-" + hashlib.sha256(
                email_msg.as_bytes()
            ).hexdigest()

        return cls.model_validate(
            {
                "id": message_id,
                "subject": subject,
                "sender": from_ or "",
                "recipients": to,
                "date": date,
            }
        )
