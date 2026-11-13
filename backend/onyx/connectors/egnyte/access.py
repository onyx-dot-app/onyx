from collections.abc import Callable
from typing import cast

from onyx.access.models import ExternalAccess
from onyx.connectors.egnyte.models import EgnyteDirectory, EgnytePermissions
from onyx.connectors.egnyte.source_operations import EgnyteSourceOperations
from onyx.utils.variable_functionality import (
    fetch_versioned_implementation,
    global_version,
)

_EE_ACCESS_MODULE: str = "onyx.external_permissions.egnyte.access"


class EgnyteUnknownGroupError(RuntimeError):
    """A folder grants a group that is neither a custom group nor a default
    one. Dropping it could hide the folder from its readers without a trace,
    so the folder's access cannot be built."""


def load_directory(ops: EgnyteSourceOperations) -> EgnyteDirectory | None:
    if not global_version.is_ee_version():
        return None
    ee_build_directory = cast(
        Callable[[EgnyteSourceOperations], EgnyteDirectory],
        fetch_versioned_implementation(_EE_ACCESS_MODULE, "build_directory"),
    )
    return ee_build_directory(ops)


def get_folder_access(
    domain: str,
    permissions: EgnytePermissions | None,
    directory: EgnyteDirectory,
) -> ExternalAccess | None:
    if not global_version.is_ee_version():
        return None
    ee_folder_access = cast(
        Callable[[str, EgnytePermissions | None, EgnyteDirectory], ExternalAccess],
        fetch_versioned_implementation(_EE_ACCESS_MODULE, "folder_access"),
    )
    return ee_folder_access(domain, permissions, directory)
