"""Named permission sync checks for Azure Data Lake Storage, one per access
path the syncs read: ACLs, the container's anonymous access, the account's
role and deny assignments in Azure Resource Manager, and the tenant's users
and group members in Microsoft Graph. All of them need an app registration,
since an account key opens storage only."""

from collections.abc import Callable
from typing import TypeVar

from ee.onyx.external_permissions.azure_datalake.directory import user_email
from ee.onyx.external_permissions.azure_datalake.rbac import (
    container_scope,
    find_storage_account,
    role_reads_blobs,
)
from onyx.connectors.azure_datalake.capability_checks import (
    ACCOUNT_LABELS,
    ALL_FIELDS,
    CONTAINER_FIELDS,
    DOCS_LINK,
    gateway_from_context,
    probe,
)
from onyx.connectors.azure_datalake.config import AzureDataLakeConnectorConfig
from onyx.connectors.azure_datalake.models import (
    AzureDataLakeAuthMethod,
    AzureDataLakeCredentials,
    AzureDataLakePath,
    AzureRoleAssignment,
    AzureRoleDefinition,
    AzureStorageAccountResource,
)
from onyx.connectors.azure_datalake.source_operations import (
    AzureDataLakeSourceOperations,
)
from onyx.connectors.capability_checks.microsoft_check_text import (
    raise_for_sign_in_error,
)
from onyx.connectors.capability_checks.models import (
    CapabilityCheck,
    CapabilityCheckContext,
    CheckAdvisory,
    CheckOutput,
    CredentialCapability,
)
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    InconclusiveValidationError,
    InsufficientPermissionsError,
)
from onyx.connectors.microsoft_utils.entra import EntraGroup, EntraUser
from onyx.connectors.microsoft_utils.graph_errors import (
    MicrosoftAuthError,
    MicrosoftGraphError,
    raise_for_auth_error,
)

T = TypeVar("T")

APP_REGISTRATION_CHECK_ID = "adls_perm_sync_app_registration"
ACL_CHECK_ID = "adls_acl_read"
ANONYMOUS_ACCESS_CHECK_ID = "adls_anonymous_access"
STORAGE_ACCOUNT_CHECK_ID = "adls_storage_account_resource"
ROLE_ASSIGNMENTS_CHECK_ID = "adls_role_assignments"
GRAPH_USERS_CHECK_ID = "adls_graph_users"
GRAPH_GROUP_MEMBERS_CHECK_ID = "adls_graph_group_members"

_PROBE_PAGE_SIZE = 10
_FILE_PROBE_PAGE_SIZE = 100
_FILE_PROBE_MAX_PAGES = 5
_ARM_REMEDIATION = (
    "Give the app registration the Reader role on the storage account, so it "
    "can read the account's role and deny assignments."
)
_STORAGE_REMEDIATION = (
    "Give the app registration the Storage Blob Data Reader role on the "
    "container. It reads every ACL with that role."
)


def _account_probe(action: Callable[[], T], failed: str) -> T:
    """``probe``, plus the sign-in errors of an Azure Resource Manager or
    Microsoft Graph token."""
    try:
        return probe(action, failed)
    except MicrosoftAuthError as error:
        raise_for_auth_error(error, ACCOUNT_LABELS)
    except MicrosoftGraphError as error:
        raise_for_sign_in_error(error)


def _first_file(
    gateway: AzureDataLakeSourceOperations, path_prefix: str
) -> AzureDataLakePath | None:
    continuation_token: str | None = None
    for _ in range(_FILE_PROBE_MAX_PAGES):
        page = gateway.list_paths_page(
            path_prefix=path_prefix,
            recursive=True,
            page_size=_FILE_PROBE_PAGE_SIZE,
            continuation_token=continuation_token,
        )
        for path in page.paths:
            if not path.is_directory:
                return path
        continuation_token = page.continuation_token
        if continuation_token is None:
            return None
    return None


