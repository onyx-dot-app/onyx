"""
Assumptions:
- The test users have already been created
- General is empty of messages
- In addition to the normal slack oauth permissions, the following scopes are needed:
    - channels:manage
    - groups:write
    - chat:write
    - chat:write.public
"""

from typing import Any
from typing import cast
from uuid import uuid4

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from onyx.connectors.slack.connector import default_msg_filter
from onyx.connectors.slack.connector import get_channel_messages
from onyx.connectors.slack.models import ChannelType
from onyx.connectors.slack.utils import make_paginated_slack_api_call


def _get_slack_channel_id(channel: ChannelType) -> str:
    if not (channel_id := channel.get("id")):
        raise ValueError("Channel ID is missing")
    return channel_id


def _get_non_general_channels(
    slack_client: WebClient,
    get_private: bool,
    get_public: bool,
    only_get_done: bool = False,
) -> list[ChannelType]:
    channel_types = []
    if get_private:
        channel_types.append("private_channel")
    if get_public:
        channel_types.append("public_channel")

    conversations: list[dict[str, Any]] = []
    for result in make_paginated_slack_api_call(
        slack_client.conversations_list,
        exclude_archived=False,
        types=channel_types,
    ):
        conversations.extend(result["channels"])

    filtered_conversations = []
    for conversation in conversations:
        if conversation.get("is_general", False):
            continue
        if only_get_done and "done" not in conversation.get("name", ""):
            continue
        filtered_conversations.append(conversation)
    return cast(list[ChannelType], filtered_conversations)


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
    try:
        slack_client.conversations_unarchive(channel=channel_id)
        channel["is_archived"] = False
    except Exception:
        # Channel is already unarchived
        pass


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
    message_to_delete: str | None = None,
) -> None:
    """deletes all messages from a channel if message_to_delete is None"""
    channel_id = _get_slack_channel_id(channel)
    for message_batch in get_channel_messages(slack_client, channel):
        for message in message_batch:
            if default_msg_filter(message):
                continue

            if message_to_delete and message.get("text") != message_to_delete:
                continue
            print(" removing message: ", message.get("text"))

            try:
                if not (ts := message.get("ts")):
                    raise ValueError("Message timestamp is missing")
                slack_client.chat_delete(channel=channel_id, ts=ts)
            except Exception as e:
                print(f"Error deleting message: {e}")
                print(message)


def _build_slack_channel_from_name(
    slack_client: WebClient,
    admin_user_id: str,
    suffix: str,
    is_private: bool,
    channel: ChannelType | None,
) -> ChannelType:
    base = "public_channel" if not is_private else "private_channel"
    channel_name = f"{base}-{suffix}"
    if channel:
        # If channel is provided, we rename it
        channel_id = _get_slack_channel_id(channel)
        channel_response = slack_client.conversations_rename(
            channel=channel_id,
            name=channel_name,
        )
    else:
        # Otherwise, we create a new channel
        channel_response = slack_client.conversations_create(
            name=channel_name,
            is_private=is_private,
        )

    try:
        slack_client.conversations_unarchive(channel=channel_response["channel"]["id"])
    except Exception:
        # Channel is already unarchived
        pass
    try:
        slack_client.conversations_invite(
            channel=channel_response["channel"]["id"],
            users=[admin_user_id],
        )
    except Exception:
        pass

    final_channel = channel_response["channel"] if channel_response else {}
    return cast(ChannelType, final_channel)


class SlackManager:
    @staticmethod
    def get_slack_client(token: str) -> WebClient:
        return WebClient(token=token)

    @staticmethod
    def get_and_provision_available_slack_channels(
        slack_client: WebClient, admin_user_id: str
    ) -> tuple[ChannelType, ChannelType, str]:
        run_id = str(uuid4())
        public_channels = _get_non_general_channels(
            slack_client, get_private=False, get_public=True, only_get_done=True
        )

        first_available_channel = (
            None if len(public_channels) < 1 else public_channels[0]
        )
        public_channel = _build_slack_channel_from_name(
            slack_client=slack_client,
            admin_user_id=admin_user_id,
            suffix=run_id,
            is_private=False,
            channel=first_available_channel,
        )
        _delete_slack_conversation_messages(
            slack_client=slack_client, channel=public_channel
        )

        private_channels = _get_non_general_channels(
            slack_client, get_private=True, get_public=False, only_get_done=True
        )
        second_available_channel = (
            None if len(private_channels) < 1 else private_channels[0]
        )
        private_channel = _build_slack_channel_from_name(
            slack_client=slack_client,
            admin_user_id=admin_user_id,
            suffix=run_id,
            is_private=True,
            channel=second_available_channel,
        )
        _delete_slack_conversation_messages(
            slack_client=slack_client, channel=private_channel
        )

        return public_channel, private_channel, run_id

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
    def cleanup_after_test(
        slack_client: WebClient,
        test_id: str,
    ) -> None:
        channel_types = ["private_channel", "public_channel"]
        channels: list[ChannelType] = []
        for result in make_paginated_slack_api_call(
            slack_client.conversations_list,
            exclude_archived=False,
            types=channel_types,
        ):
            channels.extend(result["channels"])

        for channel in channels:
            if test_id not in channel.get("name", ""):
                continue
            # "done" in the channel name indicates that this channel is free to be used for a new test
            new_name = f"done_{str(uuid4())}"
            try:
                slack_client.conversations_rename(channel=channel["id"], name=new_name)
            except SlackApiError as e:
                print(f"Error renaming channel {channel['id']}: {e}")
