import re
import time
from collections.abc import Callable
from collections.abc import Generator
from functools import lru_cache
from typing import Any
from typing import cast

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from slack_sdk.web import SlackResponse

from onyx.connectors.models import BasicExpertInfo
from onyx.connectors.slack.models import MessageType
from onyx.utils.logger import setup_logger
from onyx.utils.retry_after import parse_retry_after_seconds

logger = setup_logger()

# number of messages we request per page when fetching paginated slack messages
_SLACK_LIMIT = 900
_SLACK_RATE_LIMIT_MAX_RETRIES = 7
_SLACK_RATE_LIMIT_DEFAULT_RETRY_AFTER_SECONDS = 5.0
_SLACK_RATE_LIMIT_ERRORS = {"ratelimited", "rate_limited"}

# used to serialize access to the retry TTL
ONYX_SLACK_LOCK_TTL = 1800  # how long the lock is allowed to idle before it expires
ONYX_SLACK_LOCK_BLOCKING_TIMEOUT = 60  # how long to wait for the lock per wait attempt
ONYX_SLACK_LOCK_TOTAL_BLOCKING_TIMEOUT = 3600  # how long to wait for the lock in total


@lru_cache()
def get_base_url(token: str) -> str:
    """Retrieve and cache the base URL of the Slack workspace based on the client token."""
    client = WebClient(token=token)
    return client.auth_test()["url"]


def fetch_team_user_emails(
    slack_client: WebClient,
    team_ids: list[str],
) -> dict[str, set[str]]:
    """Per-workspace user email sets. Used to scope public-channel access on
    Enterprise Grid so users from one workspace can't see another workspace's
    public channels."""
    result: dict[str, set[str]] = {}
    for tid in team_ids:
        emails: set[str] = set()
        for user_info in make_paginated_slack_api_call(
            slack_client.users_list, team_id=tid
        ):
            for user in user_info.get("members", []):
                email = user.get("profile", {}).get("email")
                if email:
                    emails.add(email)
        result[tid] = emails
    return result


def get_message_link(
    event: MessageType,
    client: WebClient,
    channel_id: str,
    team_id: str | None = None,
    team_id_to_url: dict[str, str] | None = None,
) -> str:
    message_ts = event["ts"]
    message_ts_without_dot = message_ts.replace(".", "")
    thread_ts = event.get("thread_ts")

    base_url: str | None = None
    if team_id and team_id_to_url is not None:
        base_url = team_id_to_url.get(team_id)
    if not base_url:
        base_url = get_base_url(client.token)

    link = f"{base_url.rstrip('/')}/archives/{channel_id}/p{message_ts_without_dot}" + (
        f"?thread_ts={thread_ts}" if thread_ts else ""
    )
    return link


def make_slack_api_call(
    call: Callable[..., SlackResponse], **kwargs: Any
) -> SlackResponse:
    return call(**kwargs)


def make_paginated_slack_api_call(
    call: Callable[..., SlackResponse], **kwargs: Any
) -> Generator[dict[str, Any], None, None]:
    """Wraps calls to slack API so that they automatically handle pagination"""

    cursor: str | None = None
    has_more = True
    while has_more:
        for retry_num in range(_SLACK_RATE_LIMIT_MAX_RETRIES + 1):
            try:
                response = call(cursor=cursor, limit=_SLACK_LIMIT, **kwargs).validate()
                response_dict = cast(dict[str, Any], response)
                yield response_dict
                cursor = cast(
                    dict[str, Any], response_dict.get("response_metadata", {})
                ).get("next_cursor", "")
                has_more = bool(cursor)
                break
            except SlackApiError as e:
                slack_response = e.response
                error_code = (
                    slack_response.get("error") if slack_response is not None else None
                )

                if (
                    slack_response is None
                    or getattr(slack_response, "status_code", None) == 429
                    or error_code not in _SLACK_RATE_LIMIT_ERRORS
                    or retry_num >= _SLACK_RATE_LIMIT_MAX_RETRIES
                ):
                    raise

                retry_after_header_value = None
                for header_name, header_value in getattr(
                    slack_response, "headers", {}
                ).items():
                    if header_name.lower() != "retry-after":
                        continue
                    if isinstance(header_value, list):
                        retry_after_header_value = (
                            header_value[0] if header_value else None
                        )
                    else:
                        retry_after_header_value = header_value
                    break

                retry_after = parse_retry_after_seconds(
                    str(retry_after_header_value)
                    if retry_after_header_value is not None
                    else None
                )
                if retry_after is None:
                    retry_after = _SLACK_RATE_LIMIT_DEFAULT_RETRY_AFTER_SECONDS

                logger.warning(
                    "Slack API returned %s for %s; sleeping %.2fs before retry %s/%s.",
                    error_code,
                    getattr(call, "__name__", repr(call)),
                    retry_after,
                    retry_num + 1,
                    _SLACK_RATE_LIMIT_MAX_RETRIES,
                )
                time.sleep(retry_after)


