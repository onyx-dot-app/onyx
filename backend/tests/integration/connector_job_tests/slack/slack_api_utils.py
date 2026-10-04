"""
Assumptions:
- The test users have already been created
- In addition to the normal slack oauth permissions, the following scopes are needed:
    - channels:manage
    - groups:write
    - chat:write
"""

import time
from collections.abc import Callable, Generator
from enum import StrEnum
from typing import Any, cast

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from slack_sdk.http_retry import RateLimitErrorRetryHandler
from slack_sdk.web import SlackResponse

from onyx.connectors.slack.models import ChannelType, MessageType

_SLACK_LIMIT = 900
# Concurrent CI runs share each workspace's rate limits, so calls wait out 429s instead of failing the test.
_RATE_LIMIT_MAX_RETRIES = 7

# Names used by the per-run channels that tests created before the channel pool.
_LEGACY_TEST_CHANNEL_PREFIXES = ("public_channel-", "private_channel-")
# Older than any test run can last, so a sweep never archives a channel in use.
_SWEEP_MIN_CHANNEL_AGE_SECONDS = 60 * 60
# conversations.archive allows about 20 calls per minute.
_SWEEP_MAX_CHANNELS = 100


class SlackApiErrorCode(StrEnum):
    ALREADY_ARCHIVED = "already_archived"
    CHANNEL_NOT_FOUND = "channel_not_found"
    MESSAGE_NOT_FOUND = "message_not_found"
    NAME_TAKEN = "name_taken"


def slack_error_code(error: SlackApiError) -> str:
    return cast(str, error.response.get("error", ""))


def make_paginated_slack_api_call(
    call: Callable[..., SlackResponse], **kwargs: Any
) -> Generator[dict[str, Any], None, None]:
    """Cursor pagination over the test-management client.

    Test setup drives its own admin ``WebClient`` (kicks members, deletes
    messages), so it keeps a local paginator instead of going through the
    connector's source-operations gateway.
    """
    cursor: str | None = None
    has_more = True
    while has_more:
        response = call(cursor=cursor, limit=_SLACK_LIMIT, **kwargs)
        yield cast(dict[str, Any], response.validate())
        cursor = cast(dict[str, Any], response.get("response_metadata", {})).get(
            "next_cursor", ""
        )
        has_more = bool(cursor)


def get_channel_messages(
    slack_client: WebClient, channel: ChannelType
) -> Generator[list[MessageType], None, None]:
    """Yields message batches for a channel via the test-management client."""
    for result in make_paginated_slack_api_call(
        slack_client.conversations_history,
        channel=channel["id"],
    ):
        yield cast(list[MessageType], result["messages"])


def _get_slack_channel_id(channel: ChannelType) -> str:
    if not (channel_id := channel.get("id")):
        raise ValueError("Channel ID is missing")
    return channel_id


def _clear_slack_conversation_members(
    slack_client: WebClient,
    admin_user_id: str,
    channel: ChannelType,
) -> None:
    channel_id = _get_slack_channel_id(channel)
    member_ids: list[str] = []
    for result in make_paginated_slack_api_call(
        slack_client.conversations_members,
        channel=channel_id,
    ):
        member_ids.extend(result["members"])

    for member_id in member_ids:
        if member_id == admin_user_id:
            continue
        try:
            slack_client.conversations_kick(channel=channel_id, user=member_id)
            print(f"Kicked member: {member_id}")
        except Exception as e:
            if "cant_kick_self" in str(e):
                continue
            print(f"Error kicking member: {e}")
            print(member_id)


def _add_slack_conversation_members(
    slack_client: WebClient, channel: ChannelType, member_ids: list[str]
) -> None:
    channel_id = _get_slack_channel_id(channel)
    for user_id in member_ids:
        try:
            slack_client.conversations_invite(channel=channel_id, users=user_id)
        except Exception as e:
            if "already_in_channel" in str(e):
                continue
            print(f"Error inviting member: {e}")
            print(user_id)


def _delete_slack_conversation_messages(
    slack_client: WebClient,
    channel: ChannelType,
    message_to_delete: str,
) -> None:
    channel_id = _get_slack_channel_id(channel)
    for message_batch in get_channel_messages(slack_client, channel):
        for message in message_batch:
            if message.get("text") != message_to_delete:
                continue
            print(" removing message: ", message.get("text"))

            try:
                if not (ts := message.get("ts")):
                    raise ValueError("Message timestamp is missing")
                slack_client.chat_delete(channel=channel_id, ts=ts)
            except Exception as e:
                print(f"Error deleting message: {e}")
                print(message)


def _delete_all_slack_conversation_messages(
    slack_client: WebClient, channel: ChannelType
) -> None:
    """Deletes plain messages; system messages (joins, renames) cannot be deleted."""
    channel_id = _get_slack_channel_id(channel)
    timestamps = [
        ts
        for message_batch in get_channel_messages(slack_client, channel)
        for message in message_batch
        if not message.get("subtype") and (ts := message.get("ts"))
    ]
    for ts in timestamps:
        try:
            slack_client.chat_delete(channel=channel_id, ts=ts)
        except SlackApiError as e:
            print(f"Error deleting message {ts} in {channel_id}: {e}")


