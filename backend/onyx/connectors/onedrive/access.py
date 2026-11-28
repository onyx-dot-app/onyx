from collections.abc import Callable
from typing import cast

from onyx.access.models import ExternalAccess
from onyx.connectors.onedrive.models import OneDrivePermission
from onyx.utils.variable_functionality import (
    fetch_versioned_implementation,
    global_version,
)


def get_onedrive_external_access(
    permissions: list[OneDrivePermission],
    owner_email: str,
    treat_organization_link_as_public: bool,
) -> ExternalAccess:
    if not global_version.is_ee_version():
        return ExternalAccess.empty()

    mapper = cast(
        Callable[[list[OneDrivePermission], str, bool], ExternalAccess],
        fetch_versioned_implementation(
            "onyx.external_permissions.onedrive.permission_mapper",
            "map_onedrive_permissions",
        ),
    )
    return mapper(
        permissions,
        owner_email,
        treat_organization_link_as_public,
    )
