from slack_sdk import WebClient

from onyx.access.models import ExternalAccess
from onyx.connectors.models import BasicExpertInfo
from onyx.connectors.slack.connector import channel_team_ids
from onyx.connectors.slack.connector import ChannelType
from onyx.connectors.slack.utils import expert_info_from_slack_id
from onyx.connectors.slack.utils import make_paginated_slack_api_call


def get_channel_access(
    client: WebClient,
    channel: ChannelType,
    user_cache: dict[str, BasicExpertInfo | None],
    team_id_to_user_emails: dict[str, set[str]] | None = None,
) -> ExternalAccess:
    """Get channel access permissions for a Slack channel.

    On Enterprise Grid, public channels are scoped to the union of users in
    the workspaces the channel is shared into (via ``team_id_to_user_emails``).
    On non-Grid, public channels stay org-public (existing behavior).
    """
    channel_is_public = not channel["is_private"]
    if channel_is_public:
        if team_id_to_user_emails:
            emails: set[str] = set()
            for tid in channel_team_ids(channel):
                emails |= team_id_to_user_emails.get(tid, set())
            if 0 < len(emails) <= ExternalAccess.MAX_NUM_ENTRIES:
                return ExternalAccess(
                    external_user_emails=emails,
                    external_user_group_ids=set(),
                    is_public=False,
                )
            # Empty union (channel's teams not in cache — e.g. workspace added
            # post-init or Slack Connect share) or union past the perm-sync
            # size guard. Fall back to is_public so the doc stays accessible.
        return ExternalAccess(
            external_user_emails=set(),
            external_user_group_ids=set(),
            is_public=True,
        )

    channel_id = channel["id"]

    member_ids = []
    for result in make_paginated_slack_api_call(
        client.conversations_members,
        channel=channel_id,
    ):
        member_ids.extend(result.get("members", []))

    member_emails = set()
    for member_id in member_ids:
        user_info = expert_info_from_slack_id(
            user_id=member_id,
            client=client,
            user_cache=user_cache,
        )
        if user_info and user_info.email:
            member_emails.add(user_info.email)

    return ExternalAccess(
        external_user_emails=member_emails,
        external_user_group_ids=set(),
        is_public=False,
    )
