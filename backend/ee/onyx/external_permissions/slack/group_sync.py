"""
THIS IS NOT USEFUL OR USED FOR PERMISSION SYNCING
WHEN USERGROUPS ARE ADDED TO A CHANNEL, IT JUST RESOLVES ALL THE USERS TO THAT CHANNEL
SO WHEN CHECKING IF A USER CAN ACCESS A DOCUMENT, WE ONLY NEED TO CHECK THEIR EMAIL
THERE IS NO USERGROUP <-> DOCUMENT PERMISSION MAPPING
"""

from ee.onyx.db.external_perm import ExternalUserGroup
from ee.onyx.external_permissions.slack.utils import fetch_user_id_to_email_map
from onyx.configs.constants import DocumentSource
from onyx.connectors.credentials_provider import build_db_credentials_provider
from onyx.connectors.slack.source_operations import SlackSourceOperations
from onyx.db.models import ConnectorCredentialPair
from onyx.utils.logger import setup_logger

logger = setup_logger()


def _get_slack_group_ids(
    source_operations: SlackSourceOperations,
) -> list[str]:
    group_ids = []
    for result in source_operations.list_usergroups():
        for group in result.get("usergroups", []):
            group_ids.append(group.get("id"))
    return group_ids


def _get_slack_group_members_email(
    source_operations: SlackSourceOperations,
    group_name: str,
    user_id_to_email_map: dict[str, str],
) -> list[str]:
    group_member_emails = []
    for result in source_operations.list_usergroup_members(usergroup_id=group_name):
        for member_id in result.get("users", []):
            member_email = user_id_to_email_map.get(member_id)
            if not member_email:
                # If the user is an external user, they wont get returned from the
                # conversations_members call so we need to make a separate call to users_info
                member_info = source_operations.fetch_user_info(member_id)
                member_email = member_info["user"]["profile"].get("email")
                if not member_email:
                    # If no email is found, we skip the user
                    continue
                user_id_to_email_map[member_id] = member_email
            group_member_emails.append(member_email)

    return group_member_emails


def slack_group_sync(
    tenant_id: str,  # noqa: ARG001
    cc_pair: ConnectorCredentialPair,
) -> list[ExternalUserGroup]:
    """NOTE: not used atm. All channel access is done at the
    individual user level. Leaving in for now in case we need it later."""

    # The provider derives the tenant from the request context, like doc sync.
    provider = build_db_credentials_provider(
        DocumentSource.SLACK, cc_pair.credential.id
    )
    source_operations = SlackSourceOperations(credentials_provider=provider)

    user_id_to_email_map = fetch_user_id_to_email_map(source_operations)

    onyx_groups: list[ExternalUserGroup] = []
    for group_name in _get_slack_group_ids(source_operations):
        group_member_emails = _get_slack_group_members_email(
            source_operations=source_operations,
            group_name=group_name,
            user_id_to_email_map=user_id_to_email_map,
        )
        if not group_member_emails:
            continue
        onyx_groups.append(
            ExternalUserGroup(id=group_name, user_emails=group_member_emails)
        )
    return onyx_groups
