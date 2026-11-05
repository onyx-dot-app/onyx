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


class EmailHeaders(BaseModel):
    """
    Model for email headers extracted from IMAP messages.
    """

    id: str
    subject: str
    sender: str
    recipients: str | None
    date: datetime

    @staticmethod
    def _synthesize_id(email_msg: Message) -> str:
        """Build an id for a message that has no `Message-ID` header.

        RFC 5322 makes that header a SHOULD rather than a MUST, so a mailbox can
        hold valid messages without one. The value is used as the `Document` id,
        so it has to be the same on every run. A sequence number is not stable
        (it shifts when earlier mail is deleted) and this connector does not
        fetch UIDs, so hash the message itself instead.
        """
        digest = hashlib.sha256()
        try:
            digest.update(email_msg.as_bytes())
        except Exception:
            # as_bytes() can fail on a malformed message. The headers are still
            # enough to tell it apart from the other messages in the mailbox.
            digest.update(repr(sorted(email_msg.items())).encode("utf-8", "replace"))
        return f"imap-no-message-id-{digest.hexdigest()}"

    @classmethod
    def from_email_msg(cls, email_msg: Message) -> "EmailHeaders":
        def _decode(header: str, default: str | None = None) -> str | None:
            value = email_msg.get(header, default)
            if not value:
                return None

            decoded_value, encoding = email.header.decode_header(value)[0]
            if isinstance(decoded_value, bytes):
                encoding = encoding or "utf-8"
                return decoded_value.decode(encoding, errors="replace")
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
                "id": message_id or cls._synthesize_id(email_msg=email_msg),
                "subject": subject,
                "sender": from_,
                "recipients": to,
                "date": date,
            }
        )
