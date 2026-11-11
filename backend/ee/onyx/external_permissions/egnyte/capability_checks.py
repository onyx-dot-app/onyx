"""Named permission sync checks for Egnyte. Both syncs need an administrator's
token, because only administrators list every user and see every folder, and
a token with the Egnyte.permission, Egnyte.user and Egnyte.group scopes.
Credentials connected before permission sync have only Egnyte.filesystem, so
the admin connects the account again."""

from onyx.connectors.capability_checks.models import (
    CapabilityCheck,
    CapabilityCheckContext,
    CheckAdvisory,
    CheckOutput,
    CredentialCapability,
)
from onyx.connectors.egnyte.capability_checks import (
    SIGN_IN_CHECK_ID,
    configured_folder,
    gateway_from_context,
    probe,
)
from onyx.connectors.egnyte.config import EgnyteConnectorConfig
from onyx.connectors.egnyte.connector import PATHS_WITHOUT_PERMISSIONS
from onyx.connectors.egnyte.models import EgnyteGroupRef, EgnyteUserType
from onyx.connectors.egnyte.source_operations import EgnyteSourceOperations
from onyx.connectors.exceptions import InsufficientPermissionsError

_REMEDIATION: str = (
    "Connect the Egnyte account again as an administrator, and allow the "
    "permission, user and group access that Onyx asks for."
)
# Egnyte refuses to list the permissions of "/" and "/Private", so a check of
# the whole domain reads those of "/Shared".
_PERMISSIONS_PROBE_FALLBACK: str = "/Shared"


class _AdministratorCheck(CapabilityCheck[EgnyteConnectorConfig]):
    config_class = EgnyteConnectorConfig

    def __init__(self, capability: CredentialCapability) -> None:
        super().__init__(
            capability=capability,
            # One id for both capabilities, so the runner reads it once.
            check_id="egnyte_administrator",
            display_name="The connected user is an Egnyte administrator",
            requires_connector_instance=False,
            depends_on=(SIGN_IN_CHECK_ID,),
            remediation=_REMEDIATION,
        )

    def run(self, context: CapabilityCheckContext) -> None:
        user_type: EgnyteUserType = probe(
            gateway_from_context(context).get_user_info,
            "Onyx could not read the connected user.",
        ).user_type
        if user_type != EgnyteUserType.ADMIN:
            raise InsufficientPermissionsError(
                f"The connected Egnyte user is a {user_type.value} user. {_REMEDIATION}"
            )


class _DirectoryCheck(CapabilityCheck[EgnyteConnectorConfig]):
    config_class = EgnyteConnectorConfig

    def __init__(self, capability: CredentialCapability) -> None:
        super().__init__(
            capability=capability,
            check_id="egnyte_directory",
            display_name="Users and groups are readable",
            requires_connector_instance=False,
            depends_on=(SIGN_IN_CHECK_ID,),
            remediation=_REMEDIATION,
        )

    def run(self, context: CapabilityCheckContext) -> None:
        gateway: EgnyteSourceOperations = gateway_from_context(context)
        probe(gateway.list_users, "Onyx could not list the Egnyte users.")
        probe(gateway.list_groups, "Onyx could not list the Egnyte groups.")


class _FolderPermissionsCheck(CapabilityCheck[EgnyteConnectorConfig]):
    config_class = EgnyteConnectorConfig

    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.DOC_PERMISSION_SYNC,
            check_id="egnyte_folder_permissions",
            display_name="Folder permissions are readable",
            requires_connector_instance=False,
            requires_connector_config=True,
            depends_on=(SIGN_IN_CHECK_ID,),
            remediation=_REMEDIATION,
        )

    def run(self, context: CapabilityCheckContext) -> None:
        folder_path: str = configured_folder(context)
        if folder_path in PATHS_WITHOUT_PERMISSIONS:
            folder_path = _PERMISSIONS_PROBE_FALLBACK
        probe(
            lambda: gateway_from_context(context).list_folder_page_with_permissions(
                folder_path=folder_path, offset=0, page_size=1
            ),
            f"Onyx could not read the permissions of {folder_path}.",
        )


class _GroupMembersCheck(CapabilityCheck[EgnyteConnectorConfig]):
    config_class = EgnyteConnectorConfig

    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.EXTERNAL_GROUP_SYNC,
            check_id="egnyte_group_members",
            display_name="Group members are readable",
            requires_connector_instance=False,
            depends_on=(SIGN_IN_CHECK_ID,),
            remediation=_REMEDIATION,
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput | None:
        gateway: EgnyteSourceOperations = gateway_from_context(context)
        groups: list[EgnyteGroupRef] = probe(
            gateway.list_groups, "Onyx could not list the Egnyte groups."
        )
        if not groups:
            return CheckOutput(
                advisories=[
                    CheckAdvisory(
                        message="Egnyte has no custom groups, so members were not read."
                    )
                ]
            )
        probe(
            lambda: gateway.get_group(group_id=groups[0].id),
            "Onyx could not read the members of an Egnyte group.",
        )
        return None


def build_egnyte_doc_permission_sync_checks() -> list[CapabilityCheck]:
    return [
        _AdministratorCheck(CredentialCapability.DOC_PERMISSION_SYNC),
        _DirectoryCheck(CredentialCapability.DOC_PERMISSION_SYNC),
        _FolderPermissionsCheck(),
    ]


def build_egnyte_group_sync_checks() -> list[CapabilityCheck]:
    return [
        _AdministratorCheck(CredentialCapability.EXTERNAL_GROUP_SYNC),
        _DirectoryCheck(CredentialCapability.EXTERNAL_GROUP_SYNC),
        _GroupMembersCheck(),
    ]
