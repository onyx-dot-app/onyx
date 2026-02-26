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

import logging
import re
from dataclasses import dataclass
from dataclasses import field
from typing import Any

from ee.onyx.server.scim.models import SCIM_ENTERPRISE_USER_SCHEMA
from ee.onyx.server.scim.models import ScimGroupMember
from ee.onyx.server.scim.models import ScimGroupResource
from ee.onyx.server.scim.models import ScimPatchOperation
from ee.onyx.server.scim.models import ScimPatchOperationType
from ee.onyx.server.scim.models import ScimPatchResourceValue
from ee.onyx.server.scim.models import ScimPatchValue
from ee.onyx.server.scim.models import ScimUserResource

logger = logging.getLogger(__name__)

# Lowercased enterprise extension URN for case-insensitive matching
_ENTERPRISE_URN_LOWER = SCIM_ENTERPRISE_USER_SCHEMA.lower()

# Pattern for email filter paths, e.g.:
#   emails[primary eq true].value  (Okta)
#   emails[type eq "work"].value   (Azure AD / Entra ID)
_EMAIL_FILTER_RE = re.compile(
    r"^emails\[.+\]\.value$",
    re.IGNORECASE,
)

# Pattern for member removal path: members[value eq "user-id"]
_MEMBER_FILTER_RE = re.compile(
    r'^members\[value\s+eq\s+"([^"]+)"\]$',
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Dispatch tables for user PATCH paths
#
# Maps lowercased SCIM path → (camelCase key, target dict name).
# "data" writes to the top-level resource dict, "name" writes to the
# name sub-object dict. This replaces the elif chains for simple fields.
# ---------------------------------------------------------------------------

_USER_REPLACE_PATHS: dict[str, tuple[str, str]] = {
    "active": ("active", "data"),
    "username": ("userName", "data"),
    "externalid": ("externalId", "data"),
    "name.givenname": ("givenName", "name"),
    "name.familyname": ("familyName", "name"),
    "name.formatted": ("formatted", "name"),
}

_USER_REMOVE_PATHS: dict[str, tuple[str, str]] = {
    "externalid": ("externalId", "data"),
    "name.givenname": ("givenName", "name"),
    "name.familyname": ("familyName", "name"),
    "name.formatted": ("formatted", "name"),
    "displayname": ("displayName", "data"),
}

_GROUP_REPLACE_PATHS: dict[str, tuple[str, str]] = {
    "displayname": ("displayName", "data"),
    "externalid": ("externalId", "data"),
}


class ScimPatchError(Exception):
    """Raised when a PATCH operation cannot be applied."""

    def __init__(self, detail: str, status: int = 400) -> None:
        self.detail = detail
        self.status = status
        super().__init__(detail)


@dataclass
class _UserPatchCtx:
    """Bundles the mutable state for user PATCH operations."""

    data: dict[str, Any]
    name_data: dict[str, Any]
    ent_data: dict[str, str | None] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# User PATCH
# ---------------------------------------------------------------------------


def apply_user_patch(
    operations: list[ScimPatchOperation],
    current: ScimUserResource,
    ignored_paths: frozenset[str] = frozenset(),
) -> tuple[ScimUserResource, dict[str, str | None]]:
    """Apply SCIM PATCH operations to a user resource.

    Args:
        operations: The PATCH operations to apply.
        current: The current user resource state.
        ignored_paths: SCIM attribute paths to silently skip (from provider).

    Returns:
        A tuple of (modified user resource, enterprise extension data dict).
        The enterprise dict has keys ``"department"`` and ``"manager"``
        with values set only when a PATCH operation touched them.

    Raises:
        ScimPatchError: If an operation targets an unsupported path.
    """
    data = current.model_dump()
    ctx = _UserPatchCtx(data=data, name_data=data.get("name") or {})

    for op in operations:
        if op.op in (ScimPatchOperationType.REPLACE, ScimPatchOperationType.ADD):
            _apply_user_replace(op, ctx, ignored_paths)
        elif op.op == ScimPatchOperationType.REMOVE:
            _apply_user_remove(op, ctx, ignored_paths)
        else:
            raise ScimPatchError(
                f"Unsupported operation '{op.op.value}' on User resource"
            )

    ctx.data["name"] = ctx.name_data
    return ScimUserResource.model_validate(ctx.data), ctx.ent_data


def _apply_user_replace(
    op: ScimPatchOperation,
    ctx: _UserPatchCtx,
    ignored_paths: frozenset[str],
) -> None:
    """Apply a replace/add operation to user data."""
    path = (op.path or "").lower()

    if not path:
        # No path — value is a resource dict of top-level attributes to set.
        if isinstance(op.value, ScimPatchResourceValue):
            for key, val in op.value.model_dump(exclude_unset=True).items():
                _set_user_field(key.lower(), val, ctx, ignored_paths, strict=False)
        else:
            raise ScimPatchError("Replace without path requires a dict value")
        return

    _set_user_field(path, op.value, ctx, ignored_paths)


def _apply_user_remove(
    op: ScimPatchOperation,
    ctx: _UserPatchCtx,
    ignored_paths: frozenset[str],
) -> None:
    """Apply a remove operation to user data — clears the target field."""
    path = (op.path or "").lower()
    if not path:
        raise ScimPatchError("Remove operation requires a path")

    if path in ignored_paths:
        return

    entry = _USER_REMOVE_PATHS.get(path)
    if entry:
        key, target = entry
        target_dict = ctx.data if target == "data" else ctx.name_data
        target_dict[key] = None
        return

    raise ScimPatchError(f"Unsupported remove path '{path}' for User PATCH")


def _set_user_field(
    path: str,
    value: ScimPatchValue,
    ctx: _UserPatchCtx,
    ignored_paths: frozenset[str],
    *,
    strict: bool = True,
) -> None:
    """Set a single field on user data by SCIM path.

    Args:
        strict: When ``False`` (path-less replace), unknown attributes are
            silently skipped.  When ``True`` (explicit path), they raise.
    """
    if path in ignored_paths:
        return

    # Simple field writes handled by the dispatch table
    entry = _USER_REPLACE_PATHS.get(path)
    if entry:
        key, target = entry
        target_dict = ctx.data if target == "data" else ctx.name_data
        target_dict[key] = value
        return

    # displayName sets both the top-level field and the name.formatted sub-field
    if path == "displayname":
        ctx.data["displayName"] = value
        ctx.name_data["formatted"] = value
    elif path == "name":
        if isinstance(value, dict):
            for k, v in value.items():
                ctx.name_data[k] = v
    elif path == "emails":
        if isinstance(value, list):
            ctx.data["emails"] = value
    elif _EMAIL_FILTER_RE.match(path):
        _update_primary_email(ctx.data, value)
    elif path.startswith(_ENTERPRISE_URN_LOWER):
        _set_enterprise_field(path, value, ctx.ent_data)
    elif not strict:
        return
    else:
        raise ScimPatchError(f"Unsupported path '{path}' for User PATCH")


def _update_primary_email(data: dict[str, Any], value: ScimPatchValue) -> None:
    """Update the primary email entry via an email filter path."""
    emails: list[dict] = data.get("emails") or []
    for email_entry in emails:
        if email_entry.get("primary"):
            email_entry["value"] = value
            break
    else:
        emails.append({"value": value, "type": "work", "primary": True})
    data["emails"] = emails


def _to_dict(value: ScimPatchValue) -> dict | None:
    """Coerce a SCIM patch value to a plain dict if possible.

    Pydantic may parse raw dicts as ``ScimPatchResourceValue`` (which uses
    ``extra="allow"``), so we also dump those back to a dict.
    """
    if isinstance(value, dict):
        return value
    if isinstance(value, ScimPatchResourceValue):
        return value.model_dump(exclude_unset=True)
    return None


def _set_enterprise_field(
    path: str,
    value: ScimPatchValue,
    ent_data: dict[str, str | None],
) -> None:
    """Handle enterprise extension URN paths or value dicts."""
    # Full URN as key with dict value (path-less PATCH)
    # e.g. key="urn:...:user", value={"department": "Eng", "manager": {...}}
    if path == _ENTERPRISE_URN_LOWER:
        d = _to_dict(value)
        if d is not None:
            if "department" in d:
                ent_data["department"] = d["department"]
            if "manager" in d:
                mgr = d["manager"]
                if isinstance(mgr, dict):
                    ent_data["manager"] = mgr.get("value")
        return

    # Dotted URN path, e.g. "urn:...:user:department"
    suffix = path[len(_ENTERPRISE_URN_LOWER) :].lstrip(":").lower()
    if suffix == "department":
        ent_data["department"] = str(value) if value is not None else None
    elif suffix == "manager":
        d = _to_dict(value)
        if d is not None:
            ent_data["manager"] = d.get("value")
        elif isinstance(value, str):
            ent_data["manager"] = value
    else:
        # Unknown enterprise attributes are silently ignored rather than
        # rejected — IdPs may send attributes we don't model yet.
        logger.warning("Ignoring unknown enterprise extension attribute '%s'", suffix)


# ---------------------------------------------------------------------------
# Group PATCH
# ---------------------------------------------------------------------------


def apply_group_patch(
    operations: list[ScimPatchOperation],
    current: ScimGroupResource,
    ignored_paths: frozenset[str] = frozenset(),
) -> tuple[ScimGroupResource, list[str], list[str]]:
    """Apply SCIM PATCH operations to a group resource.

    Args:
        operations: The PATCH operations to apply.
        current: The current group resource state.
        ignored_paths: SCIM attribute paths to silently skip (from provider).

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
            _apply_group_replace(
                op, data, current_members, added_ids, removed_ids, ignored_paths
            )
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
    ignored_paths: frozenset[str],
) -> None:
    """Apply a replace operation to group data."""
    path = (op.path or "").lower()

    if not path:
        if isinstance(op.value, ScimPatchResourceValue):
            dumped = op.value.model_dump(exclude_unset=True)
            for key, val in dumped.items():
                if key.lower() == "members":
                    _replace_members(val, current_members, added_ids, removed_ids)
                else:
                    _set_group_field(key.lower(), val, data, ignored_paths)
        else:
            raise ScimPatchError("Replace without path requires a dict value")
        return

    if path == "members":
        _replace_members(
            _members_to_dicts(op.value), current_members, added_ids, removed_ids
        )
        return

    _set_group_field(path, op.value, data, ignored_paths)


def _members_to_dicts(
    value: str | bool | list[ScimGroupMember] | ScimPatchResourceValue | None,
) -> list[dict]:
    """Convert a member list value to a list of dicts for internal processing."""
    if not isinstance(value, list):
        raise ScimPatchError("Replace members requires a list value")
    return [m.model_dump(exclude_none=True) for m in value]


def _replace_members(
    value: list[dict],
    current_members: list[dict],
    added_ids: list[str],
    removed_ids: list[str],
) -> None:
    """Replace the entire group member list."""
    old_ids = {m["value"] for m in current_members}
    new_ids = {m.get("value", "") for m in value}

    removed_ids.extend(old_ids - new_ids)
    added_ids.extend(new_ids - old_ids)

    current_members[:] = value


def _set_group_field(
    path: str,
    value: ScimPatchValue,
    data: dict,
    ignored_paths: frozenset[str],
) -> None:
    """Set a single field on group data by SCIM path."""
    if path in ignored_paths:
        return

    entry = _GROUP_REPLACE_PATHS.get(path)
    if entry:
        key, _ = entry
        data[key] = value
        return

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

    member_dicts = [m.model_dump(exclude_none=True) for m in op.value]

    existing_ids = {m["value"] for m in members}
    for member_data in member_dicts:
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
