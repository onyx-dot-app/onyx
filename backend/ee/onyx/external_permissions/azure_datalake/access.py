"""Who may read each path of an Azure Data Lake Storage container.

A file's readers are its RBAC readers, plus those its ACLs let reach it: read
on the file and execute on every directory above it, the container root
included. The walk computes the traversal set of each directory once, as its
parent's set intersected with the directory's execute set, and keeps only the
directories on the current path. A container with anonymous access is public.
A term with exclusions becomes an exclusion group (``exclusion_groups``).
"""

import posixpath
from collections.abc import Callable

from ee.onyx.external_permissions.azure_datalake.acl import AclBit, granted_principals
from ee.onyx.external_permissions.azure_datalake.directory import (
    GraphDirectory,
    GroupMembersUnreadableError,
    entra_tenant_id,
    everyone_group_id,
)
from ee.onyx.external_permissions.azure_datalake.exclusion_groups import (
    exclusion_group_id,
)
from ee.onyx.external_permissions.azure_datalake.principals import (
    ExpansionLimitError,
    PrincipalSet,
    ResolvedPrincipals,
    intersect,
    resolve,
    union,
)
from ee.onyx.external_permissions.azure_datalake.rbac import (
    RbacReaders,
    container_scope,
    find_storage_account,
    rbac_readers,
)
from onyx.access.models import ExternalAccess
from onyx.configs.app_configs import AZURE_DATALAKE_ACL_READ_CONCURRENCY
from onyx.connectors.azure_datalake.access import AzureDataLakeAccessWalker
from onyx.connectors.azure_datalake.models import (
    AzureDataLakeAccessControl,
    AzureDataLakePath,
    AzureStorageAccountResource,
)
from onyx.connectors.azure_datalake.source_operations import (
    AzureDataLakeNotFoundError,
    AzureDataLakeSourceOperations,
)
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import run_functions_tuples_in_parallel

logger = setup_logger()

# The container's root directory, as the listing names paths.
ROOT = ""


def _parent(path: str) -> str:
    return posixpath.dirname(path)


def _on_path(directory: str, path_directory: str) -> bool:
    """Whether ``directory`` is ``path_directory`` or one above it."""
    return (
        directory == ROOT
        or directory == path_directory
        or path_directory.startswith(f"{directory}/")
    )


