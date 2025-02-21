import contextvars
import copy
import re
from collections.abc import Callable
from collections.abc import Generator
from concurrent.futures import as_completed
from concurrent.futures import Future
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from datetime import timezone
from typing import Any
from typing import cast
from typing import TypedDict

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from onyx.configs.app_configs import ENABLE_EXPENSIVE_EXPERT_CALLS
from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.interfaces import CheckpointConnector
from onyx.connectors.interfaces import CheckpointOutput
from onyx.connectors.interfaces import GenerateSlimDocumentOutput
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.interfaces import SlimConnector
from onyx.connectors.models import BasicExpertInfo
from onyx.connectors.models import ConnectorCheckpoint
from onyx.connectors.models import ConnectorFailure
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.models import Document
from onyx.connectors.models import DocumentFailure
from onyx.connectors.models import EntityFailure
from onyx.connectors.models import Section
from onyx.connectors.models import SlimDocument
from onyx.connectors.slack.utils import expert_info_from_slack_id
from onyx.connectors.slack.utils import get_message_link
from onyx.connectors.slack.utils import make_paginated_slack_api_call_w_retries
from onyx.connectors.slack.utils import make_slack_api_call_w_retries
from onyx.connectors.slack.utils import SlackTextCleaner
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.utils.logger import setup_logger


logger = setup_logger()

_SLACK_LIMIT = 900


ChannelType = dict[str, Any]
MessageType = dict[str, Any]
# list of messages in a thread
ThreadType = list[MessageType]


class SlackCheckpointContent(TypedDict):
    channel_ids: list[str]
    channel_completion_map: dict[str, str]
    current_channel: ChannelType | None
    seen_thread_ts: list[str]


def _collect_paginated_channels(
    client: WebClient,
    exclude_archived: bool,
    channel_types: list[str],
) -> list[ChannelType]:
    channels: list[dict[str, Any]] = []
    for result in make_paginated_slack_api_call_w_retries(
        client.conversations_list,
        exclude_archived=exclude_archived,
        # also get private channels the bot is added to
        types=channel_types,
    ):
        channels.extend(result["channels"])

    return channels


def get_channels(
    client: WebClient,
    exclude_archived: bool = True,
    get_public: bool = True,
    get_private: bool = True,
) -> list[ChannelType]:
    """Get all channels in the workspace"""
    channels: list[dict[str, Any]] = []
    channel_types = []
    if get_public:
        channel_types.append("public_channel")
    if get_private:
        channel_types.append("private_channel")
    # try getting private channels as well at first
    try:
        channels = _collect_paginated_channels(
            client=client,
            exclude_archived=exclude_archived,
            channel_types=channel_types,
        )
    except SlackApiError as e:
        logger.info(f"Unable to fetch private channels due to - {e}")
        logger.info("trying again without private channels")
        if get_public:
            channel_types = ["public_channel"]
        else:
            logger.warning("No channels to fetch")
            return []
        channels = _collect_paginated_channels(
            client=client,
            exclude_archived=exclude_archived,
            channel_types=channel_types,
        )

    return channels


def get_channel_messages(
    client: WebClient,
    channel: dict[str, Any],
    oldest: str | None = None,
    latest: str | None = None,
    callback: IndexingHeartbeatInterface | None = None,
) -> Generator[list[MessageType], None, None]:
    """Get all messages in a channel"""
    # join so that the bot can access messages
    if not channel["is_member"]:
        make_slack_api_call_w_retries(
            client.conversations_join,
            channel=channel["id"],
            is_private=channel["is_private"],
        )
        logger.info(f"Successfully joined '{channel['name']}'")

    for result in make_paginated_slack_api_call_w_retries(
        client.conversations_history,
        channel=channel["id"],
        oldest=oldest,
        latest=latest,
    ):
        if callback:
            if callback.should_stop():
                raise RuntimeError("get_channel_messages: Stop signal detected")

            callback.progress("get_channel_messages", 0)
        yield cast(list[MessageType], result["messages"])


