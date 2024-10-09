"""
THIS IS NOT USEFUL OR USED FOR PERMISSION SYNCING
WHEN USERGROUPS ARE ADDED TO A CHANNEL, IT JUST RESOLVES ALL THE USERS TO THAT CHANNEL
SO WHEN CHECKING IF A USER CAN ACCESS A DOCUMENT, WE ONLY NEED TO CHECK THEIR EMAIL
THERE IS NO USERGROUP <-> DOCUMENT PERMISSION MAPPING
"""
from slack_sdk import WebClient
from sqlalchemy.orm import Session

from danswer.connectors.slack.connector import make_paginated_slack_api_call_w_retries
from danswer.db.models import ConnectorCredentialPair
from danswer.db.users import batch_add_non_web_user_if_not_exists__no_commit
from danswer.utils.logger import setup_logger
from ee.danswer.db.external_perm import ExternalUserGroup
from ee.danswer.db.external_perm import replace_user__ext_group_for_cc_pair__no_commit
from ee.danswer.external_permissions.slack.utils import fetch_user_id_to_email_map

logger = setup_logger()


def _get_slack_group_ids(
    slack_client: WebClient,
) -> list[str]:
    group_ids = []
    for result in make_paginated_slack_api_call_w_retries(slack_client.usergroups_list):
        for group in result.get("usergroups", []):
            group_ids.append(group.get("id"))
    return group_ids


def _get_slack_group_members_email(
    db_session: Session,
    slack_client: WebClient,
    group_name: str,
    user_id_to_email_map: dict[str, str],
) -> list[str]:
    group_member_emails = []
    for result in make_paginated_slack_api_call_w_retries(
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
                batch_add_non_web_user_if_not_exists__no_commit(
                    db_session, [member_email]
                )
            group_member_emails.append(member_email)

    return group_member_emails


def slack_group_sync(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
) -> None:
    slack_client = WebClient(
        token=cc_pair.credential.credential_json["slack_bot_token"]
    )
    user_id_to_email_map = fetch_user_id_to_email_map(slack_client)

    danswer_groups: list[ExternalUserGroup] = []
    for group_name in _get_slack_group_ids(slack_client):
        group_member_emails = _get_slack_group_members_email(
            db_session=db_session,
            slack_client=slack_client,
            group_name=group_name,
            user_id_to_email_map=user_id_to_email_map,
        )
        group_members = batch_add_non_web_user_if_not_exists__no_commit(
            db_session=db_session, emails=group_member_emails
        )
        if group_members:
            danswer_groups.append(
                ExternalUserGroup(
                    id=group_name, user_ids=[user.id for user in group_members]
                )
            )

    replace_user__ext_group_for_cc_pair__no_commit(
        db_session=db_session,
        cc_pair_id=cc_pair.id,
        group_defs=danswer_groups,
        source=cc_pair.connector.source,
    )
