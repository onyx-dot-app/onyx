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
