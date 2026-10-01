"""Header helpers for endpoints that serve stored files."""

import mimetypes
import re
from urllib.parse import quote

_UNSAFE_FILENAME_CHARS = re.compile(r'[\x00-\x1f\x7f"\\/]')
_NON_ASCII_CHARS = re.compile(r"[^\x20-\x7e]")
# Matches the frontend check, so "Sales v1.2 data" still counts as extensionless.
_FILENAME_EXTENSION = re.compile(r"\.[^./\\\s]+$")

UNKNOWN_MEDIA_TYPE: str = "application/octet-stream"


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
    if bare_media_type == UNKNOWN_MEDIA_TYPE:
        return filename
    extension = mimetypes.guess_extension(bare_media_type)
    return f"{filename}{extension}" if extension else filename
