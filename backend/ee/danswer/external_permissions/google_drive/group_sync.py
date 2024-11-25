from sqlalchemy.orm import Session

from danswer.connectors.google_drive.connector import GoogleDriveConnector
from danswer.connectors.google_utils.google_utils import execute_paginated_retrieval
from danswer.connectors.google_utils.resources import get_admin_service
from danswer.db.models import ConnectorCredentialPair
from danswer.db.users import batch_add_non_web_user_if_not_exists__no_commit
from danswer.utils.logger import setup_logger
from ee.danswer.db.external_perm import ExternalUserGroup
from ee.danswer.db.external_perm import replace_user__ext_group_for_cc_pair__no_commit

logger = setup_logger()


def gdrive_group_sync(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
) -> None:
    google_drive_connector = GoogleDriveConnector(
        **cc_pair.connector.connector_specific_config
    )
    google_drive_connector.load_credentials(cc_pair.credential.credential_json)
    admin_service = get_admin_service(
        google_drive_connector.creds, google_drive_connector.primary_admin_email
    )

    danswer_groups: list[ExternalUserGroup] = []
    for group in execute_paginated_retrieval(
        admin_service.groups().list,
        list_key="groups",
        domain=google_drive_connector.google_domain,
        fields="groups(email)",
    ):
        # The id is the group email
        group_email = group["email"]

        # Gather group member emails
        group_member_emails: list[str] = []
        for member in execute_paginated_retrieval(
            admin_service.members().list,
            list_key="members",
            groupKey=group_email,
            fields="members(email)",
        ):
            group_member_emails.append(member["email"])

        # Add group members to DB and get their IDs
        group_members = batch_add_non_web_user_if_not_exists__no_commit(
            db_session=db_session, emails=group_member_emails
        )
        if group_members:
            danswer_groups.append(
                ExternalUserGroup(
                    id=group_email, user_ids=[user.id for user in group_members]
                )
            )

    replace_user__ext_group_for_cc_pair__no_commit(
        db_session=db_session,
        cc_pair_id=cc_pair.id,
        group_defs=danswer_groups,
        source=cc_pair.connector.source,
    )
