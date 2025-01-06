import re
from collections.abc import Callable
from collections.abc import Generator
from datetime import datetime
from datetime import timezone
from typing import Any
from typing import cast

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from onyx.configs.app_configs import ENABLE_EXPENSIVE_EXPERT_CALLS
from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.interfaces import GenerateDocumentsOutput
from onyx.connectors.interfaces import GenerateSlimDocumentOutput
from onyx.connectors.interfaces import PollConnector
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.interfaces import SlimConnector
from onyx.connectors.models import BasicExpertInfo
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.models import Document
from onyx.connectors.models import Section
from onyx.connectors.models import SlimDocument
from onyx.connectors.slack.utils import expert_info_from_slack_id
from onyx.connectors.slack.utils import get_message_link
from onyx.connectors.slack.utils import make_paginated_slack_api_call_w_retries
from onyx.connectors.slack.utils import make_slack_api_call_w_retries
from onyx.connectors.slack.utils import SlackTextCleaner
from onyx.utils.logger import setup_logger


logger = setup_logger()


ChannelType = dict[str, Any]
MessageType = dict[str, Any]
# list of messages in a thread
ThreadType = list[MessageType]


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
        id=f"{channel_id}__{thread[0]['ts']}",
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


def _get_all_docs(
    client: WebClient,
    channels: list[str] | None = None,
    channel_name_regex_enabled: bool = False,
    oldest: str | None = None,
    latest: str | None = None,
    msg_filter_func: Callable[[MessageType], bool] = default_msg_filter,
) -> Generator[Document, None, None]:
    """Get all documents in the workspace, channel by channel"""
    slack_cleaner = SlackTextCleaner(client=client)

    # Cache to prevent refetching via API since users
    user_cache: dict[str, BasicExpertInfo | None] = {}

    all_channels = get_channels(client)
    filtered_channels = filter_channels(
        all_channels, channels, channel_name_regex_enabled
    )

    for channel in filtered_channels:
        channel_docs = 0
        channel_message_batches = get_channel_messages(
            client=client, channel=channel, oldest=oldest, latest=latest
        )

        seen_thread_ts: set[str] = set()
        for message_batch in channel_message_batches:
            for message in message_batch:
                filtered_thread: ThreadType | None = None
                thread_ts = message.get("thread_ts")
                if thread_ts:
                    # skip threads we've already seen, since we've already processed all
                    # messages in that thread
                    if thread_ts in seen_thread_ts:
                        continue
                    seen_thread_ts.add(thread_ts)
                    thread = get_thread(
                        client=client, channel_id=channel["id"], thread_id=thread_ts
                    )
                    filtered_thread = [
                        message for message in thread if not msg_filter_func(message)
                    ]
                elif not msg_filter_func(message):
                    filtered_thread = [message]

                if filtered_thread:
                    channel_docs += 1
                    yield thread_to_doc(
                        channel=channel,
                        thread=filtered_thread,
                        slack_cleaner=slack_cleaner,
                        client=client,
                        user_cache=user_cache,
                    )

        logger.info(
            f"Pulled {channel_docs} documents from slack channel {channel['name']}"
        )


def _get_all_doc_ids(
    client: WebClient,
    channels: list[str] | None = None,
    channel_name_regex_enabled: bool = False,
    msg_filter_func: Callable[[MessageType], bool] = default_msg_filter,
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
                    id=f"{channel_id}__{message_ts}",
                    perm_sync_data={"channel_id": channel_id},
                )
            )

        yield channel_metadata_list


class SlackPollConnector(PollConnector, SlimConnector):
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

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        bot_token = credentials["slack_bot_token"]
        self.client = WebClient(token=bot_token)
        return None

    def retrieve_all_slim_documents(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
    ) -> GenerateSlimDocumentOutput:
        if self.client is None:
            raise ConnectorMissingCredentialError("Slack")

        return _get_all_doc_ids(
            client=self.client,
            channels=self.channels,
            channel_name_regex_enabled=self.channel_regex_enabled,
        )

    def poll_source(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> GenerateDocumentsOutput:
        if self.client is None:
            raise ConnectorMissingCredentialError("Slack")

        documents: list[Document] = []
        for document in _get_all_docs(
            client=self.client,
            channels=self.channels,
            channel_name_regex_enabled=self.channel_regex_enabled,
            # NOTE: need to impute to `None` instead of using 0.0, since Slack will
            # throw an error if we use 0.0 on an account without infinite data
            # retention
            oldest=str(start) if start else None,
            latest=str(end),
        ):
            documents.append(document)
            if len(documents) >= self.batch_size:
                yield documents
                documents = []

        if documents:
            yield documents


if __name__ == "__main__":
    import os
    import time

    slack_channel = os.environ.get("SLACK_CHANNEL")
    connector = SlackPollConnector(
        channels=[slack_channel] if slack_channel else None,
    )
    connector.load_credentials({"slack_bot_token": os.environ["SLACK_BOT_TOKEN"]})

    current = time.time()
    one_day_ago = current - 24 * 60 * 60  # 1 day

    document_batches = connector.poll_source(one_day_ago, current)

    print(next(document_batches))
