"""The principal rules SharePoint permission sync and its checks share: which
principal types name groups, which role assignments grant nothing, which login
names mean everyone, and how a group SharePoint names resolves to its Entra id."""

import re
from enum import IntEnum

from onyx.connectors.microsoft_utils.models import (
    SharepointPrincipal,
    SharepointRoleAssignment,
)
from onyx.connectors.microsoft_utils.sharepoint_rest import EntraGroupReader
from onyx.utils.logger import setup_logger

logger = setup_logger()


class SharepointPrincipalType(IntEnum):
    USER = 1
    ANONYMOUS_USER = 3
    ENTRA_GROUP = 4
    # A site group, local to the site.
    SHAREPOINT_GROUP = 8


GROUP_PRINCIPAL_TYPES = frozenset(
    {SharepointPrincipalType.ENTRA_GROUP, SharepointPrincipalType.SHAREPOINT_GROUP}
)
# PnP RoleType defines Guest=1 and RestrictedGuest=9:
# https://github.com/pnp/pnpcore/blob/4e4f58fcac797f2957bfcd14fedcecd690dfe7ee/src/sdk/PnP.Core/Model/SharePoint/Core/Public/Enums/RoleType.cs
LIMITED_ACCESS_ROLE_TYPES = frozenset({1, 9})
GUID_RE = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
# https://learn.microsoft.com/en-us/answers/questions/2085339/guid-in-the-loginname-of-site-user-everyone-except
_PUBLIC_LOGIN_PATTERNS = ("c:0-.f|rolemanager|spo-grid-all-users/", "c:0(.s|true")


def has_only_limited_access(assignment: SharepointRoleAssignment) -> bool:
    return bool(assignment.role_type_kinds) and all(
        kind in LIMITED_ACCESS_ROLE_TYPES for kind in assignment.role_type_kinds
    )


def granting_members(
    assignments: list[SharepointRoleAssignment],
) -> list[SharepointPrincipal]:
    """The members of assignments that grant more than Limited Access."""
    members: list[SharepointPrincipal] = []
    for assignment in assignments:
        logger.debug("Assignment: %s", assignment)
        if has_only_limited_access(assignment):
            logger.info("Skipping Limited Access-only assignment")
            continue
        if assignment.member:
            members.append(assignment.member)
    return members


def is_public_login_name(login_name: str) -> bool:
    for pattern in _PUBLIC_LOGIN_PATTERNS:
        if pattern in login_name:
            logger.info("Login name %s is public", login_name)
            return True
    return False


def extract_guid(text: str) -> str | None:
    """Pull the first GUID out of a string such as a SharePoint claims token."""
    try:
        match = re.search(f"({GUID_RE})", text, re.IGNORECASE)
        if match:
            return match.group(1)

        return None

    except Exception as e:
        logger.error("Failed to extract GUID from %s: %s", text, e)
        return None


def find_group_id_by_name(reader: EntraGroupReader, display_name: str) -> str | None:
    try:
        return reader.find_entra_group_id(display_name=display_name)
    except Exception as e:
        logger.error("Failed to get Entra group id for name %s: %s", display_name, e)
        return None


def resolve_group_id(reader: EntraGroupReader, identifier: str) -> str | None:
    """Resolve a GUID, a SharePoint claims token, or a display name to a group id."""
    try:
        if re.match(f"^{GUID_RE}$", identifier, re.IGNORECASE):
            return identifier

        if identifier.startswith("c:0") and "|" in identifier:
            guid = extract_guid(identifier)
            if guid:
                logger.info("Extracted GUID %s from claims token %s", guid, identifier)
                return guid

        return find_group_id_by_name(reader, identifier)

    except Exception as e:
        logger.error("Failed to resolve group id from %s: %s", identifier, e)
        return None
