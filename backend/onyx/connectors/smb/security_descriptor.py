"""Parses the access list of a Windows security descriptor, as the SMB server
returns it (self-relative form).

https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-dtyp/7d4dac05-9cef-4563-a058-f108abecce1d
"""

import struct
from enum import Enum

from pydantic import BaseModel

from onyx.connectors.smb.sid import MalformedSidError, sid_from_bytes

# SECURITY_DESCRIPTOR: revision, sbz1, control, then the offsets of the
# owner, the group, the SACL and the DACL.
_DESCRIPTOR_HEADER = struct.Struct("<BBHIIII")
# ACL: revision, sbz1, size, ACE count, sbz2.
_ACL_HEADER = struct.Struct("<BBHHH")
# ACE: type, flags, size.
_ACE_HEADER = struct.Struct("<BBH")
_MASK = struct.Struct("<I")
_SE_DACL_PRESENT = 0x0004
_INHERIT_ONLY_ACE = 0x08
_GUID_LENGTH = 16
_OBJECT_TYPE_PRESENT = 0x1
_INHERITED_OBJECT_TYPE_PRESENT = 0x2

_ALLOW_TYPES = frozenset({0x00, 0x05, 0x09, 0x0B})
_DENY_TYPES = frozenset({0x01, 0x06, 0x0A, 0x0C})
# Applies to one property or child type of a directory object.
_OBJECT_TYPES = frozenset({0x05, 0x06, 0x0B, 0x0C})
# Carries a condition that only the server can evaluate.
_CALLBACK_TYPES = frozenset({0x09, 0x0A, 0x0B, 0x0C})


class MalformedSecurityDescriptorError(ValueError):
    """The bytes are not a security descriptor."""


class AceKind(str, Enum):
    ALLOW = "allow"
    DENY = "deny"


class Ace(BaseModel):
    kind: AceKind
    sid: str
    # The raw access mask.
    mask: int
    # True for an entry that only children inherit: it does not apply to the
    # file or folder that holds it.
    inherit_only: bool = False
    # True for an entry with a condition or an object type. Onyx cannot tell
    # when such an entry applies.
    qualified: bool = False


class SecurityDescriptor(BaseModel):
    # False for a descriptor with no DACL, which Windows reads as full access
    # for everyone.
    dacl_present: bool
    # In stored order. Windows stops at the first entry that decides.
    aces: list[Ace]


def _parse_ace(data: bytes, offset: int, ace_type: int, flags: int) -> Ace | None:
    """The entry at ``offset``, which is past the ACE header. None for an
    entry that neither allows nor denies, e.g. an audit entry."""
    if ace_type not in _ALLOW_TYPES and ace_type not in _DENY_TYPES:
        return None
    (mask,) = _MASK.unpack_from(data, offset)
    sid_offset: int = offset + _MASK.size
    if ace_type in _OBJECT_TYPES:
        (object_flags,) = _MASK.unpack_from(data, sid_offset)
        sid_offset += _MASK.size
        if object_flags & _OBJECT_TYPE_PRESENT:
            sid_offset += _GUID_LENGTH
        if object_flags & _INHERITED_OBJECT_TYPE_PRESENT:
            sid_offset += _GUID_LENGTH
    return Ace(
        kind=AceKind.ALLOW if ace_type in _ALLOW_TYPES else AceKind.DENY,
        sid=sid_from_bytes(data, sid_offset),
        mask=mask,
        inherit_only=bool(flags & _INHERIT_ONLY_ACE),
        qualified=ace_type in _OBJECT_TYPES or ace_type in _CALLBACK_TYPES,
    )


def parse_security_descriptor(data: bytes) -> SecurityDescriptor:
    try:
        _, _, control, _, _, _, dacl_offset = _DESCRIPTOR_HEADER.unpack_from(data, 0)
        if not control & _SE_DACL_PRESENT or dacl_offset == 0:
            return SecurityDescriptor(dacl_present=False, aces=[])
        _, _, acl_size, ace_count, _ = _ACL_HEADER.unpack_from(data, dacl_offset)
        acl_end: int = dacl_offset + acl_size
        if acl_end > len(data):
            raise MalformedSecurityDescriptorError("The access list is cut off.")
        aces: list[Ace] = []
        offset: int = dacl_offset + _ACL_HEADER.size
        for _ in range(ace_count):
            ace_type, flags, ace_size = _ACE_HEADER.unpack_from(data, offset)
            if ace_size < _ACE_HEADER.size or offset + ace_size > acl_end:
                raise MalformedSecurityDescriptorError("An access entry is cut off.")
            ace: Ace | None = _parse_ace(
                data[: offset + ace_size], offset + _ACE_HEADER.size, ace_type, flags
            )
            if ace is not None:
                aces.append(ace)
            offset += ace_size
        return SecurityDescriptor(dacl_present=True, aces=aces)
    except (struct.error, MalformedSidError) as e:
        raise MalformedSecurityDescriptorError(
            f"The security descriptor is malformed: {e}"
        ) from e