def get_thread(client: WebClient, channel_id: str, thread_id: str) -> ThreadType:
    """Get all messages in a thread"""
    threads: list[MessageType] = []
    for result in make_paginated_slack_api_call_w_retries(
        client.conversations_replies, channel=channel_id, ts=thread_id
    ):
        threads.extend(result["messages"])
    return threads


def get_latest_message_time(thread: ThreadType) -> datetime:
    max_ts = max([float(msg.get("ts", 0)) for msg in thread])
    return datetime.fromtimestamp(max_ts, tz=timezone.utc)


def _build_doc_id(channel_id: str, thread_ts: str) -> str:
    return f"{channel_id}__{thread_ts}"


def thread_to_doc(
    channel: ChannelType,
    thread: ThreadType,
    slack_cleaner: SlackTextCleaner,
    client: WebClient,
    user_cache: dict[str, BasicExpertInfo | None],
) -> Document:
    channel_id = channel["id"]

    initial_sender_expert_info = expert_info_from_slack_id(
        user_id=thread[0].get("user"), client=client, user_cache=user_cache
    )
    initial_sender_name = (
        initial_sender_expert_info.get_semantic_name()
        if initial_sender_expert_info
        else "Unknown"
    )

    valid_experts = None
    if ENABLE_EXPENSIVE_EXPERT_CALLS:
        all_sender_ids = [m.get("user") for m in thread]
        experts = [
            expert_info_from_slack_id(
                user_id=sender_id, client=client, user_cache=user_cache
            )
            for sender_id in all_sender_ids
            if sender_id
        ]
        valid_experts = [expert for expert in experts if expert]

    first_message = slack_cleaner.index_clean(cast(str, thread[0]["text"]))
    snippet = (
        first_message[:50].rstrip() + "..."
        if len(first_message) > 50
        else first_message
    )

    doc_sem_id = f"{initial_sender_name} in #{channel['name']}: {snippet}".replace(
        "\n", " "
    )

    return Document(
        id=_build_doc_id(channel_id=channel_id, thread_ts=thread[0]["ts"]),
        sections=[
            Section(
                link=get_message_link(event=m, client=client, channel_id=channel_id),
                text=slack_cleaner.index_clean(cast(str, m["text"])),
            )
            for m in thread
        ],
        source=DocumentSource.SLACK,
        semantic_identifier=doc_sem_id,
        doc_updated_at=get_latest_message_time(thread),
        title="",  # slack docs don't really have a "title"
        primary_owners=valid_experts,
        metadata={"Channel": channel["name"]},
    )


# list of subtypes can be found here: https://api.slack.com/events/message
_DISALLOWED_MSG_SUBTYPES = {
    "channel_join",
    "channel_leave",
    "channel_archive",
    "channel_unarchive",
    "pinned_item",
    "unpinned_item",
    "ekm_access_denied",
    "channel_posting_permissions",
    "group_join",
    "group_leave",
    "group_archive",
    "group_unarchive",
    "channel_leave",
    "channel_name",
    "channel_join",
}


def default_msg_filter(message: MessageType) -> bool:
    # Don't keep messages from bots
    if message.get("bot_id") or message.get("app_id"):
        if message.get("bot_profile", {}).get("name") == "OnyxConnector":
            return False
        return True

    # Uninformative
    if message.get("subtype", "") in _DISALLOWED_MSG_SUBTYPES:
        return True

    return False


def filter_channels(
    all_channels: list[dict[str, Any]],
    channels_to_connect: list[str] | None,
    regex_enabled: bool,
) -> list[dict[str, Any]]:
    if not channels_to_connect:
        return all_channels

    if regex_enabled:
        return [
            channel
            for channel in all_channels
            if any(
                re.fullmatch(channel_to_connect, channel["name"])
                for channel_to_connect in channels_to_connect
            )
        ]

    # validate that all channels in `channels_to_connect` are valid
    # fail loudly in the case of an invalid channel so that the user
    # knows that one of the channels they've specified is typo'd or private
    all_channel_names = {channel["name"] for channel in all_channels}
    for channel in channels_to_connect:
        if channel not in all_channel_names:
            raise ValueError(
                f"Channel '{channel}' not found in workspace. "
                f"Available channels: {all_channel_names}"
            )

    return [
        channel for channel in all_channels if channel["name"] in channels_to_connect
    ]


