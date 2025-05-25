"""
Assumptions:
- The test users have already been created
- General is empty of messages
- In addition to the normal slack oauth permissions, the following scopes are needed:
    - channels:manage
    - chat:write.public
    - channels:history
    - channels:write
    - chat:write
    - groups:history
    - groups:write
    - im:history
    - im:write
    - mpim:history
    - mpim:write
    - users:write
    - channels:read
    - groups:read
    - mpim:read
    - im:read
"""

import time
from typing import Any
from typing import Optional
from uuid import uuid4

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from onyx.connectors.slack.connector import default_msg_filter
from onyx.connectors.slack.connector import get_channel_messages
from onyx.connectors.slack.utils import make_paginated_slack_api_call_w_retries
from onyx.connectors.slack.utils import make_slack_api_call_w_retries
from onyx.utils.logger import setup_logger

logger = setup_logger()


def _get_slack_channel_id(channel: dict[str, Any]) -> str:
    if not (channel_id := channel.get("id")):
        raise ValueError("Channel ID is missing")
    return channel_id


def _get_non_general_channels(
    slack_client: WebClient,
    get_private: bool,
    get_public: bool,
    only_get_done: bool = False,
) -> list[dict[str, Any]]:
    channel_types = []
    if get_private:
        channel_types.append("private_channel")
    if get_public:
        channel_types.append("public_channel")

    conversations: list[dict[str, Any]] = []
    for result in make_paginated_slack_api_call_w_retries(
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
    return filtered_conversations


def _clear_slack_conversation_members(
    slack_client: WebClient,
    admin_user_id: str,
    channel: dict[str, Any],
) -> None:
    channel_id = _get_slack_channel_id(channel)
    member_ids: list[str] = []
    for result in make_paginated_slack_api_call_w_retries(
        slack_client.conversations_members,
        channel=channel_id,
    ):
        member_ids.extend(result["members"])

    for member_id in member_ids:
        if member_id == admin_user_id:
            continue
        try:
            slack_client.conversations_kick(channel=channel_id, user=member_id)
            logger.info(f"Kicked member {member_id} from channel {channel_id}")
        except Exception as e:
            if "cant_kick_self" in str(e):
                continue
            logger.error(
                f"Error kicking member {member_id} from channel {channel_id}: {e}"
            )
            logger.error(f"Failed member ID: {member_id}")
    try:
        slack_client.conversations_unarchive(channel=channel_id)
        logger.info(f"Unarchived channel {channel_id}")
        channel["is_archived"] = False
    except Exception as e:
        # Channel is already unarchived or another error occurred
        logger.warning(
            f"Could not unarchive channel {channel_id}, it might already be unarchived or another error occurred: {e}"
        )


def _add_slack_conversation_members(
    slack_client: WebClient, channel: dict[str, Any], member_ids: list[str]
) -> None:
    channel_id = _get_slack_channel_id(channel)
    for user_id in member_ids:
        try:
            slack_client.conversations_invite(channel=channel_id, users=user_id)
        except Exception as e:
            if "already_in_channel" in str(e):
                continue
            logger.error(f"Error inviting member: {e}")
            logger.error(user_id)


def _delete_slack_conversation_messages(
    slack_client: WebClient,
    channel: dict[str, Any],
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
            logger.info(f" removing message: {message.get('text')}")

            try:
                if not (ts := message.get("ts")):
                    raise ValueError("Message timestamp is missing")
                slack_client.chat_delete(channel=channel_id, ts=ts)
            except Exception as e:
                logger.error(f"Error deleting message: {e}")
                logger.error(message)


def _build_slack_channel_from_name(
    slack_client: WebClient,
    admin_user_id: str,
    suffix: str,
    is_private: bool,
    channel: dict[str, Any] | None,
) -> dict[str, Any]:
    base = "public_channel" if not is_private else "private_channel"
    channel_name = f"{base}-{suffix}"
    if channel:
        # If channel is provided, we rename it
        channel_id = _get_slack_channel_id(channel)
        channel_response = make_slack_api_call_w_retries(
            slack_client.conversations_rename,
            channel=channel_id,
            name=channel_name,
        )
    else:
        # Otherwise, we create a new channel
        channel_response = make_slack_api_call_w_retries(
            slack_client.conversations_create,
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
    return final_channel


class SlackManager:
    @staticmethod
    def get_slack_client(token: str) -> WebClient:
        return WebClient(token=token)

    @staticmethod
    def get_and_provision_available_slack_channels(
        slack_client: WebClient, admin_user_id: str
    ) -> tuple[dict[str, Any], dict[str, Any], str]:
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
        users_results = make_slack_api_call_w_retries(
            slack_client.users_list,
        )
        users: list[dict[str, Any]] = users_results.get("members", [])
        user_email_id_map = {}
        for user in users:
            if not (email := user.get("profile", {}).get("email")):
                continue
            if not (user_id := user.get("id")):
                raise ValueError("User ID is missing")
            user_email_id_map[email] = user_id
        return user_email_id_map

    @staticmethod
    def get_client_user_and_bot_ids(
        slack_client: WebClient,
    ) -> tuple[str, str]:
        """
        Fetches the user ID and bot ID of the authenticated user.
        """
        logger.info("Attempting to find onyxbot user ID and bot ID.")
        try:
            auth_response = make_slack_api_call_w_retries(
                slack_client.auth_test,
            )
            id = auth_response.get("user_id")
            bot_id = auth_response.get("bot_id")
            return id, bot_id
        except SlackApiError as e:
            logger.error(f"Error fetching auth test: {e}")
            raise

    @staticmethod
    def set_channel_members(
        slack_client: WebClient,
        admin_user_id: str,
        channel: dict[str, Any],
        user_ids: list[str],
    ) -> None:
        """
        Sets the members of a Slack channel by first removing all members
        and then adding the specified members.
        """
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
        slack_client: WebClient, channel: dict[str, Any], message: str
    ) -> Optional[str]:
        """Posts a message to a channel and returns the message timestamp (ts)."""
        try:
            channel_id = _get_slack_channel_id(channel)
            response = make_slack_api_call_w_retries(
                slack_client.chat_postMessage,
                channel=channel_id,
                text=message,
            )
            # Return the timestamp of the posted message
            return response.get("ts")
        except SlackApiError as e:
            logger.error(f"Error posting message to channel {channel_id}: {e}")
            raise
        except Exception as e:
            logger.error(f"An unexpected error occurred: {e}")
            raise

    @staticmethod
    def poll_for_reply(
        slack_client: WebClient,
        channel: dict[str, Any],
        original_message_ts: str,
        timeout_seconds: int,
    ) -> Optional[dict[str, Any]]:
        """
        Polls a channel for a reply to a specific message for a given duration.
        """
        channel_id = _get_slack_channel_id(channel)
        start_time = time.time()
        logger.info(
            f"Polling channel {channel_id} for reply to message {original_message_ts} for {timeout_seconds} seconds."
        )

        while time.time() - start_time < timeout_seconds:
            logger.info(
                f"""Polling channel {channel_id} | elapsed time: {time.time() - start_time:.2f}
                seconds out of {timeout_seconds} seconds."""
            )
            try:
                # Fetch recent messages in the thread
                result = make_slack_api_call_w_retries(
                    slack_client.conversations_replies,
                    channel=channel_id,
                    ts=original_message_ts,
                    limit=20,
                )
                messages = result.get("messages", [])

                # The first message is the original message, skip it.
                for message in messages[1:]:
                    # Check if it's a reply in the correct thread
                    if message.get("thread_ts") == original_message_ts:
                        logger.info(f"Found reply: {message.get('text')}")
                        return message

            except SlackApiError as e:
                logger.error(f"Error fetching replies from channel {channel_id}: {e}")
                raise
            except Exception as e:
                logger.error(f"An unexpected error occurred during polling: {e}")
                raise

            # Wait a bit before the next poll
            time.sleep(1)

        logger.warning(
            f"Timeout reached. No reply found for message {original_message_ts} in channel {channel_id}."
        )
        return None  # Timeout reached without finding a reply

    @staticmethod
    def remove_message_from_channel(
        slack_client: WebClient, channel: dict[str, Any], message: str
    ) -> None:
        """Removes a specific message from the given channel."""
        _delete_slack_conversation_messages(
            slack_client=slack_client, channel=channel, message_to_delete=message
        )

    @staticmethod
    def cleanup_after_test(
        slack_client: WebClient,
        test_id: str,
    ) -> None:
        """
        Cleans up Slack channels after a test by renaming channels that contain the test ID.
        """
        channel_types = ["private_channel", "public_channel"]
        channels: list[dict[str, Any]] = []
        for result in make_paginated_slack_api_call_w_retries(
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
                logger.error(f"Error renaming channel {channel['id']}: {e}")

    @staticmethod
    def get_dm_channel(
        slack_client: WebClient,
        user_id: str,
    ) -> dict[str, Any]:
        try:
            response = make_slack_api_call_w_retries(
                slack_client.conversations_open,
                users=user_id,
            )
            channel = response["channel"]
            return channel
        except SlackApiError as e:
            logger.error(f"Error opening DM channel with user {user_id}: {e}")
            raise

    @staticmethod
    def delete_all_messages_and_threads(
        slack_user_client: WebClient,
        slack_bot_client: WebClient,
        channel: dict[str, Any],
    ) -> None:
        """
        Deletes all messages and their thread replies in the specified channel.
        """
        try:
            logger.info(f"Deleting all messages and threads in channel {channel}")
            user_bot_id, _ = SlackManager.get_client_user_and_bot_ids(slack_user_client)
            # Fetch all messages in the channel
            channel_id = _get_slack_channel_id(channel)
            for message_batch in get_channel_messages(slack_user_client, channel):
                for message in message_batch:
                    user_id = message.get("user")
                    if user_id == "USLACKBOT":
                        continue
                    ts = message.get("ts")
                    if not ts:
                        continue
                    logger.info(f"Deleting message: {message}")
                    # Delete all replies in the thread, if any
                    if message.get("reply_count", 0) > 0:
                        try:
                            replies_result = make_slack_api_call_w_retries(
                                slack_user_client.conversations_replies,
                                channel=channel_id,
                                ts=ts,
                                limit=100,
                            )
                            replies = replies_result.get("messages", [])[
                                1:
                            ]  # skip parent
                            for reply in replies:
                                logger.info(f"Deleting thread reply: {reply}")
                                user_id = reply.get("user")
                                if user_id == "USLACKBOT":
                                    continue
                                client = (
                                    slack_user_client
                                    if user_id == user_bot_id
                                    else slack_bot_client
                                )
                                reply_ts = reply.get("ts")
                                if reply_ts:
                                    try:
                                        make_slack_api_call_w_retries(
                                            client.chat_delete,
                                            channel=channel_id,
                                            ts=reply_ts,
                                        )
                                        logger.info("Deleted thread reply")
                                    except Exception as e:
                                        logger.error(
                                            f"Error deleting thread reply: {e}"
                                        )
                                        raise
                        except Exception as e:
                            logger.error(f"Error fetching thread replies: {e}")

                    # Delete the parent/original message
                    try:
                        logger.info(f"Deleting message: {message}")
                        user_id = message.get("user")
                        client = (
                            slack_user_client
                            if user_id == user_bot_id
                            else slack_bot_client
                        )
                        make_slack_api_call_w_retries(
                            client.chat_delete,
                            channel=channel_id,
                            ts=ts,
                        )
                        logger.info(f"Deleted message: {message}")
                    except Exception as e:
                        logger.error(f"Error deleting message: {e}")

        except Exception as e:
            logger.error(
                f"Error deleting all messages and threads in channel {channel_id}: {e}"
            )
            raise

    @staticmethod
    def get_full_channel_info(
        slack_client: WebClient,
        channel: dict[str, Any],
    ) -> dict[str, Any]:
        """Fetches full channel information for the specified channel."""
        logger.info(f"Fetching full channel info for channel {channel}")
        channel_id = _get_slack_channel_id(channel)
        try:
            channel_info = make_slack_api_call_w_retries(
                slack_client.conversations_info,
                channel=channel_id,
            )
            return channel_info.get("channel", {})
        except SlackApiError as e:
            logger.error(f"Error fetching channel info for {channel_id}: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error fetching channel info: {e}")
            raise

    @staticmethod
    def create_slack_channel(
        slack_client: WebClient,
        channel_name: str,
        is_private: bool = False,
    ) -> dict[str, Any]:
        """
        Creates a new Slack channel (public or private) and returns its details.
        """
        logger.info(f"Creating Slack channel {channel_name} (private: {is_private})")
        if not channel_name:
            raise ValueError("Channel name is required")
        try:
            # Check if channel already exists
            for result in make_paginated_slack_api_call_w_retries(
                slack_client.conversations_list,
                exclude_archived=False,
                types=["public_channel", "private_channel"],
            ):
                for channel in result["channels"]:
                    if channel.get("name") == channel_name:
                        logger.info(
                            f"Channel {channel_name} already exists with ID: {channel['id']}"
                        )
                        return channel

            # Create a new channel if it doesn't exist
            channel_response = make_slack_api_call_w_retries(
                slack_client.conversations_create,
                name=channel_name,
                is_private=is_private,
            )
            channel_id = channel_response["channel"]["id"]
            logger.info(f"Channel created with ID: {channel_id}")
            return channel_response["channel"]
        except SlackApiError as e:
            logger.error(f"Error creating channel {channel_name}: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error creating channel {channel_name}: {e}")
            raise

    @staticmethod
    def create_user_group(
        slack_client: WebClient,
        group_name: str,
    ) -> dict[str, Any]:
        """
        Checks if a user group exists by name. If it does, returns it.
        Otherwise, creates a new user group.
        """
        if not group_name:
            raise ValueError("Group name is required")
        try:
            # Check if group already exists
            response = make_slack_api_call_w_retries(
                slack_client.usergroups_list,
            )
            for group in response.get("usergroups", []):
                if group.get("name") == group_name:
                    logger.info(
                        f"User group {group_name} already exists with ID: {group['id']}"
                    )
                    return group

            # Create a new user group if not found
            response = make_slack_api_call_w_retries(
                slack_client.usergroups_create, name=group_name
            )
            usergroup_id = response["usergroup"]["id"]
            logger.info(f"User group created with ID: {usergroup_id}")
            return response["usergroup"]
        except SlackApiError as e:
            logger.error(f"Error creating or finding user group {group_name}: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error in create_user_group for {group_name}: {e}")
            raise

    @staticmethod
    def set_user_group_members(
        slack_client: WebClient,
        user_group_id: str,
        user_ids: list[str],
    ) -> None:
        """
        Removes all users from the user group and adds the specified users.
        """
        logger.info(f"Setting members of user group {user_group_id} to: {user_ids}")
        try:
            # Add specified users
            if user_ids:
                make_slack_api_call_w_retries(
                    slack_client.usergroups_users_update,
                    usergroup=user_group_id,
                    users=user_ids,
                )
                logger.info(f"Added users to user group {user_group_id}")
        except SlackApiError as e:
            logger.error(f"Error resetting members for user group {user_group_id}: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error resetting user group {user_group_id}: {e}")
            raise
