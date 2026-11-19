"""Who may read the paths of one container. Enterprise Edition resolves it
from Azure RBAC, the container's anonymous access, and the POSIX ACLs."""

from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import cast

from onyx.access.models import ExternalAccess
from onyx.connectors.azure_datalake.models import AzureDataLakePath
from onyx.connectors.azure_datalake.source_operations import (
    AzureDataLakeSourceOperations,
)
from onyx.utils.variable_functionality import (
    fetch_versioned_implementation,
    global_version,
)

_EE_ACCESS_MODULE = "onyx.external_permissions.azure_datalake.access"


class AzureDataLakeAccessWalker(ABC):
    """Resolves access along one walk of the listing, which puts each parent
    directory before its children. Group ids are bare: storage adds the
    source prefix."""

    @abstractmethod
    def container_access(self) -> ExternalAccess:
        """Who may list the container's root directory."""

    @abstractmethod
    def directory_access(self, path: str) -> ExternalAccess:
        """Who may list the directory."""

    @abstractmethod
    def page_access(self, paths: list[AzureDataLakePath]) -> dict[str, ExternalAccess]:
        """Per path of one listing page, in listing order: who may read the
        file, or list the directory."""


def build_access_walker(
    ops: AzureDataLakeSourceOperations,
    account_name: str,
    container_name: str,
) -> AzureDataLakeAccessWalker | None:
    """None outside Enterprise Edition."""
    if not global_version.is_ee_version():
        return None
    build = cast(
        Callable[[AzureDataLakeSourceOperations, str, str], AzureDataLakeAccessWalker],
        fetch_versioned_implementation(_EE_ACCESS_MODULE, "build_access_walker"),
    )
    return build(ops, account_name, container_name)
