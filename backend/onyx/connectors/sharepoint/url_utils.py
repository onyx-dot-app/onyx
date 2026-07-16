"""URL helpers for SharePoint that must stay import-light.

This module must not pull in the heavy connector dependencies (office365,
msal, etc.), so it can be imported wherever URL parsing is needed.
"""

import base64
import binascii
import re
from collections.abc import Callable
from urllib.parse import parse_qs
from urllib.parse import quote
from urllib.parse import unquote
from urllib.parse import urlsplit
from urllib.parse import urlunsplit
from uuid import UUID

_SOURCEDOC_PARAM = "sourcedoc"
_SHARE_PARAM = "share"

_BASE32_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"

# Graph drive-item ids are "01" + base32(4-byte drive hash + item unique-ID GUID
# little-endian). Undocumented but stable; verified against live Graph data.
# An id prefix of this length pins 30 of the 32 drive-hash bits (the remaining
# 2 bits straddle the next base32 char and are enumerated at lookup time).
DRIVE_ITEM_ID_PREFIX = "01"
DRIVE_ITEM_ID_PREFIX_LENGTH = 8
# 20 payload bytes (4 drive hash + 16 GUID) encode to exactly 32 unpadded
# base32 chars, so every drive-item id is 34 chars long.
DRIVE_ITEM_ID_LENGTH = 34
_DRIVE_HASH_BYTES = 4

# Sharing links look like /:w:/s/<site-name>/<base64url-token>. The token decodes
# to a "!\x00" header followed by the item's unique-ID GUID in little-endian
# (the same GUID Doc.aspx URLs carry in `sourcedoc=`), then opaque trailing bytes.
_SHARING_LINK_PATH_PATTERN = re.compile(
    r"^/:[a-z]:/s/[^/]+/([A-Za-z0-9_-]{20,})/?$", re.IGNORECASE
)
_SHARING_TOKEN_HEADER = b"!\x00"
_SHARING_TOKEN_MIN_BYTES = len(_SHARING_TOKEN_HEADER) + 16


def _parse_guid(value: str) -> str | None:
    """Canonicalize a GUID in any common form (braced, dashed, bare hex) to
    uppercase dashed, or None if invalid."""
    try:
        return str(UUID(value.strip())).upper()
    except ValueError:
        return None


def _guid_from_query_param(
    query: str, param: str, extract: Callable[[str], str | None]
) -> str | None:
    if not query or param not in query.lower():
        return None

    for key, values in parse_qs(query).items():
        if key.lower() != param:
            continue
        for value in values:
            guid = extract(value)
            if guid:
                return guid
    return None


def _guid_from_token(token: str) -> str | None:
    try:
        raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
    except (binascii.Error, ValueError):
        return None

    if len(raw) < _SHARING_TOKEN_MIN_BYTES or not raw.startswith(_SHARING_TOKEN_HEADER):
        # Other token families (e.g. E...-prefixed) have an unverified layout; punt
        # so resolution falls back to the crawl path rather than joining on a
        # misparsed GUID.
        return None

    guid_bytes = raw[len(_SHARING_TOKEN_HEADER) : len(_SHARING_TOKEN_HEADER) + 16]
    return str(UUID(bytes_le=guid_bytes)).upper()


def _guid_from_sharing_token(path: str) -> str | None:
    match = _SHARING_LINK_PATH_PATTERN.match(path)
    if not match:
        return None
    return _guid_from_token(match.group(1))


def sharepoint_guid_from_drive_item_id(drive_item_id: str) -> str | None:
    """Decode the unique-ID GUID embedded in a Graph drive-item id.

    Inverse of sharepoint_drive_item_id_candidates: the GUID occupies bytes
    4-19 of the base32 payload, little-endian. Returns the lowercase dashed
    GUID (the Document.id format for SharePoint files), or None when the input
    isn't a well-formed drive-item id.
    """
    if (
        len(drive_item_id) != DRIVE_ITEM_ID_LENGTH
        or not drive_item_id.startswith(DRIVE_ITEM_ID_PREFIX)
        or any(
            char not in _BASE32_ALPHABET
            for char in drive_item_id[len(DRIVE_ITEM_ID_PREFIX) :]
        )
    ):
        return None
    raw = base64.b32decode(drive_item_id[len(DRIVE_ITEM_ID_PREFIX) :])
    return str(UUID(bytes_le=raw[_DRIVE_HASH_BYTES:]))