class AzureDataLakeAccessResolver(AzureDataLakeAccessWalker):
    def __init__(
        self,
        ops: AzureDataLakeSourceOperations,
        account_name: str,
        container_name: str,
        max_users: int = ExternalAccess.MAX_NUM_ENTRIES,
    ) -> None:
        self._ops = ops
        self._account_name = account_name
        self._container_name = container_name
        self._max_users = max_users
        self._directory = GraphDirectory(ops)
        self._tenant_id: str | None = None
        self._everyone_group_id: str | None = None
        self._account: AzureStorageAccountResource | None = None
        self._rbac: PrincipalSet | None = None
        self._public: bool | None = None
        # Directory path -> who may reach its children. Holds only the
        # directories on the walk's current path.
        self._traversal: dict[str, PrincipalSet] = {}

    def _storage_account(self) -> AzureStorageAccountResource:
        if self._account is None:
            self._account = find_storage_account(self._ops, self._account_name)
        return self._account

    def _rbac_readers(self) -> PrincipalSet:
        if self._rbac is None:
            readers: RbacReaders = rbac_readers(
                self._ops,
                container_scope(self._storage_account(), self._container_name),
                self._directory,
            )
            if readers.conditioned_assignment_ids:
                logger.warning(
                    "Azure Data Lake container %s/%s: role assignments with "
                    "conditions are left out of permission sync: %s",
                    self._account_name,
                    self._container_name,
                    readers.conditioned_assignment_ids,
                )
            self._rbac = readers.principals
        return self._rbac

    def _is_public(self) -> bool:
        """Anonymous reads need both the container's access level and the
        account's permission for it."""
        if self._public is None:
            self._public = (
                self._ops.get_container_access().anonymous_read
                and self._storage_account().allow_blob_public_access is not False
            )
        return self._public

    def _everyone(self) -> str:
        if self._everyone_group_id is None:
            self._everyone_group_id = everyone_group_id(self._ops)
        return self._everyone_group_id

    def _tenant(self) -> str:
        if self._tenant_id is None:
            self._tenant_id = entra_tenant_id(self._ops)
        return self._tenant_id

    def _external_access(
        self, acl_readers: Callable[[], PrincipalSet], name: str
    ) -> ExternalAccess:
        if self._is_public():
            return ExternalAccess.public()
        # Outside the fallback below: RBAC is read once, and an error in it
        # fails the sync rather than every document.
        rbac: PrincipalSet = self._rbac_readers()
        try:
            resolved: ResolvedPrincipals = resolve(
                union(rbac, acl_readers()), self._directory, self._max_users
            )
            group_ids: set[str] = resolved.group_ids | {
                exclusion_group_id(term, self._tenant())
                for term in resolved.exclusion_terms
            }
        except (ExpansionLimitError, GroupMembersUnreadableError) as e:
            logger.error("Azure Data Lake path %s stays private: %s", name, e)
            return ExternalAccess.empty()
        if resolved.everyone:
            group_ids.add(self._everyone())
        return ExternalAccess(
            external_user_emails=resolved.user_emails,
            external_user_group_ids=group_ids,
            is_public=False,
        )

    def _read_acl(self, path: str, is_directory: bool) -> AzureDataLakeAccessControl:
        return self._ops.get_access_control(path=path, is_directory=is_directory)

    def _read_acl_if_present(
        self, path: str, is_directory: bool
    ) -> AzureDataLakeAccessControl | None:
        try:
            return self._read_acl(path, is_directory)
        except AzureDataLakeNotFoundError:
            logger.info("Azure Data Lake path %s was deleted during the walk", path)
            return None

    def _reach(
        self, directory: str, known: dict[str, AzureDataLakeAccessControl | None]
    ) -> PrincipalSet:
        """Who may reach the children of ``directory``: execute on it and on
        every directory above it."""
        cached: PrincipalSet | None = self._traversal.get(directory)
        if cached is not None:
            return cached
        acl: AzureDataLakeAccessControl | None = (
            known[directory]
            if directory in known
            else self._read_acl_if_present(directory, True)
        )
        executors: PrincipalSet = (
            granted_principals(acl, AclBit.EXECUTE) if acl is not None else frozenset()
        )
        reach: PrincipalSet = (
            executors
            if directory == ROOT
            else intersect(
                self._reach(_parent(directory), known), executors, self._directory
            )
        )
        self._traversal[directory] = reach
        return reach

    def _leave_other_directories(self, path_directory: str) -> None:
        self._traversal = {
            directory: reach
            for directory, reach in self._traversal.items()
            if _on_path(directory, path_directory)
        }

    def _readers(
        self,
        path: str,
        is_directory: bool,
        acl: AzureDataLakeAccessControl | None,
        known: dict[str, AzureDataLakeAccessControl | None],
    ) -> PrincipalSet:
        """ACL readers of a file: read on it, and reach from its parent. Of a
        directory, its listers: read and execute on it, and reach."""
        if acl is None:
            return frozenset()
        readers: PrincipalSet = granted_principals(acl, AclBit.READ)
        if is_directory:
            readers = intersect(
                readers, granted_principals(acl, AclBit.EXECUTE), self._directory
            )
        if path == ROOT:
            return readers
        return intersect(self._reach(_parent(path), known), readers, self._directory)

    def container_access(self) -> ExternalAccess:
        root_acl = self._read_acl_if_present(ROOT, True)
        return self._external_access(
            lambda: self._readers(ROOT, True, root_acl, {}), "/"
        )

    def directory_access(self, path: str) -> ExternalAccess:
        self._leave_other_directories(_parent(path))
        acl = self._read_acl_if_present(path, True)
        return self._external_access(
            lambda: self._readers(path, True, acl, {path: acl}), path
        )

    def page_access(self, paths: list[AzureDataLakePath]) -> dict[str, ExternalAccess]:
        acls: list[AzureDataLakeAccessControl | None] = (
            run_functions_tuples_in_parallel(
                [
                    (self._read_acl_if_present, (path.name, path.is_directory))
                    for path in paths
                ],
                max_workers=AZURE_DATALAKE_ACL_READ_CONCURRENCY,
            )
        )
        known: dict[str, AzureDataLakeAccessControl | None] = {
            path.name: acl
            for path, acl in zip(paths, acls, strict=True)
            if path.is_directory
        }
        access: dict[str, ExternalAccess] = {}
        for path, acl in zip(paths, acls, strict=True):
            self._leave_other_directories(_parent(path.name))
            access[path.name] = self._external_access(
                lambda path=path, acl=acl: self._readers(
                    path.name, path.is_directory, acl, known
                ),
                path.name,
            )
        return access


def build_access_walker(
    ops: AzureDataLakeSourceOperations, account_name: str, container_name: str
) -> AzureDataLakeAccessWalker:
    return AzureDataLakeAccessResolver(ops, account_name, container_name)
