"""Who a POSIX ACL of Azure Data Lake Storage grants one permission bit.

Azure picks the first class that matches the caller: the owning user, then a
named user entry, then the owning group and named groups (the union of every
matching group entry), then ``other``. A caller matched by an earlier class
never falls through to a later one. The ``mask`` limits named users and every
group entry. ``default:`` entries only seed new children and grant nothing.
"""

from enum import Enum

from pydantic import BaseModel

from ee.onyx.external_permissions.azure_datalake.principals import (
    PrincipalSet,
    PrincipalTerm,
    everyone_term,
    group_term,
    simplify,
    user_term,
)
from onyx.connectors.azure_datalake.models import AzureDataLakeAccessControl

# Not a principal: the owner or owning group of a path nobody owns.
SUPERUSER = "$superuser"
_DEFAULT_SCOPE = "default"


class AclBit(str, Enum):
    READ = "r"
    WRITE = "w"
    EXECUTE = "x"


class AclEntryType(str, Enum):
    USER = "user"
    GROUP = "group"
    MASK = "mask"
    OTHER = "other"


class AclEntry(BaseModel):
    entry_type: AclEntryType
    # The Entra object id. Empty for the owner, owning group, mask and other.
    qualifier: str
    permissions: str


def parse_acl(acl: str) -> list[AclEntry]:
    """The access entries of an ACL string, without ``default:`` entries."""
    entries: list[AclEntry] = []
    for raw in acl.split(","):
        parts: list[str] = raw.strip().split(":")
        if parts and parts[0] == _DEFAULT_SCOPE:
            continue
        if len(parts) != 3:
            continue
        type_name, qualifier, permissions = parts
        try:
            entry_type = AclEntryType(type_name)
        except ValueError:
            continue
        entries.append(
            AclEntry(
                entry_type=entry_type, qualifier=qualifier, permissions=permissions
            )
        )
    return entries


def _short_form_entries(permissions: str) -> list[AclEntry]:
    """The three base entries of a permission string such as ``rwxr-x---``,
    for a path that returns no ACL."""
    # A sticky bit shows in other's execute slot: "t" with execute, "T"
    # without.
    bits: str = permissions[:9].ljust(9, "-")[:8] + {"t": "x", "T": "-"}.get(
        permissions[8:9], permissions[8:9] or "-"
    )
    return [
        AclEntry(entry_type=AclEntryType.USER, qualifier="", permissions=bits[0:3]),
        AclEntry(entry_type=AclEntryType.GROUP, qualifier="", permissions=bits[3:6]),
        AclEntry(entry_type=AclEntryType.OTHER, qualifier="", permissions=bits[6:9]),
    ]


def _is_principal(object_id: str) -> bool:
    return bool(object_id) and object_id != SUPERUSER


def granted_principals(access: AzureDataLakeAccessControl, bit: AclBit) -> PrincipalSet:
    """Everyone the path's ACL gives ``bit``, exactly."""
    entries: list[AclEntry] = parse_acl(access.acl) if access.acl else []
    if not entries:
        entries = _short_form_entries(access.permissions)

    mask: str | None = None
    owner_permissions: str = ""
    other_permissions: str = ""
    named_users: dict[str, str] = {}
    # A group can match both as the owning group and as a named group; its
    # members then hold the union of both entries.
    group_permissions: dict[str, str] = {}
    for entry in entries:
        if entry.entry_type is AclEntryType.MASK:
            mask = entry.permissions
        elif entry.entry_type is AclEntryType.OTHER:
            other_permissions = entry.permissions
        elif entry.entry_type is AclEntryType.USER:
            if entry.qualifier:
                named_users[entry.qualifier] = entry.permissions
            else:
                owner_permissions = entry.permissions
        else:
            group_id: str = entry.qualifier or access.group
            if _is_principal(group_id):
                group_permissions[group_id] = (
                    group_permissions.get(group_id, "") + entry.permissions
                )

    def masked(permissions: str) -> bool:
        return bit.value in permissions and (mask is None or bit.value in mask)

    terms: list[PrincipalTerm] = []
    # Matched by an earlier class without the bit: no later class can give it.
    denied_users: set[str] = set()
    owner: str = access.owner
    if _is_principal(owner):
        if bit.value in owner_permissions:
            terms.append(user_term(owner))
        else:
            denied_users.add(owner)
    for user_id, permissions in named_users.items():
        if user_id == owner:
            continue
        if masked(permissions):
            terms.append(user_term(user_id))
        else:
            denied_users.add(user_id)
    granting_groups: set[str] = {
        group_id
        for group_id, permissions in group_permissions.items()
        if masked(permissions)
    }
    terms.extend(
        group_term(group_id, excluded_users=denied_users)
        for group_id in granting_groups
    )
    if bit.value in other_permissions:
        # Members of a group entry without the bit match that entry, not
        # ``other``. Members of a granting group are in through its term.
        terms.append(
            everyone_term(
                excluded_users=denied_users,
                excluded_groups=set(group_permissions) - granting_groups,
            )
        )
    return simplify(terms)
