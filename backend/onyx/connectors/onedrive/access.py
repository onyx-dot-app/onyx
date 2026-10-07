from collections.abc import Callable
from typing import cast

from onyx.access.models import ExternalAccess
from onyx.access.utils import build_ext_group_name_for_onyx
from onyx.configs.constants import DocumentSource
from onyx.connectors.onedrive.models import OneDrivePermission
from onyx.utils.variable_functionality import (
    fetch_versioned_implementation,
    global_version,
)


def get_onedrive_external_access(
    permissions: list[OneDrivePermission],
    owner_email: str,
    treat_organization_link_as_public: bool,
    *,
    add_prefix: bool,
) -> ExternalAccess:
    if not global_version.is_ee_version():
        return ExternalAccess.empty()

    mapper = cast(
        Callable[[list[OneDrivePermission], str, bool, bool], ExternalAccess],
        fetch_versioned_implementation(
            "onyx.external_permissions.onedrive.permission_mapper",
            "map_onedrive_permissions",
        ),
    )
    return mapper(
        permissions,
        owner_email,
        treat_organization_link_as_public,
        add_prefix,
    )


def prefix_onedrive_external_groups(access: ExternalAccess) -> ExternalAccess:
    return ExternalAccess(
        external_user_emails=access.external_user_emails,
        external_user_group_ids={
            build_ext_group_name_for_onyx(group_id, DocumentSource.ONEDRIVE)
            for group_id in access.external_user_group_ids
        },
        is_public=access.is_public,
    )
