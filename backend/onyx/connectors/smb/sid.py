"""Windows security identifiers (SIDs), as Active Directory and NTFS access
lists store them.

https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-dtyp/f992ad60-0fe4-4b87-9fed-beb478836861
"""

import struct

_HEADER_LENGTH = 8
_SUB_AUTHORITY_LENGTH = 4
_REVISION = 1
# A domain's SID is S-1-5-21 and three numbers. An account adds its RID.
_DOMAIN_SID_PARTS = 7
_DOMAIN_PREFIX = "S-1-5-21-"


class MalformedSidError(ValueError):
    """The bytes are not a SID."""


def sid_length(data: bytes, offset: int = 0) -> int:
    """The length in bytes of the SID that starts at ``offset``."""
    if len(data) < offset + _HEADER_LENGTH:
        raise MalformedSidError("The SID is cut off.")
    return _HEADER_LENGTH + data[offset + 1] * _SUB_AUTHORITY_LENGTH


def sid_from_bytes(data: bytes, offset: int = 0) -> str:
    """The string form, e.g. ``S-1-5-21-1-2-3-513``."""
    length: int = sid_length(data, offset)
    if len(data) < offset + length:
        raise MalformedSidError("The SID is cut off.")
    revision: int = data[offset]
    if revision != _REVISION:
        raise MalformedSidError(f"Unknown SID revision {revision}.")
    count: int = data[offset + 1]
    authority: int = int.from_bytes(data[offset + 2 : offset + 8], "big")
    sub_authorities: tuple[int, ...] = struct.unpack_from(
        f"<{count}I", data, offset + _HEADER_LENGTH
    )
    return "-".join(["S", str(revision), str(authority), *map(str, sub_authorities)])


def normalize_sid(sid: str) -> str:
    """One spelling per SID: stored group ids are in lower case."""
    return sid.strip().upper()


def domain_sid_of(sid: str) -> str | None:
    """The SID of the domain that issued an account SID. None for a
    well-known or built-in SID."""
    parts: list[str] = sid.split("-")
    if not sid.startswith(_DOMAIN_PREFIX) or len(parts) <= _DOMAIN_SID_PARTS:
        return None
    return "-".join(parts[:_DOMAIN_SID_PARTS])


def rid_of(sid: str) -> int:
    """The last number of a SID: the account's id inside its domain."""
    return int(sid.rsplit("-", 1)[-1])