def expert_info_from_slack_id(
    user_id: str | None,
    client: WebClient,
    user_cache: dict[str, BasicExpertInfo | None],
) -> BasicExpertInfo | None:
    if not user_id:
        return None

    if user_id in user_cache:
        return user_cache[user_id]

    response = client.users_info(user=user_id)

    if not response["ok"]:
        user_cache[user_id] = None
        return None

    user: dict = cast(dict[Any, dict], response.data).get("user", {})
    profile = user.get("profile", {})

    expert = BasicExpertInfo(
        display_name=user.get("real_name") or profile.get("display_name"),
        first_name=profile.get("first_name"),
        last_name=profile.get("last_name"),
        email=profile.get("email"),
    )

    user_cache[user_id] = expert

    return expert


class SlackTextCleaner:
    """Utility class to replace user IDs with usernames in a message.
    Handles caching, so the same request is not made multiple times
    for the same user ID"""

    def __init__(self, client: WebClient) -> None:
        self._client = client
        self._id_to_name_map: dict[str, str] = {}

    def _get_slack_name(self, user_id: str) -> str:
        if user_id not in self._id_to_name_map:
            try:
                response = self._client.users_info(user=user_id)
                # prefer display name if set, since that is what is shown in Slack
                self._id_to_name_map[user_id] = (
                    response["user"]["profile"]["display_name"]
                    or response["user"]["profile"]["real_name"]
                )
            except SlackApiError as e:
                # Common per-message condition: user was deleted, workspace
                # migrated, bot lacks users:read, etc. Cache the raw id as a
                # fallback so we don't re-hit the API for the same bad id on
                # every message, and keep the event out of Sentry — the
                # message indexing path continues with the id in place of
                # the display name (ONYX-BACKEND-H6FN).
                logger.warning(
                    "Error fetching data for user %s: %s", user_id, e.response["error"]
                )
                self._id_to_name_map[user_id] = user_id

        return self._id_to_name_map[user_id]

    def _replace_user_ids_with_names(self, message: str) -> str:
        # Find user IDs in the message
        user_ids = re.findall("<@(.*?)>", message)

        # Iterate over each user ID found
        for user_id in user_ids:
            try:
                if user_id in self._id_to_name_map:
                    user_name = self._id_to_name_map[user_id]
                else:
                    user_name = self._get_slack_name(user_id)

                # Replace the user ID with the username in the message
                message = message.replace(f"<@{user_id}>", f"@{user_name}")
            except Exception as e:
                # _get_slack_name no longer raises on SlackApiError, so this
                # only fires on unexpected errors (e.g. malformed response);
                # still defensive, but not actionable per-message — warn.
                logger.warning(
                    "Unable to replace user ID with username for user_id '%s': %s",
                    user_id,
                    e,
                )

        return message

    def index_clean(self, message: str) -> str:
        """During indexing, replace pattern sets that may cause confusion to the model
        Some special patterns are left in as they can provide information
        ie. links that contain format text|link, both the text and the link may be informative
        """
        message = self._replace_user_ids_with_names(message)
        message = self.replace_tags_basic(message)
        message = self.replace_channels_basic(message)
        message = self.replace_special_mentions(message)
        message = self.replace_special_catchall(message)
        return message

    @staticmethod
    def replace_tags_basic(message: str) -> str:
        """Simply replaces all tags with `@<USER_ID>` in order to prevent us from
        tagging users in Slack when we don't want to"""
        # Find user IDs in the message
        user_ids = re.findall("<@(.*?)>", message)
        for user_id in user_ids:
            message = message.replace(f"<@{user_id}>", f"@{user_id}")
        return message

    @staticmethod
    def replace_channels_basic(message: str) -> str:
        """Simply replaces all channel mentions with `#<CHANNEL_ID>` in order
        to make a message work as part of a link"""
        # Find user IDs in the message
        channel_matches = re.findall(r"<#(.*?)\|(.*?)>", message)
        for channel_id, channel_name in channel_matches:
            message = message.replace(
                f"<#{channel_id}|{channel_name}>", f"#{channel_name}"
            )
        return message

    @staticmethod
    def replace_special_mentions(message: str) -> str:
        """Simply replaces @channel, @here, and @everyone so we don't tag
        a bunch of people in Slack when we don't want to"""
        # Find user IDs in the message
        message = message.replace("<!channel>", "@channel")
        message = message.replace("<!here>", "@here")
        message = message.replace("<!everyone>", "@everyone")
        return message

    @staticmethod
    def replace_special_catchall(message: str) -> str:
        """Replaces pattern of <!something|another-thing> with another-thing
        This is added for <!subteam^TEAM-ID|@team-name> but may match other cases as well
        """

        pattern = r"<!([^|]+)\|([^>]+)>"
        return re.sub(pattern, r"\2", message)

    @staticmethod
    def add_zero_width_whitespace_after_tag(message: str) -> str:
        """Add a 0 width whitespace after every @"""
        return message.replace("@", "@\u200b")
