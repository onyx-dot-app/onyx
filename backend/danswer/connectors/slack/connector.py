import re
from collections.abc import Callable
from collections.abc import Generator
from datetime import datetime
from datetime import timezone
from typing import Any
from typing import cast

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from slack_sdk.web import SlackResponse

from danswer.configs.app_configs import ENABLE_EXPENSIVE_EXPERT_CALLS
from danswer.configs.app_configs import INDEX_BATCH_SIZE
from danswer.configs.constants import DocumentSource
from danswer.connectors.cross_connector_utils.retry_wrapper import retry_builder
from danswer.connectors.interfaces import GenerateDocumentsOutput
from danswer.connectors.interfaces import PollConnector
from danswer.connectors.interfaces import SecondsSinceUnixEpoch
from danswer.connectors.models import BasicExpertInfo
from danswer.connectors.models import ConnectorMissingCredentialError
from danswer.connectors.models import Document
from danswer.connectors.models import Section
from danswer.connectors.slack.utils import expert_info_from_slack_id
from danswer.connectors.slack.utils import get_message_link
from danswer.connectors.slack.utils import make_slack_api_call_logged
from danswer.connectors.slack.utils import make_slack_api_call_paginated
from danswer.connectors.slack.utils import make_slack_api_rate_limited
from danswer.connectors.slack.utils import SlackTextCleaner
from danswer.utils.logger import setup_logger


logger = setup_logger()


ChannelType = dict[str, Any]
MessageType = dict[str, Any]
# list of messages in a thread
ThreadType = list[MessageType]

basic_retry_wrapper = retry_builder()


def _make_paginated_slack_api_call(
    call: Callable[..., SlackResponse], **kwargs: Any
) -> Generator[dict[str, Any], None, None]:
    return make_slack_api_call_paginated(
        basic_retry_wrapper(
            make_slack_api_rate_limited(make_slack_api_call_logged(call))
        )
    )(**kwargs)


def _make_slack_api_call(
    call: Callable[..., SlackResponse], **kwargs: Any
) -> SlackResponse:
    return basic_retry_wrapper(
        make_slack_api_rate_limited(make_slack_api_call_logged(call))
    )(**kwargs)


def get_channel_info(client: WebClient, channel_id: str) -> ChannelType:
    """Get information about a channel. Needed to convert channel ID to channel name"""
    return _make_slack_api_call(client.conversations_info, channel=channel_id)[0][
        "channel"
    ]


def _get_channels(
    client: WebClient,
    exclude_archived: bool,
    get_private: bool,
) -> list[ChannelType]:
    channels: list[dict[str, Any]] = []
    for result in _make_paginated_slack_api_call(
        client.conversations_list,
        exclude_archived=exclude_archived,
        # also get private channels the bot is added to
        types=["public_channel", "private_channel"]
        if get_private
        else ["public_channel"],
    ):
        channels.extend(result["channels"])

    return channels


def get_channels(
    client: WebClient,
    exclude_archived: bool = True,
) -> list[ChannelType]:
    """Get all channels in the workspace"""
    # try getting private channels as well at first
    try:
        return _get_channels(
            client=client, exclude_archived=exclude_archived, get_private=True
        )
    except SlackApiError as e:
        logger.info(f"Unable to fetch private channels due to - {e}")

    return _get_channels(
        client=client, exclude_archived=exclude_archived, get_private=False
    )


def get_channel_messages(
    client: WebClient,
    channel: dict[str, Any],
    oldest: str | None = None,
    latest: str | None = None,
) -> Generator[list[MessageType], None, None]:
    """Get all messages in a channel"""
    # join so that the bot can access messages
    if not channel["is_member"]:
        _make_slack_api_call(
            client.conversations_join,
            channel=channel["id"],
            is_private=channel["is_private"],
        )
        logger.info(f"Successfully joined '{channel['name']}'")

    for result in _make_paginated_slack_api_call(
        client.conversations_history,
        channel=channel["id"],
        oldest=oldest,
        latest=latest,
    ):
        yield cast(list[MessageType], result["messages"])


def get_thread(client: WebClient, channel_id: str, thread_id: str) -> ThreadType:
    """Get all messages in a thread"""
    threads: list[MessageType] = []
    for result in _make_paginated_slack_api_call(
        client.conversations_replies, channel=channel_id, ts=thread_id
    ):
        threads.extend(result["messages"])
    return threads


def get_latest_message_time(thread: ThreadType) -> datetime:
    max_ts = max([float(msg.get("ts", 0)) for msg in thread])
    return datetime.fromtimestamp(max_ts, tz=timezone.utc)


def thread_to_doc(
    workspace: str,
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

    doc_sem_id = f"{initial_sender_name} in #{channel['name']}: {snippet}"

    return Document(
        id=f"{channel_id}__{thread[0]['ts']}",
        sections=[
            Section(
                link=get_message_link(
                    event=m, workspace=workspace, channel_id=channel_id
                ),
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
}


def _default_msg_filter(message: MessageType) -> bool:
    # Don't keep messages from bots
    if message.get("bot_id") or message.get("app_id"):
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


def get_all_docs(
    client: WebClient,
    workspace: str,
    channels: list[str] | None = None,
    channel_name_regex_enabled: bool = False,
    oldest: str | None = None,
    latest: str | None = None,
    msg_filter_func: Callable[[MessageType], bool] = _default_msg_filter,
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
                        workspace=workspace,
                        channel=channel,
                        thread=filtered_thread,
                        slack_cleaner=slack_cleaner,
                        client=client,
                        user_cache=user_cache,
                    )

        logger.info(
            f"Pulled {channel_docs} documents from slack channel {channel['name']}"
        )


class SlackPollConnector(PollConnector):
    def __init__(
        self,
        workspace: str,
        channels: list[str] | None = None,
        # if specified, will treat the specified channel strings as
        # regexes, and will only index channels that fully match the regexes
        channel_regex_enabled: bool = False,
        batch_size: int = INDEX_BATCH_SIZE,
    ) -> None:
        self.workspace = workspace
        self.channels = channels
        self.channel_regex_enabled = channel_regex_enabled
        self.batch_size = batch_size
        self.client: WebClient | None = None

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        bot_token = credentials["slack_bot_token"]
        self.client = WebClient(token=bot_token)
        return None

    def poll_source(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> GenerateDocumentsOutput:
        if self.client is None:
            raise ConnectorMissingCredentialError("Slack")

        documents: list[Document] = []
        for document in get_all_docs(
            client=self.client,
            workspace=self.workspace,
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
        workspace=os.environ["SLACK_WORKSPACE"],
        channels=[slack_channel] if slack_channel else None,
    )
    connector.load_credentials({"slack_bot_token": os.environ["SLACK_BOT_TOKEN"]})

    current = time.time()
    one_day_ago = current - 24 * 60 * 60  # 1 day
    document_batches = connector.poll_source(one_day_ago, current)

    print(next(document_batches))
