import asyncio
from collections.abc import AsyncIterable
from collections.abc import Iterable
from datetime import datetime
from datetime import timezone
from typing import Any

from discord import Client
from discord.channel import TextChannel
from discord.channel import Thread
from discord.enums import MessageType
from discord.flags import Intents
from discord.message import Message as DiscordMessage

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.interfaces import GenerateDocumentsOutput
from onyx.connectors.interfaces import LoadConnector
from onyx.connectors.interfaces import PollConnector
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.models import Document
from onyx.connectors.models import Section
from onyx.utils.logger import setup_logger

logger = setup_logger()


_DISCORD_DOC_ID_PREFIX = "DISCORD_"
_SNIPPET_LENGTH = 30


def _convert_message_to_document(
    message: DiscordMessage, sections: list[Section]
) -> Document:
    """
    Convert a discord message to a document
    Sections are collected before calling this function because it relies on async
        calls to fetch the thread history if there is one
    """

    metadata: dict[str, str | list[str]] = {}
    semantic_substring = ""

    # Only messages from TextChannels will make it here but we have to check for it anyways
    if isinstance(message.channel, TextChannel) and (
        channel_name := message.channel.name
    ):
        metadata["Channel"] = channel_name
        semantic_substring += f" in Channel: #{channel_name}"

    # Single messages dont have a title
    title = ""

    # If there is a thread, add more detail to the metadata, title, and semantic identifier
    if isinstance(message.channel, Thread):
        # Threads do have a title
        title = message.channel.name

        # If its a thread, update the metadata, title, and semantic_substring
        metadata["Thread"] = title

        # Add more detail to the semantic identifier if available
        semantic_substring += f" in Thread: {title}"

    snippet: str = (
        message.content[:_SNIPPET_LENGTH].rstrip() + "..."
        if len(message.content) > _SNIPPET_LENGTH
        else message.content
    )

    semantic_identifier = f"{message.author.name} said{semantic_substring}: {snippet}"

    return Document(
        id=f"{_DISCORD_DOC_ID_PREFIX}{message.id}",
        source=DocumentSource.DISCORD,
        semantic_identifier=semantic_identifier,
        doc_updated_at=message.edited_at,
        title=title,
        sections=sections,
        metadata=metadata,
    )


async def _fetch_filtered_channels(
    discord_client: Client,
    server_ids: list[int] | None,
    channel_names: list[str] | None,
) -> list[TextChannel]:
    filtered_channels: list[TextChannel] = []

    for channel in discord_client.get_all_channels():
        if not channel.permissions_for(channel.guild.me).read_message_history:
            continue
        if not isinstance(channel, TextChannel):
            continue
        if server_ids and len(server_ids) > 0 and channel.guild.id not in server_ids:
            continue
        if channel_names and channel.name not in channel_names:
            continue
        filtered_channels.append(channel)

    logger.info(f"Found {len(filtered_channels)} channels for the authenticated user")
    return filtered_channels


async def _fetch_documents_from_channel(
    channel: TextChannel,
    start_time: datetime | None,
    end_time: datetime | None,
) -> AsyncIterable[Document]:
    async for channel_message in channel.history(
        after=start_time,
        before=end_time,
    ):
        # Skip messages that are not the default type
        if channel_message.type != MessageType.default:
            continue

        sections: list[Section] = [
            Section(
                text=channel_message.content,
                link=channel_message.jump_url,
            )
        ]

        yield _convert_message_to_document(channel_message, sections)

    for active_thread in channel.threads:
        async for thread_message in active_thread.history(
            after=start_time,
            before=end_time,
        ):
            # Skip messages that are not the default type
            if thread_message.type != MessageType.default:
                continue

            sections = [
                Section(
                    text=thread_message.content,
                    link=thread_message.jump_url,
                )
            ]

            yield _convert_message_to_document(thread_message, sections)

    async for archived_thread in channel.archived_threads():
        async for thread_message in archived_thread.history(
            after=start_time,
            before=end_time,
        ):
            # Skip messages that are not the default type
            if thread_message.type != MessageType.default:
                continue

            sections = [
                Section(
                    text=thread_message.content,
                    link=thread_message.jump_url,
                )
            ]

            yield _convert_message_to_document(thread_message, sections)


