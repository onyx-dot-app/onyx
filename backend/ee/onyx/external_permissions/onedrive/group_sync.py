from collections.abc import Generator

from ee.onyx.db.external_perm import ExternalUserGroup
from ee.onyx.external_permissions.microsoft_utils.entra_groups import normalize_email
from ee.onyx.external_permissions.utils import credential_json
from onyx.connectors.microsoft_utils.entra import (
    EntraDirectoryObjectPage,
    EntraDirectoryObjectType,
    EntraGroup,
    iter_entra_group_members,
    iter_entra_groups,
)
from onyx.connectors.microsoft_utils.graph_errors import (
    MicrosoftGraphError as OneDriveGraphError,
)
from onyx.connectors.onedrive.connector import OneDriveConnector
from onyx.db.models import ConnectorCredentialPair
from onyx.utils.logger import setup_logger

MEMBER_READ_HIDDEN_SCOPE = "Member.Read.Hidden"
MAX_GROUP_MEMBERS = 1_000_000
logger = setup_logger()


class _HiddenMembershipDenied(Exception):
    pass


def _member_page(
    connector: OneDriveConnector,
    group: EntraGroup,
    next_link: str | None,
) -> EntraDirectoryObjectPage:
    try:
        return connector.ops.list_transitive_group_members(
            group_id=group.id,
            next_link=next_link,
        )
    except OneDriveGraphError as error:
        if error.status != 403:
            raise
        logger.warning(
            "Cannot expand Entra group '%s'. Grant '%s' for hidden "
            "membership. Clearing its mapped users.",
            group.display_name or group.id,
            MEMBER_READ_HIDDEN_SCOPE,
        )
        raise _HiddenMembershipDenied from error


def _group_members(connector: OneDriveConnector, group: EntraGroup) -> list[str]:
    emails: set[str] = set()
    try:
        members = iter_entra_group_members(
            group.id,
            lambda next_link: _member_page(connector, group, next_link),
        )
        for member in members:
            if member.odata_type not in (None, EntraDirectoryObjectType.USER):
                continue
            email: str | None = member.user_principal_name or member.mail
            if email:
                emails.add(normalize_email(email).lower())
            if len(emails) > MAX_GROUP_MEMBERS:
                raise ValueError(
                    f"Entra group `{group.id}` exceeds the member count limit."
                )
    except _HiddenMembershipDenied:
        return []
    return sorted(emails)


def onedrive_group_sync(
    tenant_id: str,  # noqa: ARG001
    cc_pair: ConnectorCredentialPair,
) -> Generator[ExternalUserGroup, None, None]:
    connector = OneDriveConnector(**cc_pair.connector.connector_specific_config)
    connector.load_credentials(credential_json(cc_pair))

    groups = iter_entra_groups(
        lambda next_link: connector.ops.list_groups(next_link=next_link)
    )
    for group in groups:
        yield ExternalUserGroup(
            id=group.id,
            user_emails=_group_members(connector, group),
        )
