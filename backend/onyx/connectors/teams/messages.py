"""What a channel thread and a meeting chat both do with a Teams message: who
said it, what it says, when it changed."""

from collections.abc import Sequence
from datetime import datetime

from onyx.connectors.models import BasicExpertInfo
from onyx.connectors.teams.models import Message
from onyx.file_processing.html_utils import parse_html_page_basic


def sender_name(message: Message) -> str:
    """Bots and apps post without a user, so the sender is not always known."""
    if message.from_ and message.from_.user and message.from_.user.display_name:
        return message.from_.user.display_name
    return "Unknown User"


def message_header(message: Message) -> str:
    return (
        f"From: {sender_name(message)}\nDate: {message.created_date_time.isoformat()}"
    )


def message_text(message: Message) -> str | None:
    """Who said it and when, then what they said. None for an empty body."""
    body = parse_html_page_basic(message.body.content) if message.body.content else ""
    body = body.strip()
    return f"{message_header(message)}\n\n{body}" if body else None


def modified_at(message: Message) -> datetime:
    return message.last_modified_date_time or message.created_date_time


def message_authors(messages: Sequence[Message]) -> list[BasicExpertInfo]:
    """The people who wrote these messages, each once by user id: two people can
    share a name, and one can change theirs. Graph names a sender and gives no
    email, and a bot or an app posts with no sender at all."""
    names = {
        message.from_.user.id: message.from_.user.display_name
        for message in messages
        if message.is_indexable
        and message.from_
        and message.from_.user
        and message.from_.user.display_name
    }
    return [BasicExpertInfo(display_name=name) for name in names.values()]
