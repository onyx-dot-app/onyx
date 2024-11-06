from typing import Any

from sqlalchemy.orm import Session

from danswer.connectors.confluence.onyx_confluence import OnyxConfluence
from danswer.connectors.confluence.utils import build_confluence_client
from danswer.connectors.confluence.utils import get_user_email_from_username__server
from danswer.db.models import ConnectorCredentialPair
from danswer.db.users import batch_add_non_web_user_if_not_exists__no_commit
from danswer.utils.logger import setup_logger
from ee.danswer.db.external_perm import ExternalUserGroup
from ee.danswer.db.external_perm import replace_user__ext_group_for_cc_pair__no_commit


logger = setup_logger()


def _get_group_members_email_paginated(
    confluence_client: OnyxConfluence,
    group_name: str,
) -> set[str]:
    members: list[dict[str, Any]] = []
    for member_batch in confluence_client.paginated_group_members_retrieval(group_name):
        members.extend(member_batch)

    group_member_emails: set[str] = set()
    for member in members:
        email = member.get("email")
        if not email:
            user_name = member.get("username")
            if user_name:
                email = get_user_email_from_username__server(
                    confluence_client=confluence_client,
                    user_name=user_name,
                )
        if email:
            group_member_emails.add(email)

    return group_member_emails


def confluence_group_sync(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
) -> None:
    is_cloud = cc_pair.connector.connector_specific_config.get("is_cloud", False)
    confluence_client = build_confluence_client(
        credentials_json=cc_pair.credential.credential_json,
        is_cloud=is_cloud,
        wiki_base=cc_pair.connector.connector_specific_config["wiki_base"],
    )

    # Get all group names
    group_names: list[str] = []
    for group_batch in confluence_client.paginated_groups_retrieval():
        for group in group_batch:
            if group_name := group.get("name"):
                group_names.append(group_name)

    # For each group name, get all members and create a danswer group
    danswer_groups: list[ExternalUserGroup] = []
    for group_name in group_names:
        group_member_emails = _get_group_members_email_paginated(
            confluence_client, group_name
        )
        group_members = batch_add_non_web_user_if_not_exists__no_commit(
            db_session=db_session, emails=list(group_member_emails)
        )
        if group_members:
            danswer_groups.append(
                ExternalUserGroup(
                    id=group_name,
                    user_ids=[user.id for user in group_members],
                )
            )

    replace_user__ext_group_for_cc_pair__no_commit(
        db_session=db_session,
        cc_pair_id=cc_pair.id,
        group_defs=danswer_groups,
        source=cc_pair.connector.source,
    )
