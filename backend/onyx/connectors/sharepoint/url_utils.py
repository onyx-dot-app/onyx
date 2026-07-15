"""URL helpers for SharePoint that must stay import-light.

This module must not pull in the heavy connector dependencies (office365,
msal, etc.), so it can be imported wherever URL parsing is needed.
"""

import base64
import binascii
import re
from urllib.parse import parse_qs
from urllib.parse import urlsplit
from urllib.parse import urlunsplit
from uuid import UUID

_SOURCEDOC_PARAM = "sourcedoc"

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


def _guid_from_sourcedoc_query(query: str) -> str | None:
    if not query or _SOURCEDOC_PARAM not in query.lower():
        return None

    for key, values in parse_qs(query).items():
        if key.lower() != _SOURCEDOC_PARAM:
            continue
        for value in values:
            guid = _parse_guid(value)
            if guid:
                return guid
    return None


def _guid_from_sharing_token(path: str) -> str | None:
    match = _SHARING_LINK_PATH_PATTERN.match(path)
    if not match:
        return None

    token = match.group(1)
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


def sharepoint_page_url_variants(url: str) -> list[str]:
    """Candidate stored-link forms for a GUID-less SharePoint URL.

    Site pages (and other non-file content) are stored with the plain page URL
    as Document.link, so exact-link matching works once volatile parts (query
    like `?web=1`, fragment, trailing slash) are stripped. Returns the pasted
    URL plus its stripped form.
    """
    split = urlsplit(url)
    if not split.netloc:
        return []
    stripped = urlunsplit(
        (split.scheme or "https", split.netloc.lower(), split.path.rstrip("/"), "", "")
    )
    return list(dict.fromkeys([url, stripped]))


def extract_sharepoint_document_guid(query: str, path: str) -> str | None:
    """Extract a SharePoint file's unique-ID GUID from a pasted URL's parts.

    Handles Doc.aspx-style URLs (`sourcedoc=%7B<GUID>%7D`, raw-brace, or
    brace-less) and `/:w:/s/<site>/<token>` sharing links whose token embeds the
    same GUID. Returns the uppercase, brace-less GUID, or None when the URL
    doesn't carry one (e.g. SitePages URLs).
    """
    return _guid_from_sourcedoc_query(query) or _guid_from_sharing_token(path)
