from collections.abc import Callable
from typing import cast

from slack_sdk import WebClient

from onyx.access.models import ExternalAccess
from onyx.connectors.models import BasicExpertInfo
from onyx.connectors.slack.models import ChannelType
from onyx.utils.variable_functionality import fetch_versioned_implementation
from onyx.utils.variable_functionality import global_version


def get_channel_access(
    client: WebClient,
    channel: ChannelType,
    user_cache: dict[str, BasicExpertInfo | None],
) -> ExternalAccess | None:
    """
    Get channel access permissions for a Slack channel.
    This functionality requires Enterprise Edition.

    Args:
        client: Slack WebClient instance
        channel: Slack channel object containing channel info
        user_cache: Cache of user IDs to BasicExpertInfo objects. May be updated in place.

    Returns:
        ExternalAccess object for the channel. None if EE is not enabled.
    """
    # Check if EE is enabled
    if not global_version.is_ee_version():
        return None

    # Fetch the EE implementation
    ee_get_channel_access = cast(
        Callable[
            [WebClient, ChannelType, dict[str, BasicExpertInfo | None]],
            ExternalAccess,
        ],
        fetch_versioned_implementation(
            "onyx.external_permissions.slack.channel_access", "get_channel_access"
        ),
    )

    return ee_get_channel_access(client, channel, user_cache)
