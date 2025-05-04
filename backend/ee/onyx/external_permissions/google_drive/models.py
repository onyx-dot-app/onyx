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
    permission_type: str
    # this is "reader", "writer", "owner", etc.
    role: str
    # this is the id of the parent permission
    inherited_from: str | None
    # this is a boolean that indicates if the permission is inherited
    inherited: bool


class GoogleDrivePermission(BaseModel):
    id: str
    email_address: str  # groups are also represented as email addresses within Drive
    type: PermissionType
    domain: str | None  # only applies to domain permissions
    permission_details: GoogleDrivePermissionDetails

    @classmethod
    def from_drive_permission(
        cls, drive_permission: dict[str, Any]
    ) -> "GoogleDrivePermission":
        return cls(
            id=drive_permission["id"],
            email_address=drive_permission["emailAddress"],
            type=PermissionType(drive_permission["type"]),
            domain=drive_permission.get("domain"),
            permission_details=GoogleDrivePermissionDetails(
                permission_type=drive_permission["permissionDetails"]["type"],
                role=drive_permission["permissionDetails"]["role"],
                inherited_from=drive_permission["permissionDetails"]["inheritedFrom"],
                inherited=drive_permission["permissionDetails"]["inherited"],
            ),
        )
