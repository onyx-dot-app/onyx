from collections.abc import Generator

from ee.onyx.db.external_perm import ExternalUserGroup
from ee.onyx.external_permissions.utils import credential_json
from onyx.connectors.microsoft_utils.graph_errors import (
    MicrosoftGraphError as OneDriveGraphError,
)
from onyx.connectors.onedrive.connector import OneDriveConnector
from onyx.connectors.onedrive.models import GraphDirectoryObjectType, OneDriveGroup
from onyx.db.models import ConnectorCredentialPair
from onyx.utils.logger import setup_logger

MEMBER_READ_HIDDEN_SCOPE = "Member.Read.Hidden"
logger = setup_logger()


def _group_members(connector: OneDriveConnector, group: OneDriveGroup) -> list[str]:
    emails: set[str] = set()
    next_link: str | None = None
    while True:
        try:
            page = connector.ops.list_transitive_group_members(
                group_id=group.id, next_link=next_link
            )
        except OneDriveGraphError as error:
            if error.status == 403:
                logger.warning(
                    "Cannot expand Entra group '%s'. Grant '%s' for hidden "
                    "membership. Clearing its mapped users.",
                    group.display_name or group.id,
                    MEMBER_READ_HIDDEN_SCOPE,
                )
                return []
            raise
        for member in page.members:
            if member.odata_type not in (None, GraphDirectoryObjectType.USER):
                continue
            email = member.user_principal_name or member.mail
            if email:
                emails.add(email.lower())
        next_link = page.next_link
        if next_link is None:
            return sorted(emails)


def onedrive_group_sync(
    tenant_id: str,  # noqa: ARG001
    cc_pair: ConnectorCredentialPair,
) -> Generator[ExternalUserGroup, None, None]:
    connector = OneDriveConnector(**cc_pair.connector.connector_specific_config)
    connector.load_credentials(credential_json(cc_pair))

    next_link: str | None = None
    while True:
        page = connector.ops.list_groups(next_link=next_link)
        for group in page.groups:
            yield ExternalUserGroup(
                id=group.id,
                user_emails=_group_members(connector, group),
            )
        next_link = page.next_link
        if next_link is None:
            return
