from enum import Enum
from typing import Any

from pydantic import BaseModel


class PermissionType(str, Enum):
    USER = "user"
    GROUP = "group"
    DOMAIN = "domain"
    ANYONE = "anyone"


class GoogleDrivePermissionDetails(BaseModel):
    # this is "file", "member", etc.
    # different from the `type` field within `GoogleDrivePermission`
    # Sometimes can be not, although not sure why...
    permission_type: str | None
    # this is "reader", "writer", "owner", etc.
    role: str
    # this is the id of the parent permission
    inherited_from: str | None


class GoogleDrivePermission(BaseModel):
    id: str
    # groups are also represented as email addresses within Drive
    # will be None for domain/global permissions
    email_address: str | None
    type: PermissionType
    domain: str | None  # only applies to domain permissions
    permission_details: GoogleDrivePermissionDetails | None

    @classmethod
    def from_drive_permission(
        cls, drive_permission: dict[str, Any]
    ) -> "GoogleDrivePermission":
        # we seem to only get details for permissions that are inherited
        # we can get multiple details if a permission is inherited from multiple
        permission_details_list = drive_permission.get("permissionDetails", [])
        permission_details: dict[str, Any] | None = (
            permission_details_list[0] if permission_details_list else None
        )
        return cls(
            id=drive_permission["id"],
            email_address=drive_permission.get("emailAddress"),
            type=PermissionType(drive_permission["type"]),
            domain=drive_permission.get("domain"),
            permission_details=(
                GoogleDrivePermissionDetails(
                    permission_type=permission_details.get("type"),
                    role=permission_details.get("role", ""),
                    inherited_from=permission_details.get("inheritedFrom"),
                )
                if permission_details
                else None
            ),
        )

    @property
    def inherited_from(self) -> str | None:
        if self.permission_details:
            return self.permission_details.inherited_from
        return None
