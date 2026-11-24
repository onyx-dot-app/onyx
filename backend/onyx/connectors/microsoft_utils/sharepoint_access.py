"""Permission lookups for content in a SharePoint site. The SharePoint
connector uses them, and so does Teams, whose channel files are in SharePoint."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from onyx.connectors.interfaces import RunScopedCache
from onyx.connectors.microsoft_utils.drive_items import DriveItemData
from onyx.connectors.microsoft_utils.models import SharepointSecurable
from onyx.connectors.microsoft_utils.sharepoint_rest import SharepointPermissionReader
from onyx.connectors.models import ExternalAccess
from onyx.db.enums import HierarchyNodeType
from onyx.utils.logger import setup_logger
from onyx.utils.variable_functionality import (
    fetch_versioned_implementation_with_fallback,
)

logger = setup_logger()


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
    """The nested groups of each group that a permission read met, so that a
    group is expanded one time. This one lives in one process."""

    group_expansions: dict[str, SharepointGroupExpansion] = Field(default_factory=dict)

    def get_group_expansion(self, key: str) -> SharepointGroupExpansion | None:
        return self.group_expansions.get(key)

    def set_group_expansion(
        self, key: str, expansion: SharepointGroupExpansion
    ) -> None:
        self.group_expansions[key] = expansion

    # The access of a folder, a library or a site, for the files that have
    # its role assignments and none of their own.
    container_access: dict[str, ExternalAccess] = Field(default_factory=dict)
    # True after the self-check found a file whose own access differs from
    # the access it inherits: each later file reads its own.
    inheritance_off: bool = False

    def get_container_access(self, key: str) -> ExternalAccess | None:
        return self.container_access.get(key)

    def set_container_access(self, key: str, access: ExternalAccess) -> None:
        self.container_access[key] = access

    def is_inheritance_off(self) -> bool:
        return self.inheritance_off

    def turn_inheritance_off(self) -> None:
        self.inheritance_off = True


# The access of a folder, a library or a site is used for this long in one
# listing run. It is short, so that a change to its permissions during a long
# run reaches the files that the run converts later.
CONTAINER_ACCESS_TTL_SECONDS = 600
_CONTAINER_ACCESS_KEY_PREFIX = "sharepoint_container_access"
_INHERITANCE_OFF_KEY = "sharepoint_inheritance_off"

# A shared group expansion lives this long. Each entry is for one listing
# run, so this only bounds the memory of a run that ends early.
GROUP_EXPANSION_TTL_SECONDS = 3600
_GROUP_EXPANSION_KEY_PREFIX = "sharepoint_group_expansion"


class SharedSharepointPermissionCache(SharepointPermissionCache):
    """A permission cache that also keeps each expansion in the cache of the
    listing run, so that the conversion threads of every worker expand a
    group one time in one run. Another run, or a connector with another
    credential, has another run cache, so each run sees access as it is
    when the run reads it. When the run cache cannot be reached, the cache
    works in the process only."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    shared: RunScopedCache

    def get_group_expansion(self, key: str) -> SharepointGroupExpansion | None:
        local = self.group_expansions.get(key)
        if local is not None:
            return local
        raw = self.shared.get(f"{_GROUP_EXPANSION_KEY_PREFIX}:{key}")
        if raw is None:
            return None
        try:
            expansion = SharepointGroupExpansion.model_validate_json(raw)
        except ValueError:
            return None
        self.group_expansions[key] = expansion
        return expansion

    def set_group_expansion(
        self, key: str, expansion: SharepointGroupExpansion
    ) -> None:
        self.group_expansions[key] = expansion
        self.shared.set(
            f"{_GROUP_EXPANSION_KEY_PREFIX}:{key}",
            expansion.model_dump_json(),
            GROUP_EXPANSION_TTL_SECONDS,
        )

    def get_container_access(self, key: str) -> ExternalAccess | None:
        """From the run cache only, where the entry ends after
        CONTAINER_ACCESS_TTL_SECONDS. When the run cache cannot be reached,
        nothing is kept: each file then reads its container again."""
        raw = self.shared.get(f"{_CONTAINER_ACCESS_KEY_PREFIX}:{key}")
        if raw is None:
            return None
        try:
            return ExternalAccess.model_validate_json(raw)
        except ValueError:
            return None

    def set_container_access(self, key: str, access: ExternalAccess) -> None:
        self.shared.set(
            f"{_CONTAINER_ACCESS_KEY_PREFIX}:{key}",
            access.model_dump_json(),
            CONTAINER_ACCESS_TTL_SECONDS,
        )

    def is_inheritance_off(self) -> bool:
        """Off in this process, or in any worker of the run. When the run
        cache cannot be reached, only this process knows: the self-check of
        the other workers then finds a difference again on its own."""
        return self.inheritance_off or self.shared.get(_INHERITANCE_OFF_KEY) is not None

    def turn_inheritance_off(self) -> None:
        self.inheritance_off = True
        self.shared.set(_INHERITANCE_OFF_KEY, "1", GROUP_EXPANSION_TTL_SECONDS)


def _noop_external_access(*args: Any, **kwargs: Any) -> ExternalAccess:  # noqa: ARG001
    return ExternalAccess.empty()


def get_sharepoint_external_access(
    reader: SharepointPermissionReader,
    site_url: str,
    permission_cache: SharepointPermissionCache,
    drive_item: DriveItemData | None = None,
    list_id: str | None = None,
    site_page: dict[str, Any] | None = None,
    treat_sharing_link_as_public: bool = False,
) -> ExternalAccess:
    if drive_item and not list_id:
        raise ValueError("SharePoint permission lookup requires a list ID")

    get_external_access_func = fetch_versioned_implementation_with_fallback(
        "onyx.external_permissions.microsoft_utils.sharepoint_permissions",
        "get_external_access_from_sharepoint",
        fallback=_noop_external_access,
    )

    return get_external_access_func(
        reader=reader,
        site_url=site_url,
        list_id=list_id,
        drive_item=drive_item,
        site_page=site_page,
        treat_sharing_link_as_public=treat_sharing_link_as_public,
        permission_cache=permission_cache,
    )


def get_sharepoint_securable_external_access(
    reader: SharepointPermissionReader,
    site_url: str,
    permission_cache: SharepointPermissionCache,
    securable: SharepointSecurable,
) -> ExternalAccess:
    """The access that the role assignments of ``securable`` give."""
    get_external_access_func = fetch_versioned_implementation_with_fallback(
        "onyx.external_permissions.microsoft_utils.sharepoint_permissions",
        "get_securable_external_access_from_sharepoint",
        fallback=_noop_external_access,
    )
    return get_external_access_func(
        reader=reader,
        site_url=site_url,
        securable=securable,
        permission_cache=permission_cache,
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
        "onyx.external_permissions.microsoft_utils.sharepoint_permissions",
        "get_hierarchy_node_external_access_from_sharepoint",
        fallback=_noop_external_access,
    )
    return get_external_access_func(
        reader=reader,
        site_url=site_url,
        node_type=node_type,
        list_id=list_id,
        folder_server_relative_path=folder_server_relative_path,
        permission_cache=permission_cache,
    )
