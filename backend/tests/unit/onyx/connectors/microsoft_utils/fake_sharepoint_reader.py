"""An in-memory SharepointPermissionReader for the permission-logic tests."""

from pydantic import BaseModel, ConfigDict

from onyx.connectors.microsoft_utils.drive_items import DriveItemData
from onyx.connectors.microsoft_utils.entra import (
    EntraDirectoryObject,
    EntraGroup,
    EntraPage,
)
from onyx.connectors.microsoft_utils.models import (
    EntraMember,
    SharepointPrincipal,
    SharepointRoleAssignment,
    SharepointSecurable,
)
from onyx.connectors.microsoft_utils.sharepoint_rest import (
    SharepointPermissionReader,
)


class ReaderCall(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    operation: str
    site_url: str | None = None
    securable: SharepointSecurable | None = None
    key: str | None = None


class FakeSharepointReader(SharepointPermissionReader):
    """Answers from dicts keyed the way each read is addressed. A value that is
    an exception is raised instead."""

    def __init__(
        self,
        *,
        role_assignments: dict[str, list[SharepointRoleAssignment]] | None = None,
        site_group_users: dict[str, list[SharepointPrincipal] | Exception]
        | None = None,
        folder_ids: dict[str, str] | None = None,
        list_item_ids: dict[str, int | None] | None = None,
        link_scopes: dict[str, list[str] | Exception] | None = None,
        entra_group_ids: dict[str, str | None] | None = None,
        entra_members: dict[str, list[EntraMember] | Exception] | None = None,
        nested_entra_groups: dict[str, list[EntraGroup] | Exception] | None = None,
        entra_groups: list[EntraGroup] | None = None,
        entra_group_member_objects: dict[str, list[EntraDirectoryObject]] | None = None,
    ) -> None:
        # Role assignments are keyed by site URL. One site answers alike for
        # every securable.
        self.role_assignments = role_assignments or {}
        self.site_group_users = site_group_users or {}
        self.folder_ids = folder_ids or {}
        self.list_item_ids = list_item_ids or {}
        self.link_scopes = link_scopes or {}
        self.entra_group_ids = entra_group_ids or {}
        self.entra_members = entra_members or {}
        self.nested_entra_groups = nested_entra_groups or {}
        self.entra_groups = entra_groups or []
        self.entra_group_member_objects = entra_group_member_objects or {}
        self.calls: list[ReaderCall] = []

    def list_role_assignments(
        self, *, site_url: str, securable: SharepointSecurable
    ) -> list[SharepointRoleAssignment]:
        self.calls.append(
            ReaderCall(
                operation="list_role_assignments",
                site_url=site_url,
                securable=securable,
            )
        )
        return self.role_assignments.get(site_url, [])

    def list_site_group_users(
        self, *, site_url: str, group_name: str
    ) -> list[SharepointPrincipal]:
        self.calls.append(
            ReaderCall(
                operation="list_site_group_users", site_url=site_url, key=group_name
            )
        )
        users = self.site_group_users.get(group_name, [])
        if isinstance(users, Exception):
            raise users
        return users

    def get_folder_unique_id(self, *, site_url: str, server_relative_path: str) -> str:
        self.calls.append(
            ReaderCall(
                operation="get_folder_unique_id",
                site_url=site_url,
                key=server_relative_path,
            )
        )
        return self.folder_ids[server_relative_path]

    def get_list_item_id(self, *, item: DriveItemData) -> int | None:
        self.calls.append(ReaderCall(operation="get_list_item_id", key=item.id))
        return self.list_item_ids.get(item.id)

    def list_sharing_link_scopes(self, *, item: DriveItemData) -> list[str]:
        self.calls.append(ReaderCall(operation="list_sharing_link_scopes", key=item.id))
        scopes = self.link_scopes.get(item.id, [])
        if isinstance(scopes, Exception):
            raise scopes
        return scopes

    def find_entra_group_id(self, *, display_name: str) -> str | None:
        self.calls.append(ReaderCall(operation="find_entra_group_id", key=display_name))
        return self.entra_group_ids.get(display_name)

    def list_entra_group_members(self, *, group_id: str) -> list[EntraMember]:
        self.calls.append(
            ReaderCall(operation="list_entra_group_members", key=group_id)
        )
        members = self.entra_members.get(group_id, [])
        if isinstance(members, Exception):
            raise members
        return members

    def list_nested_entra_groups(self, *, group_id: str) -> list[EntraGroup]:
        self.calls.append(
            ReaderCall(operation="list_nested_entra_groups", key=group_id)
        )
        groups = self.nested_entra_groups.get(group_id, [])
        if isinstance(groups, Exception):
            raise groups
        return groups

    def list_entra_groups(
        self, *, next_link: str | None = None
    ) -> EntraPage[EntraGroup]:
        self.calls.append(ReaderCall(operation="list_entra_groups", key=next_link))
        return EntraPage(items=self.entra_groups)

    def list_entra_group_member_page(
        self,
        *,
        group_id: str,
        next_link: str | None = None,  # noqa: ARG002
    ) -> EntraPage[EntraDirectoryObject]:
        self.calls.append(
            ReaderCall(operation="list_entra_group_member_page", key=group_id)
        )
        return EntraPage(items=self.entra_group_member_objects.get(group_id, []))

    def operations(self) -> list[str]:
        return [call.operation for call in self.calls]