def _get_channel_by_id(client: WebClient, channel_id: str) -> ChannelType:
    """Get a channel by its ID.

    Args:
        client: The Slack WebClient instance
        channel_id: The ID of the channel to fetch

    Returns:
        The channel information

    Raises:
        SlackApiError: If the channel cannot be fetched
    """
    response = make_slack_api_call_w_retries(
        client.conversations_info,
        channel=channel_id,
    )
    return cast(ChannelType, response["channel"])


def _get_messages(
    channel: ChannelType,
    client: WebClient,
    oldest: str | None = None,
    latest: str | None = None,
) -> tuple[list[MessageType], bool]:
    """Slack goes from newest to oldest."""

    # have to be in the channel in order to read messages
    if not channel["is_member"]:
        make_slack_api_call_w_retries(
            client.conversations_join,
            channel=channel["id"],
            is_private=channel["is_private"],
        )
        logger.info(f"Successfully joined '{channel['name']}'")

    response = make_slack_api_call_w_retries(
        client.conversations_history,
        channel=channel["id"],
        oldest=oldest,
        latest=latest,
        limit=_SLACK_LIMIT,
    )
    response.validate()

    messages = cast(list[MessageType], response.get("messages", []))

    cursor = cast(dict[str, Any], response.get("response_metadata", {})).get(
        "next_cursor", ""
    )
    has_more = bool(cursor)
    return messages, has_more


def _message_to_doc(
    message: MessageType,
    client: WebClient,
    channel: ChannelType,
    slack_cleaner: SlackTextCleaner,
    user_cache: dict[str, BasicExpertInfo | None],
    seen_thread_ts: set[str],
    msg_filter_func: Callable[[MessageType], bool] = default_msg_filter,
) -> Document | None:
    filtered_thread: ThreadType | None = None
    thread_ts = message.get("thread_ts")
    if thread_ts:
        # skip threads we've already seen, since we've already processed all
        # messages in that thread
        if thread_ts in seen_thread_ts:
            return None

        thread = get_thread(
            client=client, channel_id=channel["id"], thread_id=thread_ts
        )
        filtered_thread = [
            message for message in thread if not msg_filter_func(message)
        ]
    elif not msg_filter_func(message):
        filtered_thread = [message]

    if filtered_thread:
        return thread_to_doc(
            channel=channel,
            thread=filtered_thread,
            slack_cleaner=slack_cleaner,
            client=client,
            user_cache=user_cache,
        )

    return None


def _get_all_doc_ids(
    client: WebClient,
    channels: list[str] | None = None,
    channel_name_regex_enabled: bool = False,
    msg_filter_func: Callable[[MessageType], bool] = default_msg_filter,
    callback: IndexingHeartbeatInterface | None = None,
) -> GenerateSlimDocumentOutput:
    """
    Get all document ids in the workspace, channel by channel
    This is pretty identical to get_all_docs, but it returns a set of ids instead of documents
    This makes it an order of magnitude faster than get_all_docs
    """

    all_channels = get_channels(client)
    filtered_channels = filter_channels(
        all_channels, channels, channel_name_regex_enabled
    )

    for channel in filtered_channels:
        channel_id = channel["id"]
        channel_message_batches = get_channel_messages(
            client=client,
            channel=channel,
            callback=callback,
        )

        message_ts_set: set[str] = set()
        for message_batch in channel_message_batches:
            for message in message_batch:
                if msg_filter_func(message):
                    continue

                # The document id is the channel id and the ts of the first message in the thread
                # Since we already have the first message of the thread, we dont have to
                # fetch the thread for id retrieval, saving time and API calls
                message_ts_set.add(message["ts"])

        channel_metadata_list: list[SlimDocument] = []
        for message_ts in message_ts_set:
            channel_metadata_list.append(
                SlimDocument(
                    id=_build_doc_id(channel_id=channel_id, thread_ts=message_ts),
                    perm_sync_data={"channel_id": channel_id},
                )
            )

        yield channel_metadata_list


