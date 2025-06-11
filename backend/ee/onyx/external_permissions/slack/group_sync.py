"""
THIS IS NOT USEFUL OR USED FOR PERMISSION SYNCING
WHEN USERGROUPS ARE ADDED TO A CHANNEL, IT JUST RESOLVES ALL THE USERS TO THAT CHANNEL
SO WHEN CHECKING IF A USER CAN ACCESS A DOCUMENT, WE ONLY NEED TO CHECK THEIR EMAIL
THERE IS NO USERGROUP <-> DOCUMENT PERMISSION MAPPING
"""

from slack_sdk import WebClient

from ee.onyx.db.external_perm import ExternalUserGroup
from ee.onyx.external_permissions.slack.utils import fetch_user_id_to_email_map
from onyx.connectors.credentials_provider import OnyxDBCredentialsProvider
from onyx.connectors.slack.connector import SlackConnector
from onyx.connectors.slack.utils import make_paginated_slack_api_call
from onyx.db.models import ConnectorCredentialPair
from onyx.redis.redis_pool import get_redis_client
from onyx.utils.logger import setup_logger

logger = setup_logger()


def _get_slack_group_ids(
    slack_client: WebClient,
) -> list[str]:
    group_ids = []
    for result in make_paginated_slack_api_call(slack_client.usergroups_list):
        for group in result.get("usergroups", []):
            group_ids.append(group.get("id"))
    return group_ids


def _get_slack_group_members_email(
    slack_client: WebClient,
    group_name: str,
    user_id_to_email_map: dict[str, str],
) -> list[str]:
    group_member_emails = []
    for result in make_paginated_slack_api_call(
        slack_client.usergroups_users_list, usergroup=group_name
    ):
        for member_id in result.get("users", []):
            member_email = user_id_to_email_map.get(member_id)
            if not member_email:
                # If the user is an external user, they wont get returned from the
                # conversations_members call so we need to make a separate call to users_info
                member_info = slack_client.users_info(user=member_id)
                member_email = member_info["user"]["profile"].get("email")
                if not member_email:
                    # If no email is found, we skip the user
                    continue
                user_id_to_email_map[member_id] = member_email
            group_member_emails.append(member_email)

    return group_member_emails


def slack_group_sync(
    tenant_id: str,
    cc_pair: ConnectorCredentialPair,
) -> list[ExternalUserGroup]:
    """NOTE: not used atm. All channel access is done at the
    individual user level. Leaving in for now in case we need it later."""

    provider = OnyxDBCredentialsProvider(tenant_id, "slack", cc_pair.credential.id)
    r = get_redis_client(tenant_id=tenant_id)
    slack_client = SlackConnector.make_slack_web_client(
        provider.get_provider_key(),
        cc_pair.credential.credential_json["slack_bot_token"],
        SlackConnector.MAX_RETRIES,
        r,
    )

    user_id_to_email_map = fetch_user_id_to_email_map(slack_client)

    onyx_groups: list[ExternalUserGroup] = []
    for group_name in _get_slack_group_ids(slack_client):
        group_member_emails = _get_slack_group_members_email(
            slack_client=slack_client,
            group_name=group_name,
            user_id_to_email_map=user_id_to_email_map,
        )
        if not group_member_emails:
            continue
        onyx_groups.append(
            ExternalUserGroup(id=group_name, user_emails=group_member_emails)
        )
    return onyx_groups