def sharepoint_drive_hash_from_drive_item_id(drive_item_id: str) -> bytes | None:
    """Extract the 4-byte drive hash from a Graph drive-item id (e.g. a drive's
    root-folder id). Every item in a drive shares this hash, so it lets a full
    drive-item id be reconstructed exactly from an item's unique-ID GUID."""
    if (
        len(drive_item_id) != DRIVE_ITEM_ID_LENGTH
        or not drive_item_id.startswith(DRIVE_ITEM_ID_PREFIX)
        or any(
            char not in _BASE32_ALPHABET
            for char in drive_item_id[len(DRIVE_ITEM_ID_PREFIX) :]
        )
    ):
        return None
    return base64.b32decode(drive_item_id[len(DRIVE_ITEM_ID_PREFIX) :])[
        :_DRIVE_HASH_BYTES
    ]


def sharepoint_drive_item_id_from_guid(drive_hash: bytes, guid: str) -> str | None:
    """Reconstruct the exact Graph drive-item id for an item's unique-ID GUID,
    given the containing drive's 4-byte hash."""
    if len(drive_hash) != _DRIVE_HASH_BYTES:
        return None
    try:
        guid_bytes = UUID(guid).bytes_le
    except ValueError:
        return None
    return DRIVE_ITEM_ID_PREFIX + base64.b32encode(drive_hash + guid_bytes).decode()


def sharepoint_drive_item_id_candidates(
    guid: str, drive_id_prefixes: list[str]
) -> list[str]:
    """Construct the candidate drive-item Document.ids for a file's unique-ID GUID.

    Each 8-char prefix ("01" + 6 base32 chars) fixes 30 drive-hash bits; the 2
    unresolved bits give 4 candidate ids per prefix. Prefixes that aren't valid
    drive-item id prefixes (other connectors' ids can also start with "01") are
    skipped.
    """
    try:
        guid_bytes = UUID(guid).bytes_le
    except ValueError:
        return []

    candidates: list[str] = []
    for prefix in drive_id_prefixes:
        if len(prefix) != DRIVE_ITEM_ID_PREFIX_LENGTH or not prefix.startswith(
            DRIVE_ITEM_ID_PREFIX
        ):
            continue
        hash_bits = 0
        try:
            for char in prefix[len(DRIVE_ITEM_ID_PREFIX) :]:
                hash_bits = (hash_bits << 5) | _BASE32_ALPHABET.index(char)
        except ValueError:
            continue
        for low_bits in range(4):
            drive_hash = ((hash_bits << 2) | low_bits).to_bytes(4, "big")
            candidates.append(
                DRIVE_ITEM_ID_PREFIX
                + base64.b32encode(drive_hash + guid_bytes).decode()
            )
    return candidates


def sharepoint_page_url_variants(url: str) -> list[str]:
    """Candidate stored-link forms for a GUID-less SharePoint URL.

    Site pages (and other non-file content) are stored with the plain page URL
    as Document.link, so exact-link matching works once volatile parts (query
    like `?web=1`, fragment, trailing slash) are stripped. Stored links come
    from Graph webUrl, whose percent-encoding can differ from a browser's
    clipboard form (Graph encodes spaces as %20 but keeps sub-delims like
    `!'()` raw), so encoding-normalized forms of the path are included too.
    """
    split = urlsplit(url)
    if not split.netloc:
        return []

    def _with_path(path: str) -> str:
        return urlunsplit((split.scheme or "https", split.netloc.lower(), path, "", ""))

    path = split.path.rstrip("/")
    decoded_path = unquote(path)
    variants = [
        url,
        _with_path(path),
        _with_path(decoded_path),
        _with_path(quote(decoded_path, safe="/!$&'()*+,;=:@")),
    ]
    return list(dict.fromkeys(variants))


def extract_sharepoint_document_guid(query: str, path: str) -> str | None:
    """Extract a SharePoint file's unique-ID GUID from a pasted URL's parts.

    Handles Doc.aspx-style URLs (`sourcedoc=%7B<GUID>%7D`, raw-brace, or
    brace-less), `/:w:/s/<site>/<token>` sharing links whose token embeds the
    same GUID, and share-redirect URLs carrying that token in a `share=` query
    param. Returns the uppercase, brace-less GUID, or None when the URL
    doesn't carry one (e.g. plain SitePages URLs).
    """
    return (
        _guid_from_query_param(query, _SOURCEDOC_PARAM, _parse_guid)
        or _guid_from_sharing_token(path)
        # share-redirect URLs carry the same token a /:x:/s/ link embeds in its path
        or _guid_from_query_param(query, _SHARE_PARAM, _guid_from_token)
    )