def _process_message(
    message: MessageType,
    client: WebClient,
    channel: ChannelType,
    slack_cleaner: SlackTextCleaner,
    user_cache: dict[str, BasicExpertInfo | None],
    seen_thread_ts: set[str],
    msg_filter_func: Callable[[MessageType], bool] = default_msg_filter,
) -> tuple[Document | None, str | None, ConnectorFailure | None]:
    thread_ts = message.get("thread_ts")
    try:
        # causes random failures for testing checkpointing / continue on failure
        # import random
        # if random.random() > 0.95:
        #     raise RuntimeError("Random failure :P")

        doc = _message_to_doc(
            message=message,
            client=client,
            channel=channel,
            slack_cleaner=slack_cleaner,
            user_cache=user_cache,
            seen_thread_ts=seen_thread_ts,
            msg_filter_func=msg_filter_func,
        )
        return (doc, thread_ts, None)
    except Exception as e:
        logger.exception(f"Error processing message {message['ts']}")
        return (
            None,
            thread_ts,
            ConnectorFailure(
                failed_document=DocumentFailure(
                    document_id=_build_doc_id(
                        channel_id=channel["id"], thread_ts=(thread_ts or message["ts"])
                    ),
                    document_link=get_message_link(message, client, channel["id"]),
                ),
                failure_message=str(e),
                exception=e,
            ),
        )


