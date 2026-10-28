"""Who Azure RBAC lets read every file of a container.

A role assignment at the container scope or above grants read to all files
when its role's data actions include the blob read action and its not-data
actions do not take it away. ACLs are not checked for such a principal. Deny
assignments override role assignments. Assignments with an ABAC condition are
left out and reported, since Onyx cannot evaluate the condition.
"""

import re
from collections.abc import Iterable

from pydantic import BaseModel

from ee.onyx.external_permissions.azure_datalake.principals import (
    EMPTY_SET,
    EntraDirectory,
    PrincipalSet,
    PrincipalTerm,
    exclude_from_set,
    group_term,
    intersect,
    simplify,
    union,
    user_term,
)
from onyx.connectors.azure_datalake.models import (
    AzureDenyAssignment,
    AzurePrincipal,
    AzurePrincipalType,
    AzureRoleAssignment,
    AzureRoleDefinition,
    AzureRolePermission,
    AzureStorageAccountResource,
)
from onyx.connectors.azure_datalake.source_operations import (
    AzureDataLakeSourceOperations,
)
from onyx.connectors.exceptions import ConnectorValidationError

BLOB_READ_DATA_ACTION = (
    "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/read"
)
# A deny assignment's principal that stands for every principal.
_ALL_PRINCIPALS_ID = "00000000-0000-0000-0000-000000000000"
_MAX_SUBSCRIPTION_PAGES = 1_000


class RbacReaders(BaseModel):
    principals: PrincipalSet
    # Assignments of a reading role that carry a condition. They can hide real
    # access, so the checks report them.
    conditioned_assignment_ids: list[str]
    # Readers that are not users or groups, e.g. service principals.
    skipped_principal_ids: list[str]


def _pattern_matches(pattern: str, action: str) -> bool:
    regex: str = ".*".join(re.escape(part) for part in pattern.split("*"))
    return re.fullmatch(regex, action, flags=re.IGNORECASE) is not None


def _matches_any(patterns: Iterable[str], action: str) -> bool:
    return any(_pattern_matches(pattern, action) for pattern in patterns)


def permission_grants(permission: AzureRolePermission, data_action: str) -> bool:
    return _matches_any(permission.data_actions, data_action) and not _matches_any(
        permission.not_data_actions, data_action
    )


def role_reads_blobs(role: AzureRoleDefinition) -> bool:
    """Azure takes the union of a role's permission blocks."""
    return any(
        permission_grants(permission, BLOB_READ_DATA_ACTION)
        for permission in role.permissions
    )


def container_scope(account: AzureStorageAccountResource, container_name: str) -> str:
    return f"{account.id}/blobServices/default/containers/{container_name}"


def find_storage_account(
    ops: AzureDataLakeSourceOperations, account_name: str
) -> AzureStorageAccountResource:
    """The account's ARM resource, from the subscriptions the app can read."""
    subscription_link: str | None = None
    for _ in range(_MAX_SUBSCRIPTION_PAGES):
        subscriptions = ops.list_subscriptions(next_link=subscription_link)
        for subscription in subscriptions.subscriptions:
            account_link: str | None = None
            for _ in range(_MAX_SUBSCRIPTION_PAGES):
                accounts = ops.list_storage_accounts(
                    subscription_id=subscription.subscription_id,
                    next_link=account_link,
                )
                for account in accounts.accounts:
                    if account.name.lower() == account_name.lower():
                        return account
                account_link = accounts.next_link
                if account_link is None:
                    break
        subscription_link = subscriptions.next_link
        if subscription_link is None:
            break
    raise ConnectorValidationError(
        f"The app registration cannot see the storage account '{account_name}' in "
        "Azure Resource Manager. Give it the Reader role on the storage account."
    )


def _principal_term(principal: AzurePrincipal) -> PrincipalTerm | None:
    if principal.type == AzurePrincipalType.USER:
        return user_term(principal.id)
    if principal.type == AzurePrincipalType.GROUP:
        return group_term(principal.id)
    return None


def _denies_read(deny: AzureDenyAssignment, scope: str) -> bool:
    if deny.do_not_apply_to_child_scopes and deny.scope.lower() != scope.lower():
        return False
    return any(
        permission_grants(permission, BLOB_READ_DATA_ACTION)
        for permission in deny.permissions
    )


def _apply_deny(
    readers: PrincipalSet, deny: AzureDenyAssignment, directory: EntraDirectory
) -> PrincipalSet:
    """``readers`` without the principals the deny assignment covers:
    readers - (denied - excluded) = (readers - denied) | (readers & excluded)."""
    excluded: PrincipalSet = simplify(
        term
        for principal in deny.exclude_principals
        if (term := _principal_term(principal)) is not None
    )
    kept: PrincipalSet = (
        intersect(readers, excluded, directory) if excluded else EMPTY_SET
    )
    if any(principal.id == _ALL_PRINCIPALS_ID for principal in deny.principals):
        return kept
    denied_users: frozenset[str] = frozenset(
        principal.id
        for principal in deny.principals
        if principal.type == AzurePrincipalType.USER
    )
    denied_groups: frozenset[str] = frozenset(
        principal.id
        for principal in deny.principals
        if principal.type == AzurePrincipalType.GROUP
    )
    narrowed: PrincipalSet = exclude_from_set(
        readers, denied_users, denied_groups, directory
    )
    return union(narrowed, kept)


def rbac_readers(
    ops: AzureDataLakeSourceOperations,
    scope: str,
    directory: EntraDirectory,
) -> RbacReaders:
    """The principals a role assignment lets read every file under ``scope``,
    the container's ARM id."""
    definitions: dict[str, AzureRoleDefinition] = {}
    terms: list[PrincipalTerm] = []
    conditioned: list[str] = []
    skipped: list[str] = []
    assignments: list[AzureRoleAssignment] = ops.list_role_assignments(scope=scope)
    for assignment in assignments:
        key: str = assignment.role_definition_id.lower()
        if key not in definitions:
            definitions[key] = ops.get_role_definition(
                role_definition_id=assignment.role_definition_id
            )
        if not role_reads_blobs(definitions[key]):
            continue
        if assignment.condition:
            conditioned.append(assignment.id)
            continue
        term = _principal_term(
            AzurePrincipal(id=assignment.principal_id, type=assignment.principal_type)
        )
        if term is None:
            skipped.append(assignment.principal_id)
            continue
        terms.append(term)
    readers: PrincipalSet = simplify(terms)
    if readers:
        for deny in ops.list_deny_assignments(scope=scope):
            if _denies_read(deny, scope):
                readers = _apply_deny(readers, deny, directory)
    return RbacReaders(
        principals=readers,
        conditioned_assignment_ids=conditioned,
        skipped_principal_ids=skipped,
    )