def create_slack_channel(
    slack_client: WebClient, admin_user_id: str, name: str, is_private: bool
) -> ChannelType:
    response: SlackResponse = slack_client.conversations_create(
        name=name, is_private=is_private
    )
    channel: ChannelType = cast(ChannelType, response["channel"])
    _add_slack_conversation_members(
        slack_client=slack_client, channel=channel, member_ids=[admin_user_id]
    )
    return channel


class SlackManager:
    @staticmethod
    def get_slack_client(token: str) -> WebClient:
        client: WebClient = WebClient(token=token)
        client.retry_handlers.append(
            RateLimitErrorRetryHandler(max_retry_count=_RATE_LIMIT_MAX_RETRIES)
        )
        return client

    @staticmethod
    def list_active_channels(slack_client: WebClient) -> list[ChannelType]:
        """Unarchived public channels plus the private channels the bot is in."""
        channels: list[ChannelType] = []
        for result in make_paginated_slack_api_call(
            slack_client.conversations_list,
            exclude_archived=True,
            types="public_channel,private_channel",
        ):
            channels.extend(cast(list[ChannelType], result["channels"]))
        return channels

    @staticmethod
    def reset_channel(
        slack_client: WebClient, admin_user_id: str, channel: ChannelType
    ) -> None:
        """Returns a reused channel to the state of a new one: no messages, only the admin."""
        _delete_all_slack_conversation_messages(slack_client, channel)
        SlackManager.set_channel_members(
            slack_client=slack_client,
            admin_user_id=admin_user_id,
            channel=channel,
            user_ids=[admin_user_id],
        )

    @staticmethod
    def sweep_leaked_test_channels(bot_token: str) -> None:
        """Archives old per-run test channels. Safe to run concurrently; never raises."""
        try:
            slack_client = SlackManager.get_slack_client(bot_token)
            cutoff = time.time() - _SWEEP_MIN_CHANNEL_AGE_SECONDS
            leaked = [
                channel
                for channel in SlackManager.list_active_channels(slack_client)
                if channel["name"].startswith(_LEGACY_TEST_CHANNEL_PREFIXES)
                and channel["created"] < cutoff
            ][:_SWEEP_MAX_CHANNELS]
            print(f"Sweeping {len(leaked)} leaked Slack test channels")
            SlackManager.archive_channels(slack_client=slack_client, channels=leaked)
        except Exception as e:
            print(f"Error sweeping leaked Slack test channels: {e}")

    @staticmethod
    def build_slack_user_email_id_map(slack_client: WebClient) -> dict[str, str]:
        users: list[dict[str, Any]] = []

        for users_results in make_paginated_slack_api_call(
            slack_client.users_list,
        ):
            users.extend(users_results.get("members", []))

        user_email_id_map = {}
        for user in users:
            if not (email := user.get("profile", {}).get("email")):
                continue
            if not (user_id := user.get("id")):
                raise ValueError("User ID is missing")
            user_email_id_map[email] = user_id
        return user_email_id_map

    @staticmethod
    def set_channel_members(
        slack_client: WebClient,
        admin_user_id: str,
        channel: ChannelType,
        user_ids: list[str],
    ) -> None:
        _clear_slack_conversation_members(
            slack_client=slack_client,
            channel=channel,
            admin_user_id=admin_user_id,
        )
        _add_slack_conversation_members(
            slack_client=slack_client, channel=channel, member_ids=user_ids
        )

    @staticmethod
    def add_message_to_channel(
        slack_client: WebClient, channel: ChannelType, message: str
    ) -> None:
        channel_id = _get_slack_channel_id(channel)
        slack_client.chat_postMessage(
            channel=channel_id,
            text=message,
        )

    @staticmethod
    def remove_message_from_channel(
        slack_client: WebClient, channel: ChannelType, message: str
    ) -> None:
        _delete_slack_conversation_messages(
            slack_client=slack_client, channel=channel, message_to_delete=message
        )

    @staticmethod
    def archive_channels(slack_client: WebClient, channels: list[ChannelType]) -> None:
        """Logs failures instead of raising so cleanup never fails a test.

        A concurrent sweep may archive the same channel first, so that error is ignored.
        """
        for channel in channels:
            channel_id: str = _get_slack_channel_id(channel)
            try:
                slack_client.conversations_archive(channel=channel_id)
            except SlackApiError as e:
                if slack_error_code(e) in (
                    SlackApiErrorCode.ALREADY_ARCHIVED,
                    SlackApiErrorCode.CHANNEL_NOT_FOUND,
                ):
                    continue
                print(f"Error archiving channel {channel_id}: {e}")
            except Exception as e:
                print(f"Error archiving channel {channel_id}: {e}")