class SlackConnector(SlimConnector, CheckpointConnector):
    def __init__(
        self,
        channels: list[str] | None = None,
        # if specified, will treat the specified channel strings as
        # regexes, and will only index channels that fully match the regexes
        channel_regex_enabled: bool = False,
        batch_size: int = INDEX_BATCH_SIZE,
    ) -> None:
        self.channels = channels
        self.channel_regex_enabled = channel_regex_enabled
        self.batch_size = batch_size
        self.client: WebClient | None = None

        # just used for efficiency
        self.text_cleaner: SlackTextCleaner | None = None
        self.user_cache: dict[str, BasicExpertInfo | None] = {}

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        bot_token = credentials["slack_bot_token"]
        self.client = WebClient(token=bot_token)
        self.text_cleaner = SlackTextCleaner(client=self.client)
        return None

    def retrieve_all_slim_documents(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
        callback: IndexingHeartbeatInterface | None = None,
    ) -> GenerateSlimDocumentOutput:
        if self.client is None:
            raise ConnectorMissingCredentialError("Slack")

        return _get_all_doc_ids(
            client=self.client,
            channels=self.channels,
            channel_name_regex_enabled=self.channel_regex_enabled,
            callback=callback,
        )

    def load_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: ConnectorCheckpoint,
    ) -> CheckpointOutput:
        """Rough outline:

        Step 1: Get all channels, yield back Checkpoint.
        Step 2: Loop through each channel. For each channel:
            Step 2.1: Get messages within the time range.
            Step 2.2: Process messages in parallel, yield back docs.
            Step 2.3: Update checkpoint with new_latest, seen_thread_ts, and current_channel.
                      Slack returns messages from newest to oldest, so we need to keep track of
                      the latest message we've seen in each channel.
            Step 2.4: If there are no more messages in the channel, switch the current
                      channel to the next channel.
        """
        if self.client is None or self.text_cleaner is None:
            raise ConnectorMissingCredentialError("Slack")

        checkpoint_content = cast(
            SlackCheckpointContent,
            (
                copy.deepcopy(checkpoint.checkpoint_content)
                or {
                    "channel_ids": None,
                    "channel_completion_map": {},
                    "current_channel": None,
                    "seen_thread_ts": [],
                }
            ),
        )

        # if this is the very first time we've called this, need to
        # get all relevant channels and save them into the checkpoint
        if checkpoint_content["channel_ids"] is None:
            raw_channels = get_channels(self.client)
            filtered_channels = filter_channels(
                raw_channels, self.channels, self.channel_regex_enabled
            )
            if len(filtered_channels) == 0:
                return checkpoint

            checkpoint_content["channel_ids"] = [c["id"] for c in filtered_channels]
            checkpoint_content["current_channel"] = filtered_channels[0]
            checkpoint = ConnectorCheckpoint(
                checkpoint_content=checkpoint_content,  # type: ignore
                has_more=True,
            )
            return checkpoint

        final_channel_ids = checkpoint_content["channel_ids"]
        channel = checkpoint_content["current_channel"]
        if channel is None:
            raise ValueError("current_channel key not found in checkpoint")

        channel_id = channel["id"]
        if channel_id not in final_channel_ids:
            raise ValueError(f"Channel {channel_id} not found in checkpoint")

        oldest = str(start) if start else None
        latest = checkpoint_content["channel_completion_map"].get(channel_id, str(end))
        seen_thread_ts = set(checkpoint_content["seen_thread_ts"])
        try:
            logger.debug(
                f"Getting messages for channel {channel} within range {oldest} - {latest}"
            )
            message_batch, has_more_in_channel = _get_messages(
                channel, self.client, oldest, latest
            )
            new_latest = message_batch[-1]["ts"] if message_batch else latest

            # Process messages in parallel using ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=8) as executor:
                futures: list[Future] = []
                for message in message_batch:
                    # Capture the current context so that the thread gets the current tenant ID
                    current_context = contextvars.copy_context()
                    futures.append(
                        executor.submit(
                            current_context.run,
                            _process_message,
                            message=message,
                            client=self.client,
                            channel=channel,
                            slack_cleaner=self.text_cleaner,
                            user_cache=self.user_cache,
                            seen_thread_ts=seen_thread_ts,
                        )
                    )

                for future in as_completed(futures):
                    doc, thread_ts, failures = future.result()
                    if doc:
                        # handle race conditions here since this is single
                        # threaded. Multi-threaded _process_message reads from this
                        # but since this is single threaded, we won't run into simul
                        # writes. At worst, we can duplicate a thread, which will be
                        # deduped later on.
                        if thread_ts not in seen_thread_ts:
                            yield doc

                        if thread_ts:
                            seen_thread_ts.add(thread_ts)
                    elif failures:
                        for failure in failures:
                            yield failure

            checkpoint_content["seen_thread_ts"] = list(seen_thread_ts)
            checkpoint_content["channel_completion_map"][channel["id"]] = new_latest
            if has_more_in_channel:
                checkpoint_content["current_channel"] = channel
            else:
                new_channel_id = next(
                    (
                        channel_id
                        for channel_id in final_channel_ids
                        if channel_id
                        not in checkpoint_content["channel_completion_map"]
                    ),
                    None,
                )
                if new_channel_id:
                    new_channel = _get_channel_by_id(self.client, new_channel_id)
                    checkpoint_content["current_channel"] = new_channel
                else:
                    checkpoint_content["current_channel"] = None

            checkpoint = ConnectorCheckpoint(
                checkpoint_content=checkpoint_content,  # type: ignore
                has_more=checkpoint_content["current_channel"] is not None,
            )
            return checkpoint

        except Exception as e:
            logger.exception(f"Error processing channel {channel['name']}")
            yield ConnectorFailure(
                failed_entity=EntityFailure(
                    entity_id=channel["id"],
                    missed_time_range=(
                        datetime.fromtimestamp(start, tz=timezone.utc),
                        datetime.fromtimestamp(end, tz=timezone.utc),
                    ),
                ),
                failure_message=str(e),
                exception=e,
            )
            return checkpoint


if __name__ == "__main__":
    import os
    import time

    slack_channel = os.environ.get("SLACK_CHANNEL")
    connector = SlackConnector(
        channels=[slack_channel] if slack_channel else None,
    )
    connector.load_credentials({"slack_bot_token": os.environ["SLACK_BOT_TOKEN"]})

    current = time.time()
    one_day_ago = current - 24 * 60 * 60  # 1 day

    checkpoint = ConnectorCheckpoint.build_dummy_checkpoint()

    gen = connector.load_from_checkpoint(one_day_ago, current, checkpoint)
    try:
        for document_or_failure in gen:
            if isinstance(document_or_failure, Document):
                print(document_or_failure)
            elif isinstance(document_or_failure, ConnectorFailure):
                print(document_or_failure)
    except StopIteration as e:
        checkpoint = e.value
        print("Next checkpoint:", checkpoint)

    print("Next checkpoint:", checkpoint)
