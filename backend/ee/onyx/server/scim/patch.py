"""SCIM PATCH operation handler (RFC 7644 §3.5.2).

Identity providers use PATCH to make incremental changes to SCIM resources
instead of replacing the entire resource with PUT. Common operations include:

  - Deactivating a user: ``replace`` ``active`` with ``false``
  - Adding group members: ``add`` to ``members``
  - Removing group members: ``remove`` from ``members[value eq "..."]``

This module applies PATCH operations to Pydantic SCIM resource objects and
returns the modified result. It does NOT touch the database — the caller is
responsible for persisting changes.
"""

from __future__ import annotations

import re

from ee.onyx.server.scim.models import ScimGroupResource
from ee.onyx.server.scim.models import ScimPatchOperation
from ee.onyx.server.scim.models import ScimPatchOperationType
from ee.onyx.server.scim.models import ScimUserResource


class ScimPatchError(Exception):
    """Raised when a PATCH operation cannot be applied."""

    def __init__(self, detail: str, status: int = 400) -> None:
        self.detail = detail
        self.status = status
        super().__init__(detail)


# Pattern for member removal path: members[value eq "user-id"]
_MEMBER_FILTER_RE = re.compile(
    r'^members\[value\s+eq\s+"([^"]+)"\]$',
    re.IGNORECASE,
)


def apply_user_patch(
    operations: list[ScimPatchOperation],
    current: ScimUserResource,
) -> ScimUserResource:
    """Apply SCIM PATCH operations to a user resource.

    Returns a new ``ScimUserResource`` with the modifications applied.
    The original object is not mutated.

    Raises:
        ScimPatchError: If an operation targets an unsupported path.
    """
    data = current.model_dump()
    name_data = data.get("name") or {}

    for op in operations:
        if op.op == ScimPatchOperationType.REPLACE:
            _apply_user_replace(op, data, name_data)
        elif op.op == ScimPatchOperationType.ADD:
            _apply_user_replace(op, data, name_data)
        else:
            raise ScimPatchError(
                f"Unsupported operation '{op.op.value}' on User resource"
            )

    data["name"] = name_data
    return ScimUserResource.model_validate(data)


def _apply_user_replace(
    op: ScimPatchOperation,
    data: dict,
    name_data: dict,
) -> None:
    """Apply a replace/add operation to user data."""
    path = (op.path or "").lower()

    if not path:
        # No path — value is a dict of top-level attributes to set
        if isinstance(op.value, dict):
            for key, val in op.value.items():
                _set_user_field(key.lower(), val, data, name_data)
        else:
            raise ScimPatchError("Replace without path requires a dict value")
        return

    _set_user_field(path, op.value, data, name_data)


def _set_user_field(
    path: str,
    value: str | bool | dict | list | None,
    data: dict,
    name_data: dict,
) -> None:
    """Set a single field on user data by SCIM path."""
    if path == "active":
        data["active"] = value
    elif path == "username":
        data["userName"] = value
    elif path == "externalid":
        data["externalId"] = value
    elif path == "name.givenname":
        name_data["givenName"] = value
    elif path == "name.familyname":
        name_data["familyName"] = value
    elif path == "name.formatted":
        name_data["formatted"] = value
    elif path == "displayname":
        # Some IdPs send displayName on users; map to formatted name
        name_data["formatted"] = value
    else:
        raise ScimPatchError(f"Unsupported path '{path}' for User PATCH")


def apply_group_patch(
    operations: list[ScimPatchOperation],
    current: ScimGroupResource,
) -> tuple[ScimGroupResource, list[str], list[str]]:
    """Apply SCIM PATCH operations to a group resource.

    Returns:
        A tuple of (modified group, added member IDs, removed member IDs).
        The caller uses the member ID lists to update the database.

    Raises:
        ScimPatchError: If an operation targets an unsupported path.
    """
    data = current.model_dump()
    current_members: list[dict] = list(data.get("members") or [])
    added_ids: list[str] = []
    removed_ids: list[str] = []

    for op in operations:
        if op.op == ScimPatchOperationType.REPLACE:
            _apply_group_replace(op, data, current_members, added_ids, removed_ids)
        elif op.op == ScimPatchOperationType.ADD:
            _apply_group_add(op, current_members, added_ids)
        elif op.op == ScimPatchOperationType.REMOVE:
            _apply_group_remove(op, current_members, removed_ids)
        else:
            raise ScimPatchError(
                f"Unsupported operation '{op.op.value}' on Group resource"
            )

    data["members"] = current_members
    group = ScimGroupResource.model_validate(data)
    return group, added_ids, removed_ids


def _apply_group_replace(
    op: ScimPatchOperation,
    data: dict,
    current_members: list[dict],
    added_ids: list[str],
    removed_ids: list[str],
) -> None:
    """Apply a replace operation to group data."""
    path = (op.path or "").lower()

    if not path:
        if isinstance(op.value, dict):
            for key, val in op.value.items():
                if key.lower() == "members":
                    _replace_members(val, current_members, added_ids, removed_ids)
                else:
                    _set_group_field(key.lower(), val, data)
        else:
            raise ScimPatchError("Replace without path requires a dict value")
        return

    if path == "members":
        _replace_members(op.value, current_members, added_ids, removed_ids)
        return

    _set_group_field(path, op.value, data)


def _replace_members(
    value: str | list | dict | bool | None,
    current_members: list[dict],
    added_ids: list[str],
    removed_ids: list[str],
) -> None:
    """Replace the entire group member list."""
    if not isinstance(value, list):
        raise ScimPatchError("Replace members requires a list value")

    old_ids = {m["value"] for m in current_members}
    new_ids = {m.get("value", "") for m in value}

    removed_ids.extend(old_ids - new_ids)
    added_ids.extend(new_ids - old_ids)

    current_members[:] = value


def _set_group_field(
    path: str,
    value: str | bool | dict | list | None,
    data: dict,
) -> None:
    """Set a single field on group data by SCIM path."""
    if path == "displayname":
        data["displayName"] = value
    elif path == "externalid":
        data["externalId"] = value
    else:
        raise ScimPatchError(f"Unsupported path '{path}' for Group PATCH")


def _apply_group_add(
    op: ScimPatchOperation,
    members: list[dict],
    added_ids: list[str],
) -> None:
    """Add members to a group."""
    path = (op.path or "").lower()

    if path and path != "members":
        raise ScimPatchError(f"Unsupported add path '{op.path}' for Group")

    if not isinstance(op.value, list):
        raise ScimPatchError("Add members requires a list value")

    existing_ids = {m["value"] for m in members}
    for member_data in op.value:
        member_id = member_data.get("value", "")
        if member_id and member_id not in existing_ids:
            members.append(member_data)
            added_ids.append(member_id)
            existing_ids.add(member_id)


def _apply_group_remove(
    op: ScimPatchOperation,
    members: list[dict],
    removed_ids: list[str],
) -> None:
    """Remove members from a group."""
    if not op.path:
        raise ScimPatchError("Remove operation requires a path")

    match = _MEMBER_FILTER_RE.match(op.path)
    if not match:
        raise ScimPatchError(
            f"Unsupported remove path '{op.path}'. "
            'Expected: members[value eq "user-id"]'
        )

    target_id = match.group(1)
    original_len = len(members)
    members[:] = [m for m in members if m.get("value") != target_id]

    if len(members) < original_len:
        removed_ids.append(target_id)