class _PermSyncCheck(CapabilityCheck[AzureDataLakeConnectorConfig]):
    config_class = AzureDataLakeConnectorConfig

    def __init__(
        self,
        *,
        capability: CredentialCapability,
        check_id: str,
        display_name: str,
        remediation: str,
        depends_on: tuple[str, ...] = (APP_REGISTRATION_CHECK_ID,),
        config_fields: frozenset[str] = CONTAINER_FIELDS,
    ) -> None:
        super().__init__(
            capability=capability,
            check_id=check_id,
            display_name=display_name,
            requires_connector_instance=False,
            requires_fields=CONTAINER_FIELDS,
            config_fields=config_fields,
            remediation=remediation,
            docs_link=DOCS_LINK,
            depends_on=depends_on,
        )


class _AppRegistrationCheck(_PermSyncCheck):
    def __init__(self, capability: CredentialCapability) -> None:
        super().__init__(
            capability=capability,
            # One id for both capabilities, so the runner runs it once.
            check_id=APP_REGISTRATION_CHECK_ID,
            display_name="The account is an app registration",
            remediation=(
                "Use an app registration (client secret or certificate). An "
                "account key cannot read role assignments or Entra groups."
            ),
            depends_on=(),
        )

    def run(self, context: CapabilityCheckContext) -> None:
        credentials = AzureDataLakeCredentials.model_validate(context.credential_json)
        if credentials.authentication_method is AzureDataLakeAuthMethod.ACCOUNT_KEY:
            raise ConnectorValidationError(
                "Permission sync needs an app registration. An account key "
                "cannot read role assignments or Entra users and groups."
            )


class _AclCheck(_PermSyncCheck):
    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.DOC_PERMISSION_SYNC,
            check_id=ACL_CHECK_ID,
            display_name="ACLs are readable",
            remediation=_STORAGE_REMEDIATION,
            config_fields=ALL_FIELDS,
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        gateway = gateway_from_context(context)
        path_prefix: str = self.config(context).path_prefix
        probe(
            lambda: gateway.get_access_control(path="", is_directory=True),
            "The container root's ACL could not be read.",
        )
        file: AzureDataLakePath | None = probe(
            lambda: _first_file(gateway, path_prefix),
            "The files could not be listed.",
        )
        if file is None:
            return CheckOutput(
                summary="Read the container root's ACL",
                advisories=[
                    CheckAdvisory(
                        message="No file in scope, so a file's ACL was not read."
                    )
                ],
            )
        probe(
            lambda: gateway.get_access_control(path=file.name, is_directory=False),
            f"The ACL of {file.name} could not be read.",
        )
        return CheckOutput(summary="Read the ACLs of the container root and a file")


class _AnonymousAccessCheck(_PermSyncCheck):
    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.DOC_PERMISSION_SYNC,
            check_id=ANONYMOUS_ACCESS_CHECK_ID,
            display_name="The container's anonymous access level is readable",
            remediation=_STORAGE_REMEDIATION,
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        gateway = gateway_from_context(context)
        access = probe(
            gateway.get_container_access,
            "The container's anonymous access level could not be read.",
        )
        return CheckOutput(
            summary=(
                "The container allows anonymous reads"
                if access.anonymous_read
                else "The container is private"
            )
        )


def _find_account(
    context: CapabilityCheckContext, config: AzureDataLakeConnectorConfig
) -> AzureStorageAccountResource:
    gateway = gateway_from_context(context)
    return _account_probe(
        lambda: find_storage_account(gateway, config.account_name),
        "The storage account could not be found in Azure Resource Manager.",
    )


class _StorageAccountCheck(_PermSyncCheck):
    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.DOC_PERMISSION_SYNC,
            check_id=STORAGE_ACCOUNT_CHECK_ID,
            display_name="The storage account is visible in Azure Resource Manager",
            remediation=_ARM_REMEDIATION,
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        account = _find_account(context, self.config(context))
        return CheckOutput(summary=f"Found {account.name}", description=account.id)


