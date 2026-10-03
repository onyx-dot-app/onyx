import email.header
import email.utils
from datetime import datetime
from email.message import Message
from enum import Enum

from pydantic import BaseModel

from onyx.utils.datetime import datetime_to_utc


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
    # `None` when the email has no (or an unparseable) `Date` header.
    date: datetime | None

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
                    # Some senders emit non-standard charset labels (e.g. the
                    # RFC 1428 placeholder `unknown-8bit`) that Python's codec
                    # registry doesn't recognize. Fall back to latin-1, which
                    # maps every byte 0-255 to a code point and never raises.
                    return decoded_value.decode("latin-1", errors="replace")
            elif isinstance(decoded_value, str):
                return decoded_value
            else:
                return None

        def _parse_date(date_str: str | None) -> datetime | None:
            if not date_str:
                return None
            try:
                parsed = email.utils.parsedate_to_datetime(date_str)
            except (TypeError, ValueError):
                return None
            # `Document.doc_updated_at` must be tz-aware UTC; `parsedate_to_datetime`
            # returns the sender's own offset (or a naive datetime for `-0000`),
            # so normalize with the repo's canonical UTC helper.
            return datetime_to_utc(parsed)

        message_id = _decode(header=Header.MESSAGE_ID_HEADER)
        # It's possible for the subject line to not exist or be an empty string.
        subject = _decode(header=Header.SUBJECT_HEADER) or "Unknown Subject"
        from_ = _decode(header=Header.FROM_HEADER)
        to = _decode(header=Header.TO_HEADER)
        if not to:
            to = _decode(header=Header.DELIVERED_TO_HEADER)
        date_str = _decode(header=Header.DATE_HEADER)
        date = _parse_date(date_str=date_str)

        # If any of the above are `None`, model validation will fail.
        # Therefore, no guards (i.e.: `if <header> is None: raise RuntimeError(..)`) were written.
        return cls.model_validate(
            {
                "id": message_id,
                "subject": subject,
                "sender": from_,
                "recipients": to,
                "date": date,
            }
        )
