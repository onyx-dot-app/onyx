"""Channel threads: a root message and its replies are one document, readable
through the group of its channel's members."""

from collections.abc import Iterator
from datetime import datetime

import requests

from onyx.configs.constants import DocumentSource
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.models import (
    BasicExpertInfo,
    ConnectorFailure,
    Document,
    EntityFailure,
    ImageSection,
    SlimDocument,
    TextSection,
)
from onyx.connectors.teams.images import (
    IMAGES_NOT_INDEXED,
    ImageHarvest,
    MessageImages,
    harvest_message_images,
)
from onyx.connectors.teams.models import ChannelRef, Message
from onyx.connectors.teams.refusals import channel_failure, is_permanent
from onyx.connectors.teams.session import TeamsSession
from onyx.connectors.teams.sources import SlimWalk
from onyx.connectors.teams.utils import (
    channel_access,
    fetch_channel_membership_type,
    fetch_message_page,
    fetch_messages,
    fetch_replies,
    message_delta_url,
)
from onyx.file_processing.html_utils import parse_html_page_basic
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Each pasted image costs a download now and a vision-model call at indexing,
# so a thread stops well past what a working conversation holds.
_MAX_IMAGES_PER_THREAD = 100


def _sender_name(message: Message) -> str:
    """Bots and apps post without a user, so the sender is not always known."""
    if message.from_ and message.from_.user and message.from_.user.display_name:
        return message.from_.user.display_name
    return "Unknown User"


def _construct_semantic_identifier(channel: ChannelRef, top_message: Message) -> str:
    top_message_user_name = _sender_name(top_message)
    top_message_content = top_message.body.content or ""
    top_message_subject = top_message.subject or "Unknown Subject"
    channel_name = channel.display_name

    try:
        snippet = parse_html_page_basic(top_message_content.rstrip())
        snippet = snippet[:50] + "..." if len(snippet) > 50 else snippet

    except Exception:
        logger.exception(
            "Error parsing snippet for message %s with url %s",
            top_message.id,
            top_message.web_url,
        )
        snippet = ""

    semantic_identifier = (
        f"{top_message_user_name} in {channel_name} about {top_message_subject}"
    )
    if snippet:
        semantic_identifier += f": {snippet}"

    return semantic_identifier


def _message_header(message: Message) -> str:
    return (
        f"From: {_sender_name(message)}\nDate: {message.created_date_time.isoformat()}"
    )


def _message_section(message: Message) -> TextSection | None:
    """One section per message, so a hit cites the message that said it."""
    body = parse_html_page_basic(message.body.content) if message.body.content else ""
    body = body.strip()
    if not body:
        return None
    return TextSection(
        link=message.web_url, text=f"{_message_header(message)}\n\n{body}"
    )


def _modified_at(message: Message) -> datetime:
    return message.last_modified_date_time or message.created_date_time


def _thread_authors(messages: list[Message]) -> list[BasicExpertInfo]:
    """The people who wrote in the thread, each once by user id: two people can
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


def _convert_thread_to_document(
    channel: ChannelRef,
    root: Message,
    replies: list[Message],
    message_images: MessageImages | None,
) -> Document:
    """A thread (the root message and its replies) is one document, oldest
    first, each message's text followed by the images pasted into it."""
    messages = sorted([root, *replies], key=lambda m: m.created_date_time)
    sections: list[TextSection | ImageSection] = []
    images_left = _MAX_IMAGES_PER_THREAD
    missed_images = 0
    for message in messages:
        if not message.is_indexable:
            continue
        if section := _message_section(message):
            sections.append(section)
        if message_images is None:
            continue
        harvest = message_images(message, images_left)
        images_left -= harvest.downloads
        missed_images += harvest.missed
        sections.extend(harvest.sections)
    # The slim walk lists every indexable root, so a thread left with no text
    # and no image must still replace its document or the old text would
    # outlive it.
    if not sections:
        sections = [TextSection(link=root.web_url, text=_message_header(root))]

    return Document(
        id=root.id,
        sections=sections,
        source=DocumentSource.TEAMS,
        semantic_identifier=_construct_semantic_identifier(channel, root),
        title="",  # teams threads don't really have a "title"
        doc_created_at=root.created_date_time,
        # Indexing skips a document whose update time has not moved, and an
        # edit or a deleted reply moves a message's modified time, not its creation.
        doc_updated_at=max(_modified_at(message) for message in messages),
        primary_owners=_thread_authors(messages),
        metadata=({IMAGES_NOT_INDEXED: str(missed_images)} if missed_images else {}),
        external_access=channel_access(channel, for_indexing=True),
    )


class ThreadSource:
    def __init__(self, session: TeamsSession, include_inline_images: bool) -> None:
        self._session = session
        self._include_inline_images = include_inline_images

    def type_failure(self, channel: ChannelRef) -> ConnectorFailure | None:
        """A checkpoint an older version saved holds its channels without a type,
        so it is read before a thread names a group. A refused read skips the
        channel: a guessed group could be one the group sync never lists."""
        if channel.membership_type is not None:
            return None
        try:
            channel.membership_type = fetch_channel_membership_type(
                self._session.graph(), channel.team_id, channel.id
            )
        except requests.HTTPError as e:
            if not is_permanent(e):
                raise
            return channel_failure(channel, "type", e)
        return None

    def page(
        self,
        channel: ChannelRef,
        page_url: str | None,
        start: SecondsSinceUnixEpoch,
    ) -> tuple[list[Message], str | None]:
        """One page of the channel's root messages and the url of the next, the
        first page when no url is saved."""
        return fetch_message_page(
            graph_client=self._session.graph(),
            request_url=page_url
            or message_delta_url(channel.team_id, channel.id, start),
        )

    def documents(
        self, channel: ChannelRef, roots: list[Message]
    ) -> Iterator[Document | ConnectorFailure]:
        for root in roots:
            # A thread is its root message. A deleted or system root drops the
            # whole thread, which is what the slim walk lists for pruning too.
            if not root.is_indexable:
                continue
            try:
                replies = list(
                    fetch_replies(
                        graph_client=self._session.graph(),
                        team_id=channel.team_id,
                        channel_id=channel.id,
                        root_message_id=root.id,
                    )
                )
            except requests.HTTPError as e:
                if not is_permanent(e):
                    raise
                yield ConnectorFailure(
                    failed_entity=EntityFailure(entity_id=root.id),
                    failure_message=f"Could not read the replies of {root.id} in channel {channel.id}",
                    exception=e,
                )
                continue
            yield _convert_thread_to_document(
                channel=channel,
                root=root,
                replies=replies,
                message_images=(
                    self._message_images if self._include_inline_images else None
                ),
            )

    def slim(self, channel: ChannelRef, walk: SlimWalk) -> Iterator[SlimDocument]:
        # A thread names its channel's group, so readers cost no call.
        external_access = (
            channel_access(channel, for_indexing=False) if walk.with_readers else None
        )
        messages = fetch_messages(
            graph_client=self._session.graph(),
            team_id=channel.team_id,
            channel_id=channel.id,
            start=walk.start,
        )
        return (
            SlimDocument(
                id=message.id,
                external_access=external_access,
                # NOTE: doc_created_at population not yet verified against live data
                doc_created_at=message.created_date_time,
            )
            # The indexing walk skips these roots, so listing them here would
            # keep their stale documents out of pruning.
            for message in messages
            if message.is_indexable
        )

    def _message_images(self, message: Message, limit: int) -> ImageHarvest:
        return harvest_message_images(self._session, message, limit)