def _manage_async_retrieval(
    token: str,
    start: datetime | None = None,
    end: datetime | None = None,
    requested_start_date_string: str | None = None,
    channel_names: list[str] | None = None,
    server_ids: list[int] | None = None,
) -> Iterable[Document]:
    # parse requested_start_date_string to datetime
    pull_date: datetime | None = (
        datetime.strptime(requested_start_date_string, "%Y-%m-%d").replace(
            tzinfo=timezone.utc
        )
        if requested_start_date_string
        else None
    )

    # Set start_time to the later of start and pull_date, or whichever is provided
    start_time = max(filter(None, [start, pull_date])) if start or pull_date else None

    end_time: datetime | None = end

    async def _async_fetch() -> AsyncIterable[Document]:
        intents = Intents.default()
        intents.message_content = True
        async with Client(intents=intents) as discord_client:
            asyncio.create_task(discord_client.start(token))
            await discord_client.wait_until_ready()

            filtered_channels: list[TextChannel] = await _fetch_filtered_channels(
                discord_client, server_ids=server_ids, channel_names=channel_names
            )

            for channel in filtered_channels:
                async for doc in _fetch_documents_from_channel(
                    channel, start_time=start_time, end_time=end_time
                ):
                    yield doc

    def run_and_yield() -> Iterable[Document]:
        loop = asyncio.new_event_loop()
        try:
            # Get the async generator
            async_gen = _async_fetch()
            # Convert to AsyncIterator
            async_iter = async_gen.__aiter__()
            while True:
                try:
                    # Create a coroutine by calling anext with the async iterator
                    next_coro = anext(async_iter)
                    # Run the coroutine to get the next document
                    doc = loop.run_until_complete(next_coro)
                    yield doc
                except StopAsyncIteration:
                    break
        finally:
            loop.close()

    return run_and_yield()


class DiscordConnector(PollConnector, LoadConnector):
    def __init__(
        self,
        batch_size: int = INDEX_BATCH_SIZE,
        server_ids: list[str] | None = None,
        channel_names: list[str] | None = None,
        start_date: str | None = None,  # YYYY-MM-DD
    ):
        self.batch_size = batch_size
        self.channel_names: list[str] | None = channel_names
        self.server_ids: list[int] | None = (
            [int(server_id) for server_id in server_ids] if server_ids else None
        )
        self._discord_bot_token: str | None = None
        self.requested_start_date_string = start_date

    @property
    def discord_bot_token(self) -> str:
        if self._discord_bot_token is None:
            raise ConnectorMissingCredentialError("Discord")
        return self._discord_bot_token

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        self._discord_bot_token = credentials["discord_bot_token"]
        return None

    def poll_source(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> GenerateDocumentsOutput:
        doc_batch = []
        for doc in _manage_async_retrieval(
            token=self.discord_bot_token,
            start=datetime.fromtimestamp(start, tz=timezone.utc),
            end=datetime.fromtimestamp(end, tz=timezone.utc),
            requested_start_date_string=self.requested_start_date_string,
            channel_names=self.channel_names,
            server_ids=self.server_ids,
        ):
            doc_batch.append(doc)
            if len(doc_batch) >= self.batch_size:
                yield doc_batch
                doc_batch = []

        if doc_batch:
            yield doc_batch

    def load_from_state(self) -> GenerateDocumentsOutput:
        doc_batch = []
        for doc in _manage_async_retrieval(
            token=self.discord_bot_token,
            requested_start_date_string=self.requested_start_date_string,
            channel_names=self.channel_names,
            server_ids=self.server_ids,
        ):
            doc_batch.append(doc)
            if len(doc_batch) >= self.batch_size:
                yield doc_batch
                doc_batch = []

        if doc_batch:
            yield doc_batch


if __name__ == "__main__":
    import os
    import time

    end = time.time()
    start = end - 24 * 60 * 60 * 1  # 1 day
    server_ids: str | None = os.environ.get("server_ids", None)  # "1,2,3"
    channel_names: str | None = os.environ.get(
        "channel_names", None
    )  # "channel1,channel2"

    connector = DiscordConnector(
        server_ids=server_ids.split(",") if server_ids else None,
        channel_names=channel_names.split(",") if channel_names else None,
        start_date=os.environ.get("start_date", None),
    )
    connector.load_credentials(
        {"discord_bot_token": os.environ.get("discord_bot_token")}
    )

    for doc_batch in connector.poll_source(start, end):
        for doc in doc_batch:
            print(doc)
