from danswer.connectors.google_drive.connector import GoogleDriveConnector
from danswer.connectors.google_utils.google_utils import execute_paginated_retrieval
from danswer.connectors.google_utils.resources import get_admin_service
from danswer.db.models import ConnectorCredentialPair
from danswer.utils.logger import setup_logger
from ee.danswer.db.external_perm import ExternalUserGroup

logger = setup_logger()


def gdrive_group_sync(
    cc_pair: ConnectorCredentialPair,
) -> list[ExternalUserGroup]:
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

        if not group_member_emails:
            continue

        danswer_groups.append(
            ExternalUserGroup(
                id=group_email,
                user_emails=list(group_member_emails),
            )
        )

    return danswer_groups