class _RoleAssignmentsCheck(_PermSyncCheck):
    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.DOC_PERMISSION_SYNC,
            check_id=ROLE_ASSIGNMENTS_CHECK_ID,
            display_name="Role and deny assignments are readable",
            remediation=_ARM_REMEDIATION,
            depends_on=(APP_REGISTRATION_CHECK_ID, STORAGE_ACCOUNT_CHECK_ID),
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        gateway = gateway_from_context(context)
        config = self.config(context)
        scope: str = container_scope(
            _find_account(context, config), config.container_name
        )

        def read_assignments() -> list[str]:
            """The ids of conditioned assignments of a reading role."""
            assignments: list[AzureRoleAssignment] = gateway.list_role_assignments(
                scope=scope
            )
            definitions: dict[str, AzureRoleDefinition] = {}
            conditioned: list[str] = []
            for assignment in assignments:
                key: str = assignment.role_definition_id.lower()
                if key not in definitions:
                    definitions[key] = gateway.get_role_definition(
                        role_definition_id=assignment.role_definition_id
                    )
                if assignment.condition and role_reads_blobs(definitions[key]):
                    conditioned.append(assignment.id)
            gateway.list_deny_assignments(scope=scope)
            return conditioned

        conditioned: list[str] = _account_probe(
            read_assignments, "The container's role assignments could not be read."
        )
        if not conditioned:
            return CheckOutput(summary="Read the container's role assignments")
        return CheckOutput(
            summary="Read the container's role assignments",
            advisories=[
                CheckAdvisory(
                    message=(
                        f"{len(conditioned)} role assignment(s) that can read "
                        "files have a condition, which Onyx cannot evaluate. "
                        "Their principals get no access through them."
                    )
                )
            ],
        )


class _GraphUsersCheck(_PermSyncCheck):
    def __init__(self, capability: CredentialCapability) -> None:
        super().__init__(
            capability=capability,
            check_id=GRAPH_USERS_CHECK_ID,
            display_name="Entra users are readable",
            remediation=(
                "Grant the app registration the Microsoft Graph application "
                "permission User.Read.All, with admin consent."
            ),
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        gateway = gateway_from_context(context)
        users: list[EntraUser] = _account_probe(
            lambda: gateway.list_users(page_size=_PROBE_PAGE_SIZE).items,
            "The app cannot list Entra users.",
        )
        # An app without User.Read.All sees users with no address, and every
        # user then maps to nobody. A disabled user has no address either way.
        enabled: list[EntraUser] = [
            user for user in users if user.account_enabled is not False
        ]
        if enabled and not any(user_email(user) for user in enabled):
            raise InsufficientPermissionsError(
                "Microsoft Graph shows no user addresses to this app. Grant "
                "User.Read.All."
            )
        return CheckOutput(summary="Read the tenant's users")


class _GraphGroupMembersCheck(_PermSyncCheck):
    def __init__(self, capability: CredentialCapability) -> None:
        super().__init__(
            capability=capability,
            check_id=GRAPH_GROUP_MEMBERS_CHECK_ID,
            display_name="Entra group members are readable",
            remediation=(
                "Grant the app registration the Microsoft Graph application "
                "permission GroupMember.Read.All, with admin consent."
            ),
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        gateway = gateway_from_context(context)
        groups: list[EntraGroup] = _account_probe(
            lambda: gateway.list_groups(page_size=_PROBE_PAGE_SIZE).items,
            "The app cannot list Entra groups.",
        )
        if not groups:
            raise InconclusiveValidationError(
                "The tenant has no Entra group, so no members were read.",
                summary="No groups found",
            )
        group: EntraGroup = groups[0]
        _account_probe(
            lambda: gateway.list_transitive_group_members(group_id=group.id),
            "The app cannot read Entra group members.",
        )
        return CheckOutput(
            summary=f"Read the members of {group.display_name or group.id}"
        )


def build_azure_datalake_doc_permission_sync_checks() -> list[CapabilityCheck]:
    return [
        _AppRegistrationCheck(CredentialCapability.DOC_PERMISSION_SYNC),
        _AclCheck(),
        _AnonymousAccessCheck(),
        _StorageAccountCheck(),
        _RoleAssignmentsCheck(),
        _GraphUsersCheck(CredentialCapability.DOC_PERMISSION_SYNC),
        _GraphGroupMembersCheck(CredentialCapability.DOC_PERMISSION_SYNC),
    ]


def build_azure_datalake_group_sync_checks() -> list[CapabilityCheck]:
    return [
        _AppRegistrationCheck(CredentialCapability.EXTERNAL_GROUP_SYNC),
        _GraphUsersCheck(CredentialCapability.EXTERNAL_GROUP_SYNC),
        _GraphGroupMembersCheck(CredentialCapability.EXTERNAL_GROUP_SYNC),
    ]
