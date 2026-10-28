"""The tenant's users and group members from Microsoft Graph, each read once
per sync."""

from ee.onyx.external_permissions.azure_datalake.principals import EntraDirectory
from ee.onyx.external_permissions.microsoft_utils.entra_groups import normalize_email
from onyx.connectors.azure_datalake.models import AzureDataLakeCredentials
from onyx.connectors.azure_datalake.source_operations import (
    AzureDataLakeNotFoundError,
    AzureDataLakeSourceOperations,
)
from onyx.connectors.exceptions import InsufficientPermissionsError
from onyx.connectors.microsoft_utils.entra import (
    EntraDirectoryObjectType,
    EntraUser,
    iter_entra_items,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()

# A guest's user principal name holds this marker; its mail is the address.
_EXTERNAL_USER_MARKER = "#EXT#"
_EVERYONE_GROUP_PREFIX = "entra_tenant_everyone"


def everyone_group_id(ops: AzureDataLakeSourceOperations) -> str:
    """The synced group of every user in the credential's tenant: the ACL
    ``other`` class. Scoped to the tenant, since connectors of other tenants
    have their own."""
    credentials = AzureDataLakeCredentials.model_validate(
        ops.credentials_provider.get_credentials()
    )
    tenant: str = (credentials.adls_directory_id or "").strip().lower()
    return f"{_EVERYONE_GROUP_PREFIX}:{tenant}"


def user_email(user: EntraUser) -> str | None:
    """The address Onyx knows the user by. None for a disabled account, which
    cannot sign in to read anything."""
    if user.account_enabled is False:
        return None
    principal_name: str | None = user.user_principal_name
    if principal_name and _EXTERNAL_USER_MARKER not in principal_name:
        address: str | None = principal_name
    else:
        address = user.mail or principal_name
    if not address:
        return None
    return normalize_email(address).lower()


class GroupMembersUnreadableError(Exception):
    """Microsoft Graph refuses to list a group's members."""


class GraphDirectory(EntraDirectory):
    def __init__(self, ops: AzureDataLakeSourceOperations) -> None:
        self._ops = ops
        self._emails: dict[str, str] | None = None
        self._members: dict[str, frozenset[str]] = {}

    def _user_emails(self) -> dict[str, str]:
        if self._emails is None:
            emails: dict[str, str] = {}
            for user in iter_entra_items(
                lambda next_link: self._ops.list_users(next_link=next_link),
                "Entra user listing",
            ):
                if (email := user_email(user)) is not None:
                    emails[user.id] = email
            self._emails = emails
        return self._emails

    def all_users(self) -> frozenset[str]:
        return frozenset(self._user_emails())

    def user_email(self, user_id: str) -> str | None:
        return self._user_emails().get(user_id)

    def group_members(self, group_id: str) -> frozenset[str]:
        if group_id in self._members:
            return self._members[group_id]
        members: set[str] = set()
        try:
            for member in iter_entra_items(
                lambda next_link: self._ops.list_transitive_group_members(
                    group_id=group_id, next_link=next_link
                ),
                f"Entra group `{group_id}` members",
            ):
                if member.odata_type in (None, EntraDirectoryObjectType.USER):
                    members.add(member.id)
        except AzureDataLakeNotFoundError:
            # An ACL can still name a deleted group, which holds nobody.
            logger.info("Entra group %s no longer exists", group_id)
            members = set()
        except InsufficientPermissionsError as e:
            # Hidden membership needs Member.Read.Hidden. An empty set would be
            # wrong wherever the group excludes people, so the caller decides.
            raise GroupMembersUnreadableError(
                f"Cannot read the members of Entra group {group_id}. Grant "
                "Member.Read.Hidden for groups with hidden membership."
            ) from e
        self._members[group_id] = frozenset(members)
        return self._members[group_id]
