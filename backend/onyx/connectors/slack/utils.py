import re
from collections.abc import Callable
from functools import lru_cache

from onyx.connectors.models import BasicExpertInfo
from onyx.connectors.slack.models import MessageType
from onyx.connectors.slack.source_operations import (
    SlackApiError,
    SlackSourceOperations,
    SlackUserInfoResponse,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Resolves one Slack user id to a validated ``users.info`` payload. The
# gateway's ``fetch_user_info`` operation satisfies this; onyxbot (which keeps
# its own bot-app WebClient and no gateway) passes an adapter over that client.
FetchUserInfo = Callable[[str], SlackUserInfoResponse]

# Skips an @ preceded by a word character, where a zero-width space would
# split an address rather than defang a mention
_MENTION_AT_PATTERN = re.compile(r"(?<!\w)@")

# Regions needing special handling: only a link destination and code are exempt
# from defanging, a link label is not
_DEFANG_EXEMPT_REGION_PATTERN = re.compile(
    r"<(?P<url>(?:https?://|mailto:)[^|<>]+)(?:\|(?P<label>[^<>]*))?>"
    r"|(?P<code>```[\s\S]*?```|`[^`\n]*`)"
)
# Optional label group, so the labelled form resolves to its label not the raw ID
_SUBTEAM_MENTION_PATTERN = re.compile(
    r"<!subteam\^(?P<id>[^<>|]+)(?:\|(?P<label>[^<>]*))?>"
)

# Message markup patterns. No group can cross a "<" or ">", so each match
# attempt stops at the next delimiter and matching stays linear in the length.
_TAG_PATTERN = re.compile(r"<@([^<>]*)>")
_CHANNEL_MENTION_PATTERN = re.compile(r"<#([^|<>]*)\|([^<>]*)>")
_SPECIAL_CATCHALL_PATTERN = re.compile(r"<!([^|<>]+)\|([^<>]+)>")
_SLACK_USER_ID_PATTERN = re.compile(r"[UW][A-Z0-9]{2,}")
# Bounds the users.info calls that one message can cause
_MAX_USER_LOOKUPS_PER_MESSAGE = 50


def _defang_mentions(text: str) -> str:
    return _MENTION_AT_PATTERN.sub("@​", text)


@lru_cache()
def get_base_url(slack_client: SlackSourceOperations) -> str:
    """Retrieve and cache the base URL of the Slack workspace for a gateway.

    Cached per gateway instance (one credential each), replacing the old
    per-token cache.
    """
    url = slack_client.check_auth().url
    if not url:
        raise RuntimeError("auth.test response contained no workspace url.")
    return url


def fetch_team_user_emails(
    slack_client: SlackSourceOperations,
    team_ids: list[str],
) -> dict[str, set[str]]:
    """Per-workspace user email sets. Used to scope public-channel access on
    Enterprise Grid so users from one workspace can't see another workspace's
    public channels."""
    result: dict[str, set[str]] = {}
    for tid in team_ids:
        emails: set[str] = set()
        for user_info in slack_client.list_users(team_id=tid):
            for user in user_info.members:
                email = user.get("profile", {}).get("email")
                if email:
                    emails.add(email)
        result[tid] = emails
    return result


def get_message_link(
    event: MessageType,
    slack_client: SlackSourceOperations,
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
        base_url = get_base_url(slack_client)

    link = f"{base_url.rstrip('/')}/archives/{channel_id}/p{message_ts_without_dot}" + (
        f"?thread_ts={thread_ts}" if thread_ts else ""
    )
    return link


def expert_info_from_slack_id(
    user_id: str | None,
    fetch_user_info: FetchUserInfo,
    user_cache: dict[str, BasicExpertInfo | None],
) -> BasicExpertInfo | None:
    if not user_id:
        return None

    if user_id in user_cache:
        return user_cache[user_id]

    response = fetch_user_info(user_id)

    if not response.ok:
        user_cache[user_id] = None
        return None

    user = response.user
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

    def __init__(self, fetch_user_info: FetchUserInfo) -> None:
        self._fetch_user_info = fetch_user_info
        self._id_to_name_map: dict[str, str] = {}

    def _get_slack_name(self, user_id: str) -> str:
        if user_id not in self._id_to_name_map:
            try:
                response = self._fetch_user_info(user_id)
                # prefer display name if set, since that is what is shown in Slack
                self._id_to_name_map[user_id] = (
                    response.user["profile"]["display_name"]
                    or response.user["profile"]["real_name"]
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
        lookups = 0

        def _replace(match: re.Match[str]) -> str:
            nonlocal lookups
            user_id = match.group(1)
            if user_id not in self._id_to_name_map:
                if (
                    not _SLACK_USER_ID_PATTERN.fullmatch(user_id)
                    or lookups >= _MAX_USER_LOOKUPS_PER_MESSAGE
                ):
                    # replace_tags_basic handles the tag
                    return match.group(0)
                lookups += 1
            try:
                return f"@{self._get_slack_name(user_id)}"
            except Exception as e:
                # _get_slack_name no longer raises on SlackApiError, so this
                # only fires on unexpected errors (e.g. malformed response);
                # still defensive, but not actionable per-message — warn.
                logger.warning(
                    "Unable to replace user ID with username for user_id '%s': %s",
                    user_id,
                    e,
                )
                return match.group(0)

        return _TAG_PATTERN.sub(_replace, message)

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
        return _TAG_PATTERN.sub(r"@\1", message)

    @staticmethod
    def replace_channels_basic(message: str) -> str:
        """Simply replaces all channel mentions with `#<CHANNEL_ID>` in order
        to make a message work as part of a link"""
        return _CHANNEL_MENTION_PATTERN.sub(r"#\2", message)

    @staticmethod
    def replace_special_mentions(message: str) -> str:
        """Simply replaces @channel, @here, and @everyone so we don't tag
        a bunch of people in Slack when we don't want to"""
        # Find user IDs in the message
        message = message.replace("<!channel>", "@channel")
        message = message.replace("<!here>", "@here")
        message = message.replace("<!everyone>", "@everyone")
        message = _SUBTEAM_MENTION_PATTERN.sub(
            lambda match: match.group("label") or f"@{match.group('id')}", message
        )
        return message

    @staticmethod
    def replace_special_catchall(message: str) -> str:
        """Replaces pattern of <!something|another-thing> with another-thing
        This is added for <!subteam^TEAM-ID|@team-name> but may match other cases as well
        """
        return _SPECIAL_CATCHALL_PATTERN.sub(r"\2", message)

    @staticmethod
    def add_zero_width_whitespace_after_tag(message: str) -> str:
        """Defang plain-text mentions without changing link destinations or code.

        A mailto token whose label is its own address is left whole, so its raw
        @ survives.
        """

        result: list[str] = []
        cursor = 0
        for match in _DEFANG_EXEMPT_REGION_PATTERN.finditer(message):
            result.append(_defang_mentions(message[cursor : match.start()]))
            url = match.group("url")
            label = match.group("label")
            if url is None or label is None:
                result.append(match.group(0))
            elif url.startswith("mailto:") and label == url.removeprefix("mailto:"):
                result.append(match.group(0))
            else:
                result.append(f"<{url}|{_defang_mentions(label)}>")
            cursor = match.end()
        result.append(_defang_mentions(message[cursor:]))
        return "".join(result)
