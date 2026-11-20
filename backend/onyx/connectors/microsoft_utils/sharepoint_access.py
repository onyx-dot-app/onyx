"""Permission lookups for content in a SharePoint site. The SharePoint
connector uses them, and so does Teams, whose channel files are in SharePoint."""

import hashlib
from typing import Any

from pydantic import BaseModel, Field, field_serializer

# no-direct-redis: allow indexing shares the group expansions between workers
from redis.exceptions import RedisError

from onyx.connectors.microsoft_utils.drive_items import DriveItemData
from onyx.connectors.microsoft_utils.sharepoint_rest import SharepointPermissionReader
from onyx.connectors.models import ExternalAccess
from onyx.db.enums import HierarchyNodeType

# no-direct-redis: allow indexing shares the group expansions between workers
from onyx.redis.redis_pool import get_redis_client
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


# A group expansion in Redis is used for this long. A change to the nested
# groups of a group shows in indexed access after at most this time, and the
# group sync still corrects the members.
GROUP_EXPANSION_TTL_SECONDS = 3600
_GROUP_EXPANSION_KEY_PREFIX = "sharepoint_group_expansion"


class SharedSharepointPermissionCache(SharepointPermissionCache):
    """A permission cache that also keeps each expansion in Redis, so that the
    conversion threads of every worker expand a group one time. The key holds
    the site for a SharePoint group and the object id for an Entra group.
    When Redis cannot be reached, the cache works in the process only."""

    @staticmethod
    def _redis_key(key: str) -> str:
        digest = hashlib.sha256(key.encode()).hexdigest()
        return f"{_GROUP_EXPANSION_KEY_PREFIX}:{digest}"

    def get_group_expansion(self, key: str) -> SharepointGroupExpansion | None:
        local = self.group_expansions.get(key)
        if local is not None:
            return local
        try:
            # no-direct-redis: allow indexing shares the group expansions between workers
            raw = get_redis_client().get(self._redis_key(key))
        except RedisError:
            return None
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
        try:
            # no-direct-redis: allow indexing shares the group expansions between workers
            get_redis_client().set(
                self._redis_key(key),
                expansion.model_dump_json(),
                ex=GROUP_EXPANSION_TTL_SECONDS,
            )
        except RedisError as error:
            logger.warning("Could not store a SharePoint group expansion: %s", error)


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
