"""A fake tenant and container for the Azure Data Lake permission tests."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, create_autospec

from onyx.connectors.azure_datalake.models import (
    AzureDataLakeAccessControl,
    AzureDataLakeContainerAccess,
    AzureDataLakePath,
    AzureDenyAssignment,
    AzureRoleAssignment,
    AzureRoleDefinition,
    AzureRolePermission,
    AzureStorageAccountPage,
    AzureStorageAccountResource,
    AzureSubscription,
    AzureSubscriptionPage,
)
from onyx.connectors.azure_datalake.source_operations import (
    AzureDataLakeNotFoundError,
    AzureDataLakeSourceOperations,
)
from onyx.connectors.microsoft_utils.entra import (
    EntraDirectoryObject,
    EntraGroup,
    EntraPage,
    EntraUser,
)

ACCOUNT = "onyxtest"
CONTAINER = "perm"
TENANT = "tenant-id"
ACCOUNT_ID = (
    "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Storage/"
    f"storageAccounts/{ACCOUNT}"
)
SCOPE = f"{ACCOUNT_ID}/blobServices/default/containers/{CONTAINER}"
READER_ROLE = (
    "/subscriptions/sub/providers/Microsoft.Authorization/roleDefinitions/reader"
)
DATA_READER_ROLE = (
    "/subscriptions/sub/providers/Microsoft.Authorization/roleDefinitions/data-reader"
)
DATA_OWNER_ROLE = (
    "/subscriptions/sub/providers/Microsoft.Authorization/roleDefinitions/data-owner"
)

OWNER = "owner-id"
RAUNAK = "raunak-id"
SUBASH = "subash-id"
ADMIN = "admin-id"
GUEST = "guest-id"
DISABLED = "disabled-id"
APP = "app-id"
GROUP_A = "group-a"
GROUP_B = "group-b"
RBAC_GROUP = "rbac-readers"

USERS: list[EntraUser] = [
    EntraUser.model_validate({"id": OWNER, "userPrincipalName": "owner@onyx.app"}),
    EntraUser.model_validate({"id": RAUNAK, "userPrincipalName": "raunak@onyx.app"}),
    EntraUser.model_validate({"id": SUBASH, "userPrincipalName": "Subash@onyx.app"}),
    EntraUser.model_validate({"id": ADMIN, "userPrincipalName": "admin@onyx.app"}),
    EntraUser.model_validate(
        {
            "id": GUEST,
            "userPrincipalName": "guest_example.com#EXT#@tenant.onmicrosoft.com",
            "mail": "guest@example.com",
            "userType": "Guest",
        }
    ),
    EntraUser.model_validate(
        {
            "id": DISABLED,
            "userPrincipalName": "gone@onyx.app",
            "accountEnabled": False,
        }
    ),
]
GROUP_MEMBERS: dict[str, set[str]] = {
    GROUP_A: {RAUNAK},
    GROUP_B: {RAUNAK, ADMIN},
    RBAC_GROUP: {SUBASH},
}


def stamp() -> datetime:
    return datetime(2026, 1, 1, tzinfo=timezone.utc)


def directory(name: str) -> AzureDataLakePath:
    return AzureDataLakePath(
        name=name, is_directory=True, last_modified=stamp(), content_length=0
    )


def file(name: str) -> AzureDataLakePath:
    return AzureDataLakePath(
        name=name, is_directory=False, last_modified=stamp(), content_length=10
    )


def access(
    acl: str, owner: str = OWNER, group: str = "$superuser"
) -> AzureDataLakeAccessControl:
    return AzureDataLakeAccessControl(owner=owner, group=group, permissions="", acl=acl)


def role(
    role_id: str, data_actions: list[str], not_data_actions: list[str] | None = None
) -> AzureRoleDefinition:
    return AzureRoleDefinition(
        id=role_id,
        permissions=[
            AzureRolePermission(
                data_actions=data_actions, not_data_actions=not_data_actions or []
            )
        ],
    )


ROLES: dict[str, AzureRoleDefinition] = {
    READER_ROLE: AzureRoleDefinition(
        id=READER_ROLE, permissions=[AzureRolePermission(actions=["*/read"])]
    ),
    DATA_READER_ROLE: role(
        DATA_READER_ROLE,
        ["Microsoft.Storage/storageAccounts/blobServices/containers/blobs/read"],
    ),
    DATA_OWNER_ROLE: role(
        DATA_OWNER_ROLE,
        ["Microsoft.Storage/storageAccounts/blobServices/containers/blobs/*"],
    ),
}


def assignment(
    principal_id: str,
    principal_type: str,
    role_id: str,
    condition: str | None = None,
) -> AzureRoleAssignment:
    return AzureRoleAssignment(
        id=f"{principal_id}-{role_id}",
        principal_id=principal_id,
        principal_type=principal_type,
        role_definition_id=role_id,
        scope=SCOPE,
        condition=condition,
    )


# The test environment: the app and a group read through RBAC, and the
# fixture writer owns the account's data.
ASSIGNMENTS: list[AzureRoleAssignment] = [
    assignment(APP, "ServicePrincipal", DATA_READER_ROLE),
    assignment(APP, "ServicePrincipal", READER_ROLE),
    assignment(OWNER, "User", DATA_OWNER_ROLE),
    assignment(RBAC_GROUP, "Group", DATA_READER_ROLE),
]


def fake_ops(
    acls: dict[str, AzureDataLakeAccessControl],
    assignments: list[AzureRoleAssignment] | None = None,
    denies: list[AzureDenyAssignment] | None = None,
    anonymous_read: bool = False,
    allow_blob_public_access: bool | None = None,
) -> MagicMock:
    """A gateway over one container. ``acls`` maps each path, "" for the
    root, to its access control."""
    ops = create_autospec(AzureDataLakeSourceOperations, instance=True)
    ops.credentials_provider = MagicMock()
    ops.credentials_provider.get_credentials.return_value = {
        "authentication_method": "certificate",
        "adls_client_id": "client",
        "adls_directory_id": TENANT,
    }

    def get_access_control(
        *,
        path: str,
        is_directory: bool,  # noqa: ARG001
    ) -> AzureDataLakeAccessControl:
        if path not in acls:
            raise AzureDataLakeNotFoundError(f"{path} does not exist")
        return acls[path]

    ops.get_access_control.side_effect = get_access_control
    ops.get_container_access.return_value = AzureDataLakeContainerAccess(
        anonymous_read=anonymous_read
    )
    ops.list_subscriptions.return_value = AzureSubscriptionPage(
        subscriptions=[AzureSubscription(subscription_id="sub")]
    )
    ops.list_storage_accounts.return_value = AzureStorageAccountPage(
        accounts=[
            AzureStorageAccountResource(
                id=ACCOUNT_ID,
                name=ACCOUNT,
                allow_blob_public_access=allow_blob_public_access,
            )
        ]
    )
    ops.list_role_assignments.return_value = (
        ASSIGNMENTS if assignments is None else assignments
    )
    ops.get_role_definition.side_effect = lambda *, role_definition_id: ROLES[
        role_definition_id
    ]
    ops.list_deny_assignments.return_value = denies or []
    ops.list_users.return_value = EntraPage[EntraUser](items=USERS)
    ops.list_groups.return_value = EntraPage[EntraGroup](
        items=[EntraGroup(id=group_id) for group_id in GROUP_MEMBERS]
    )

    def members(
        *,
        group_id: str,
        next_link: str | None = None,  # noqa: ARG001
    ) -> EntraPage[EntraDirectoryObject]:
        if group_id not in GROUP_MEMBERS:
            raise AzureDataLakeNotFoundError(f"group {group_id} does not exist")
        return EntraPage[EntraDirectoryObject](
            items=[
                EntraDirectoryObject.model_validate(
                    {"id": user_id, "@odata.type": "#microsoft.graph.user"}
                )
                for user_id in sorted(GROUP_MEMBERS[group_id])
            ]
        )

    ops.list_transitive_group_members.side_effect = members
    return ops
