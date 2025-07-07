import email
from datetime import datetime
from email.message import Message

from pydantic import BaseModel


_SUBJECT_HEADER = "subject"
_FROM_HEADER = "from"
_TO_HEADER = "to"
_DELIVERED_TO_HEADER = (
    "Delivered-To"  # Used in mailing lists instead of the "to" header.
)
_DATE_HEADER = "date"
_ENCODING_HEADER = "Content-Transfer-Encoding"
_CONTENT_TYPE_HEADER = "Content-Type"
_MESSAGE_ID_HEADER = "Message-ID"
_DEFAULT_ENCODING = "utf-8"


class EmailHeaders(BaseModel):
    """
    Model for email headers extracted from IMAP messages.
    """

    id: str
    subject: str
    sender: str
    recipients: str
    date: datetime

    @classmethod
    def from_email_msg(cls, email_msg: Message) -> "EmailHeaders":
        def _decode(header: str, default: str | None = None) -> str | None:
            value = email_msg.get(header, default)
            if not value:
                return None

            decoded_value, _encoding = email.header.decode_header(value)[0]

            if isinstance(decoded_value, bytes):
                return decoded_value.decode()
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

        # It's possible for the subject line to not exist or be an empty string.
        message_id = _decode(header=_MESSAGE_ID_HEADER)
        subject = _decode(header=_SUBJECT_HEADER) or "Unknown Subject"
        from_ = _decode(header=_FROM_HEADER)
        to = _decode(header=_TO_HEADER)
        if not to:
            to = _decode(header=_DELIVERED_TO_HEADER)
        date_str = _decode(header=_DATE_HEADER)
        date = _parse_date(date_str)
        content_type = _decode(header=_CONTENT_TYPE_HEADER)
        _encoding = _decode(header=_ENCODING_HEADER, default=_DEFAULT_ENCODING)

        return cls.model_validate(
            {
                "id": message_id,
                "subject": subject,
                "sender": from_,
                "recipients": to,
                "date": date,
                "content_type": content_type,
            }
        )
