"""Who may read the files and folders of one share. Enterprise Edition
resolves it from each one's NTFS access list and Active Directory."""

from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import cast

from onyx.access.models import ExternalAccess
from onyx.connectors.smb.models import EmailAttribute
from onyx.connectors.smb.source_operations import SmbSourceOperations
from onyx.utils.variable_functionality import (
    fetch_versioned_implementation,
    global_version,
)

_EE_ACCESS_MODULE = "onyx.external_permissions.smb.access"


class SmbAccessWalker(ABC):
    """Resolves access along one walk of the share. Group ids are bare:
    storage adds the source prefix."""

    @abstractmethod
    def paths_access(self, paths: list[str]) -> dict[str, ExternalAccess]:
        """Per path: who may read the file, or list the folder. An empty path
        is the share root. Every path gets an entry."""


def build_access_walker(
    ops: SmbSourceOperations, email_attribute: EmailAttribute
) -> SmbAccessWalker | None:
    """None outside Enterprise Edition."""
    if not global_version.is_ee_version():
        return None
    build = cast(
        Callable[[SmbSourceOperations, EmailAttribute], SmbAccessWalker],
        fetch_versioned_implementation(_EE_ACCESS_MODULE, "build_access_walker"),
    )
    return build(ops, email_attribute)
