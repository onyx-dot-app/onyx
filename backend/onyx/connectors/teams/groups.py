"""What the Teams group sync lists: the members of every group a channel
thread names. The sync deletes the groups a failed run did not reach, so a
team or a channel Graph refuses for good is left out and the listing goes on."""

from collections.abc import Iterable, Iterator

import requests
from office365.runtime.client_request_exception import ClientRequestException
from office365.teams.channels.channel import Channel
from office365.teams.team import Team

from onyx.connectors.teams import listing
from onyx.connectors.teams.models import ChannelRef
from onyx.connectors.teams.refusals import is_permanent, warn_group_left_out
from onyx.connectors.teams.session import TeamsSession
from onyx.connectors.teams.utils import channel_group_id, fetch_channel_member_emails
from onyx.utils.logger import setup_logger

logger = setup_logger()


def group_sync_channels(team: Team) -> list[Channel]:
    """A team's channels for the group sync. A listing Graph refuses for good
    leaves the team out, as a refused channel is: a raise would take access
    from every team listed after it."""
    try:
        return listing.collect_all_channels_from_team(team=team)
    # The SDK lists channels and raises its own subclass of RequestException.
    except ClientRequestException as e:
        if not is_permanent(e):
            raise
        logger.warning(
            "The channels of team %s could not be listed, so its groups are left "
            "out of this sync: %s",
            team.id,
            e,
        )
        return []


def channel_member_groups(
    session: TeamsSession, channels: Iterable[ChannelRef]
) -> Iterator[tuple[str, list[str]]]:
    """Each group a thread names and the emails in it: one per team for its
    standard channels and one per private or shared channel."""
    listed: set[str] = set()
    for channel in channels:
        group_id = channel_group_id(channel)
        # A team's standard channels share their members, read once. A refused
        # one leaves the team's group to the next of them.
        if group_id in listed:
            continue
        try:
            emails = fetch_channel_member_emails(
                session.graph(), channel.team_id, channel.id, session.directory()
            )
        except requests.HTTPError as e:
            if not is_permanent(e):
                raise
            warn_group_left_out(channel, "members", e)
            continue
        listed.add(group_id)
        yield group_id, emails
