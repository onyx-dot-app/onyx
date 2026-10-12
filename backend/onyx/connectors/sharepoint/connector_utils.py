from typing import Any

from pydantic import BaseModel, Field, field_serializer

from onyx.connectors.microsoft_utils.drive_items import DriveItemData
from onyx.connectors.microsoft_utils.sharepoint_rest import SharepointPermissionReader
from onyx.connectors.models import ExternalAccess
from onyx.db.enums import HierarchyNodeType
from onyx.utils.variable_functionality import (
    fetch_versioned_implementation_with_fallback,
)


class SharepointGroup(BaseModel):
    model_config = {"frozen": True}

    name: str
    login_name: str
    principal_type: int


class SharepointGroupExpansion(BaseModel):
    nested_groups: set[SharepointGroup]

    @field_serializer("nested_groups")
    def serialize_nested_groups(
        self, nested_groups: set[SharepointGroup]
    ) -> list[SharepointGroup]:
        return list(nested_groups)


class SharepointPermissionCache(BaseModel):
    group_expansions: dict[str, SharepointGroupExpansion] = Field(default_factory=dict)


def _noop_external_access(*args: Any, **kwargs: Any) -> ExternalAccess:  # noqa: ARG001
    return ExternalAccess.empty()


def get_sharepoint_external_access(
    reader: SharepointPermissionReader,
    site_url: str,
    permission_cache: SharepointPermissionCache,
    drive_item: DriveItemData | None = None,
    list_id: str | None = None,
    site_page: dict[str, Any] | None = None,
    add_prefix: bool = False,
    treat_sharing_link_as_public: bool = False,
) -> ExternalAccess:
    if drive_item and not list_id:
        raise ValueError("SharePoint permission lookup requires a list ID")

    get_external_access_func = fetch_versioned_implementation_with_fallback(
        "onyx.external_permissions.sharepoint.permission_utils",
        "get_external_access_from_sharepoint",
        fallback=_noop_external_access,
    )

    return get_external_access_func(
        reader,
        site_url,
        list_id,
        drive_item,
        site_page,
        add_prefix,
        treat_sharing_link_as_public,
        permission_cache,
    )


def get_sharepoint_hierarchy_node_external_access(
    reader: SharepointPermissionReader,
    site_url: str,
    permission_cache: SharepointPermissionCache,
    node_type: HierarchyNodeType,
    list_id: str | None = None,
    folder_server_relative_path: str | None = None,
) -> ExternalAccess:
    if node_type == HierarchyNodeType.DRIVE and not list_id:
        raise ValueError("SharePoint permission lookup requires a list ID")

    get_external_access_func = fetch_versioned_implementation_with_fallback(
        "onyx.external_permissions.sharepoint.permission_utils",
        "get_hierarchy_node_external_access_from_sharepoint",
        fallback=_noop_external_access,
    )
    return get_external_access_func(
        reader,
        site_url,
        node_type,
        list_id,
        folder_server_relative_path,
        permission_cache,
    )
