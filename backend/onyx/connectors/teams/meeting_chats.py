"""Meeting chats: what people write in the chat of a scheduled meeting. Graph
lists a user's chats, and a meeting's chat names its organizer, so a chat is
walked through its organizer and only there: every member lists the same chat.
A day of a chat is one document, readable by the members who can see that day."""

import time
from collections.abc import Callable, Generator, Iterator
from datetime import date, datetime, timedelta, timezone
from typing import Any

import requests
from office365.graph_client import GraphClient
from pydantic import BaseModel

from onyx.access.models import ExternalAccess
from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import (
    InsufficientPermissionsError,
    UnexpectedValidationError,
)
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.models import (
    ConnectorFailure,
    Document,
    EntityFailure,
    ImageSection,
    SlimDocument,
    TextSection,
)
from onyx.connectors.teams import images
from onyx.connectors.teams.images import IMAGES_NOT_INDEXED, harvest_message_images
from onyx.connectors.teams.messages import message_authors, message_text, modified_at
from onyx.connectors.teams.models import ChannelMember, Message
from onyx.connectors.teams.organizers import Organizer, OrganizerSource
from onyx.connectors.teams.refusals import (
    graph_error_message,
    graph_said,
    is_permanent,
    status,
)
from onyx.connectors.teams.session import TeamsSession
from onyx.connectors.teams.sources import PagedListing, SlimWalk
from onyx.connectors.teams.transcripts import TRANSCRIPT_LOOKBACK_S
from onyx.connectors.teams.utils import (
    GraphRetriesExhausted,
    UserDirectory,
    _sanitize_message_user_display_name,
    iter_values,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()

MEETING_CHAT_DOCUMENT_ID_PREFIX = "teams-chat:"

# The largest page Graph serves for chats and for their messages.
CHAT_PAGE_SIZE = 50
# A listing ends only when Graph says so. More chats than this for one
# organizer is a listing gone wrong, and a walk cut there would read as whole
# to pruning, so the attempt fails instead.
MAX_CHATS_PER_ORGANIZER = 100_000
CHAT_MESSAGE_PAGE_SIZE = 50
# A meeting's chat is kept as long as its transcript.
CHAT_LOOKBACK_S = TRANSCRIPT_LOOKBACK_S
# People fix or delete what they wrote soon after writing it, so a chat is asked
# Newest message first, so a walk stops at the first chat quiet since the
# lookback opened. Graph sorts a chat with no message last.
CHATS_QUERY = (
    "$filter=chatType eq 'meeting'&$expand=lastMessagePreview"
    f"&$orderby=lastMessagePreview/createdDateTime desc&$top={CHAT_PAGE_SIZE}"
)


def chat_document_id(organizer_id: str, chat_id: str, day: date) -> str:
    """Chats are listed per organizer and a document is one day of one chat."""
    return (
        f"{MEETING_CHAT_DOCUMENT_ID_PREFIX}{organizer_id}:{chat_id}:{day.isoformat()}"
    )


class MeetingChat(BaseModel):
    id: str
    topic: str | None
    web_url: str | None
    organizer_id: str | None
    last_message_at: datetime | None

    @classmethod
    def from_graph(cls, row: dict[str, Any]) -> "MeetingChat":
        organizer = (row.get("onlineMeetingInfo") or {}).get("organizer") or {}
        return cls(
            id=row["id"],
            topic=row.get("topic"),
            web_url=row.get("webUrl"),
            organizer_id=organizer.get("id"),
            last_message_at=(row.get("lastMessagePreview") or {}).get(
                "createdDateTime"
            ),
        )


class ChatMessage(Message):
    # Graph links a channel message and gives a chat message no url of its own.
    web_url: str | None = None


class ChatMember(ChannelMember):
    # Someone added to a chat later sees it from here on. Graph writes year 1
    # for a member who sees the whole chat.
    visible_history_start_date_time: datetime | None = None


def _graph_timestamp(moment: SecondsSinceUnixEpoch) -> str:
    return datetime.fromtimestamp(moment, tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def fetch_meeting_chats(
    graph_client: GraphClient,
    organizer_id: str,
    before_page: Callable[[], None] | None = None,
) -> Generator[MeetingChat]:
    """The chats of the meetings this user organized with a message inside the
    lookback. Every one of them is asked what changed, since a delete in a chat
    that has gone quiet must still leave the index. Needs Chat.Read.All."""
    since = datetime.fromtimestamp(time.time() - CHAT_LOOKBACK_S, tz=timezone.utc)
    url = f"users/{organizer_id}/chats?{CHATS_QUERY}"
    for row in iter_values(graph_client, url, before_page):
        chat = MeetingChat.from_graph(row)
        if chat.last_message_at is None or chat.last_message_at < since:
            return
        if chat.organizer_id == organizer_id:
            yield chat


def fetch_chat_members(graph_client: GraphClient, chat_id: str) -> list[ChatMember]:
    return [
        ChatMember(**row)
        for row in iter_values(graph_client, f"chats/{chat_id}/members")
    ]


def _messages(
    graph_client: GraphClient,
    chat_id: str,
    query: str,
    before_page: Callable[[], None] | None,
) -> Generator[ChatMessage]:
    url = f"chats/{chat_id}/messages?$top={CHAT_MESSAGE_PAGE_SIZE}&{query}"
    for row in iter_values(graph_client, url, before_page):
        # Graph names no display name for some senders, as in channels.
        yield ChatMessage(**_sanitize_message_user_display_name(row))


def _day_bounds(day: date) -> tuple[datetime, datetime]:
    opens = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    return opens, opens + timedelta(days=1)


def fetch_chat_days(
    graph_client: GraphClient,
    chat_id: str,
    start: SecondsSinceUnixEpoch | None,
    before_page: Callable[[], None] | None = None,
) -> Iterator[tuple[date, list[ChatMessage]]]:
    """Each day that changed since ``start`` with every message of it, oldest
    first. A day is a document, so one new, edited or deleted message brings the
    whole day back. Days are UTC and never older than the lookback. Graph serves
    the chat newest first, so a day is yielded as soon as an older one begins,
    and a chat of any length holds one day at a time."""
    lookback_opens = time.time() - CHAT_LOOKBACK_S
    # A whole day or none of it: a day cut at the lookback's edge would take its
    # readers from a later message than the document indexed whole.
    oldest = _day_bounds(
        datetime.fromtimestamp(lookback_opens, tz=timezone.utc).date()
    )[1]
    touched: set[date] | None = None
    # A window as old as the lookback reads every day of it, so asking what
    # changed first would read every message twice.
    if start is not None and start > lookback_opens:
        touched = {
            message.created_date_time.date()
            for message in _messages(
                graph_client,
                chat_id,
                f"$filter=lastModifiedDateTime gt {_graph_timestamp(start)}"
                "&$orderby=lastModifiedDateTime desc",
                before_page,
            )
            if message.created_date_time >= oldest
        }
        if not touched:
            return

    reads_from = _day_bounds(max(touched))[1] if touched else None
    reads_to = _day_bounds(min(touched))[0] if touched else oldest
    created_before = (
        f"$filter=createdDateTime lt {_graph_timestamp(reads_from.timestamp())}&"
        if reads_from
        else ""
    )
    current: date | None = None
    messages: list[ChatMessage] = []
    for message in _messages(
        graph_client,
        chat_id,
        f"{created_before}$orderby=createdDateTime desc",
        before_page,
    ):
        if message.created_date_time < reads_to:
            break
        day = message.created_date_time.date()
        if day != current:
            if current is not None and messages:
                yield current, messages[::-1]
            current, messages = day, []
        if touched is None or day in touched:
            messages.append(message)
    if current is not None and messages:
        yield current, messages[::-1]


def chat_day_access(
    members: list[ChatMember],
    directory: UserDirectory,
    first_message_at: datetime,
) -> ExternalAccess:
    """The members who see the day's first message, and so the whole day.
    Someone added later reads the days after, as in Teams. A row carries its
    email for users of any tenant, and one without is named by ``directory``."""
    readers = [
        member
        for member in members
        if member.visible_history_start_date_time is None
        or member.visible_history_start_date_time <= first_message_at
    ]
    names = directory.principal_names(
        [m.user_id for m in readers if not m.email and m.user_id]
    )
    return ExternalAccess(
        external_user_emails={
            email.lower()
            for member in readers
            if (email := member.email or names.get(member.user_id or ""))
        },
        external_user_group_ids=set(),
        is_public=False,
    )


def _until_refused(
    organizer: Organizer,
    chat: MeetingChat,
    days: Iterator[tuple[date, list[ChatMessage]]],
    refused: Callable[[requests.HTTPError], bool],
) -> Iterator[tuple[date, list[ChatMessage]]]:
    """The days as they come, until Graph refuses the chat: that is a warning
    and the end of the chat. Anything else fails the attempt."""
    try:
        yield from days
    except requests.HTTPError as e:
        if not refused(e):
            raise
        _warn_chat_refused(organizer, chat, e)


def _too_many_chats(organizer: Organizer) -> RuntimeError:
    return RuntimeError(
        f"The meeting chats of {organizer.email} did not end after "
        f"{MAX_CHATS_PER_ORGANIZER}, more than one organizer can hold"
    )


def _warn_chat_refused(
    organizer: Organizer, chat: MeetingChat, error: requests.HTTPError
) -> None:
    logger.warning(
        'The chat of meeting "%s" organized by %s is not readable: Graph '
        "answered %s, %s",
        chat.topic,
        organizer.email,
        status(error),
        graph_error_message(error) or "no message",
    )


def _written(messages: list[ChatMessage]) -> list[ChatMessage]:
    """What people wrote, deleted or not, without the meeting's own events. Both
    walks read a day's readers off the first of these: a delete can go unseen
    and leave its text indexed, and a later first message would widen access."""
    return [m for m in messages if m.message_type in (None, "message")]


def _chat_refusal(error: requests.HTTPError) -> str:
    """The admin-facing cause of a refused chat call."""
    if status(error) in (401, 403):
        return (
            "Include Meeting Chats needs the Chat.Read.All application "
            f"permission. {graph_said(error)}"
        )
    return f"Graph answered {status(error)}. {graph_said(error)}"


class ChatSource(OrganizerSource):
    option = "Include Meeting Chats"
    document_id_prefix = MEETING_CHAT_DOCUMENT_ID_PREFIX

    def __init__(self, session: TeamsSession, include_inline_images: bool) -> None:
        self._session = session
        self._include_inline_images = include_inline_images

    def validate(self, organizer: Organizer) -> None:
        """Lists the organizer's meeting chats, which is where Graph answers for
        the chat grant. Reading a chat takes the same grant and no policy."""
        try:
            next(fetch_meeting_chats(self._session.graph(), organizer.id), None)
        except requests.HTTPError as e:
            if status(e) in (401, 403):
                raise InsufficientPermissionsError(_chat_refusal(e))
            raise UnexpectedValidationError(f"Could not list meeting chats: {e}")
        except (GraphRetriesExhausted, requests.RequestException) as e:
            raise UnexpectedValidationError(f"Could not list meeting chats: {e}")

    def index(
        self,
        organizer: Organizer,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,  # noqa: ARG002
    ) -> Iterator[Document | ConnectorFailure]:
        """The chats of the meetings one organizer set up, a document per day
        that changed. A refused listing is one recorded failure for the
        organizer and a refused chat a warning. Refused after it answered,
        either fails the attempt."""
        listing = PagedListing()
        chats = fetch_meeting_chats(
            self._session.graph(), organizer.id, listing.before_page
        )
        for _ in range(MAX_CHATS_PER_ORGANIZER):
            # Only the listing's own refusal speaks for the organizer. What a
            # chat raises while it is read is judged with that chat.
            try:
                chat = next(chats, None)
            except requests.HTTPError as e:
                if not listing.lost_access(e):
                    raise
                yield ConnectorFailure(
                    failed_entity=EntityFailure(entity_id=organizer.id),
                    failure_message=(
                        f"Could not list the meeting chats of {organizer.email}: "
                        f"{_chat_refusal(e)}"
                    ),
                    exception=e,
                )
                return
            if chat is None:
                return
            yield from self._chat_documents(organizer, chat, start)
        raise _too_many_chats(organizer)

    def _chat_documents(
        self, organizer: Organizer, chat: MeetingChat, start: SecondsSinceUnixEpoch
    ) -> Iterator[Document | ConnectorFailure]:
        # The listing just answered with the same grant, so a refused chat is
        # the one chat and not the setup. A recorded failure would hold every
        # later poll to this window for a chat that may never open. A chat
        # refused after it answered fails the attempt, since a day written and
        # the rest skipped would look like a whole poll.
        listing = PagedListing()
        days = _until_refused(
            organizer,
            chat,
            fetch_chat_days(self._session.graph(), chat.id, start, listing.before_page),
            listing.lost_access,
        )
        members: list[ChatMember] | None = None
        for day, messages in days:
            if members is None:
                members = self._members(organizer, chat)
                if members is None:
                    return
            document = self._chat_day_document(organizer, chat, day, messages, members)
            if document is not None:
                yield document

    def _members(
        self, organizer: Organizer, chat: MeetingChat
    ) -> list[ChatMember] | None:
        """The chat's members, or None for a chat whose members Graph refuses.
        Read once a chat has a day to write, since most chats a poll lists
        have none."""
        try:
            return fetch_chat_members(self._session.graph(), chat.id)
        except requests.HTTPError as e:
            if not is_permanent(e):
                raise
            _warn_chat_refused(organizer, chat, e)
            return None

    def _chat_day_document(
        self,
        organizer: Organizer,
        chat: MeetingChat,
        day: date,
        messages: list[ChatMessage],
        members: list[ChatMember],
    ) -> Document | None:
        """One day of a meeting's chat. Graph lists a meeting's events (joined,
        recording started) as messages too, and a day of those alone is no
        document."""
        written = _written(messages)
        if not written:
            return None
        kept = [m for m in written if m.is_indexable]
        first = written[0]
        sections: list[TextSection | ImageSection] = []
        images_left = images.MAX_IMAGES_PER_DOCUMENT
        missed_images = 0
        for message in kept:
            body = message_text(message)
            if body:
                sections.append(TextSection(link=chat.web_url, text=body))
            if not self._include_inline_images:
                continue
            harvest = harvest_message_images(
                self._session, message, images_left, chat.web_url
            )
            images_left -= harvest.downloads
            missed_images += harvest.missed
            sections.extend(harvest.sections)
        title = f"Chat of {chat.topic}" if chat.topic else "Meeting chat"
        # A day whose messages were all deleted still replaces its document, or
        # the deleted text would stay searchable until the next pruning.
        if not sections:
            sections = [TextSection(link=chat.web_url, text=title)]
        metadata = {"organizer": organizer.email or ""}
        if missed_images:
            metadata[IMAGES_NOT_INDEXED] = str(missed_images)
        return Document(
            id=chat_document_id(organizer.id, chat.id, day),
            sections=sections,
            source=DocumentSource.TEAMS,
            semantic_identifier=f"{title} ({day})",
            title=title,
            doc_created_at=first.created_date_time,
            doc_updated_at=max(modified_at(message) for message in written),
            primary_owners=message_authors(kept),
            metadata=metadata,
            external_access=chat_day_access(
                members, self._session.directory(), first.created_date_time
            ),
        )

    def slim(self, organizer: Organizer, walk: SlimWalk) -> Iterator[SlimDocument]:
        """The days of one organizer's meeting chats, with the ids the indexing
        walk writes. A refused organizer or chat lists nothing and the walk
        goes on: the app lost those chats, so pruning removes them."""
        listing = PagedListing(walk)
        chats = fetch_meeting_chats(
            self._session.graph(), organizer.id, listing.before_page
        )
        for _ in range(MAX_CHATS_PER_ORGANIZER):
            # Only the listing's own refusal speaks for the organizer. What a
            # chat raises while it is read is judged with that chat.
            try:
                chat = next(chats, None)
            except requests.HTTPError as e:
                if not listing.lost_access(e):
                    raise
                logger.warning(
                    "Could not list the meeting chats of %s, so their indexed "
                    "chats are pruned: %s",
                    organizer.email,
                    _chat_refusal(e),
                )
                return
            if chat is None:
                return
            yield from self._slim_chat(organizer, chat, walk)
        raise _too_many_chats(organizer)

    def _slim_chat(
        self, organizer: Organizer, chat: MeetingChat, walk: SlimWalk
    ) -> Iterator[SlimDocument]:
        listing = PagedListing(walk)
        days = _until_refused(
            organizer,
            chat,
            fetch_chat_days(self._session.graph(), chat.id, None, listing.before_page),
            listing.lost_access,
        )
        members: list[ChatMember] | None = []
        for day, messages in days:
            written = _written(messages)
            if not any(m.is_indexable for m in written):
                continue
            if walk.with_readers and not members:
                # Days with no known reader are left out, which hides them.
                members = self._members(organizer, chat)
                if members is None:
                    return
            first_at = written[0].created_date_time
            yield SlimDocument(
                id=chat_document_id(organizer.id, chat.id, day),
                external_access=(
                    chat_day_access(members, self._session.directory(), first_at)
                    if walk.with_readers
                    else None
                ),
                doc_created_at=first_at,
            )
