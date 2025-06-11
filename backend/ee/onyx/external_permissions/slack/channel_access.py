from slack_sdk import WebClient

from onyx.access.models import ExternalAccess
from onyx.connectors.models import BasicExpertInfo
from onyx.connectors.slack.connector import ChannelType
from onyx.connectors.slack.utils import expert_info_from_slack_id
from onyx.connectors.slack.utils import make_paginated_slack_api_call


def get_channel_access(
    client: WebClient,
    channel: ChannelType,
    user_cache: dict[str, BasicExpertInfo | None],
) -> ExternalAccess:
    """
    Get channel access permissions for a Slack channel.

    Args:
        client: Slack WebClient instance
        channel: Slack channel object containing channel info
        user_cache: Cache of user IDs to BasicExpertInfo objects. May be updated in place.

    Returns:
        ExternalAccess object for the channel.
    """
    channel_is_public = not channel["is_private"]
    if channel_is_public:
        return ExternalAccess(
            external_user_emails=set(),
            external_user_group_ids=set(),
            is_public=True,
        )

    channel_id = channel["id"]

    # Get all member IDs for the channel
    member_ids = []
    for result in make_paginated_slack_api_call(
        client.conversations_members,
        channel=channel_id,
    ):
        member_ids.extend(result.get("members", []))

    member_emails = set()
    for member_id in member_ids:
        # Try to get user info from cache or fetch it
        user_info = expert_info_from_slack_id(
            user_id=member_id,
            client=client,
            user_cache=user_cache,
        )

        # If we have user info and an email, add it to the set
        if user_info and user_info.email:
            member_emails.add(user_info.email)

    return ExternalAccess(
        external_user_emails=member_emails,
        # NOTE: groups are not used, since adding a group to a channel just adds all
        # users that are in the group.
        external_user_group_ids=set(),
        is_public=False,
    )
