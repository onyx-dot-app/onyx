"""Response policy for stored file bytes served from the app origin.

Uploads keep the MIME type the client declared, so serving one inline is a
stored-XSS primitive unless the type is inert: a text/html or image/svg+xml body
rendered inline runs script on the app origin with the viewer's session.
"""

import mimetypes
import re
from urllib.parse import quote

from onyx.file_processing.file_types import (
    PRESENTATION_MIME_TYPE,
    SPREADSHEET_MIME_TYPE,
    WORD_PROCESSING_MIME_TYPE,
)

INLINE_SAFE_IMAGE_MIME_TYPES: frozenset[str] = frozenset(
    {
        "image/png",
        "image/jpg",
        "image/jpeg",
        "image/gif",
        "image/webp",
    }
)

INLINE_SAFE_MIME_TYPES: frozenset[str] = INLINE_SAFE_IMAGE_MIME_TYPES | frozenset(
    {
        "application/pdf",
        "text/plain",
    }
)

# Browsers never render these, so they keep their stored type as an attachment.
ATTACHMENT_SAFE_MIME_TYPES: frozenset[str] = frozenset(
    {
        WORD_PROCESSING_MIME_TYPE,
        SPREADSHEET_MIME_TYPE,
        PRESENTATION_MIME_TYPE,
        "application/msword",
        "application/vnd.ms-excel",
        "application/vnd.ms-powerpoint",
    }
)

ATTACHMENT_MEDIA_TYPE: str = "application/octet-stream"

_UNSAFE_FILENAME_CHARS = re.compile(r'[\x00-\x1f\x7f"\\/]')
_NON_ASCII_CHARS = re.compile(r"[^\x20-\x7e]")
# Matches the frontend check, so "Sales v1.2 data" still counts as extensionless.
_FILENAME_EXTENSION = re.compile(r"\.[^./\\\s]+$")

# Version of the policy `resolve_inline_disposition` applies. Endpoints that
# cache their responses mix this into the ETag, so bump it whenever the headers
# or the allowlist change: that is the only way to make clients drop entries
# cached under the old policy.
RESPONSE_POLICY_VERSION: str = "v3"


def resolve_inline_disposition(
    media_type: str,
    *,
    filename: str | None = None,
    inline_types: frozenset[str] = INLINE_SAFE_MIME_TYPES,
    attachment_types: frozenset[str] = frozenset(),
    fallback_media_type: str = ATTACHMENT_MEDIA_TYPE,
    fallback_disposition: str | None = "attachment",
    sandbox: bool = True,
) -> tuple[str, dict[str, str]]:
    """Decide how a stored media type may be served.

    Returns the media type to put on the wire and the security headers to merge
    into the response. A type inside `inline_types` is served as stored; anything
    else carries `fallback_disposition` (pass `None` to omit the header) and is
    downgraded to `fallback_media_type` unless it is inside `attachment_types`.
    A `filename` is added to whichever disposition is sent.
    """
    headers: dict[str, str] = {"X-Content-Type-Options": "nosniff"}
    if sandbox:
        headers["Content-Security-Policy"] = "sandbox"

    # Match on the bare type: stored types carry parameters ("image/png;base64").
    bare_media_type = media_type.split(";")[0].strip().lower()
    if bare_media_type in inline_types:
        if filename is not None:
            headers["Content-Disposition"] = build_content_disposition(
                "inline", filename
            )
        return media_type, headers

    if fallback_disposition is not None:
        headers["Content-Disposition"] = (
            fallback_disposition
            if filename is None
            else build_content_disposition(fallback_disposition, filename)
        )
    if bare_media_type in attachment_types:
        return media_type, headers
    return fallback_media_type, headers


def build_content_disposition(disposition_type: str, filename: str) -> str:
    """Build a header value that names the file safely.

    `filename` is an ASCII fallback for old clients; `filename*` (RFC 5987)
    carries the full UTF-8 name, which current browsers prefer.
    """
    cleaned_filename = _UNSAFE_FILENAME_CHARS.sub("_", filename).strip() or "download"
    ascii_filename = _NON_ASCII_CHARS.sub("_", cleaned_filename)
    encoded_filename = quote(cleaned_filename, safe="")
    return (
        f'{disposition_type}; filename="{ascii_filename}"; '
        f"filename*=UTF-8''{encoded_filename}"
    )


def ensure_filename_extension(filename: str, media_type: str) -> str:
    """Append the extension of `media_type` when `filename` has none."""
    if _FILENAME_EXTENSION.search(filename):
        return filename
    bare_media_type = media_type.split(";")[0].strip().lower()
    if bare_media_type == ATTACHMENT_MEDIA_TYPE:
        return filename
    extension = mimetypes.guess_extension(bare_media_type)
    return f"{filename}{extension}" if extension else filename
