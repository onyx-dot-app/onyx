from typing import cast

import puremagic
from fastapi import UploadFile
from pydantic import BaseModel

from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.utils.logger import setup_logger

logger = setup_logger()


# Caps an uploaded image's raster at about 67 MB RGBA. A small, highly
# compressed file can declare a much larger raster than its byte size suggests,
# so uploads check the header size against this before they decode.
MAX_UPLOAD_IMAGE_PIXELS = 4096 * 4096


def read_upload_within_limit(upload: UploadFile, max_bytes: int, label: str) -> bytes:
    """Read the upload, or raise PAYLOAD_TOO_LARGE when it is over `max_bytes`.
    It reads one byte over the cap, not the rest of an oversized body."""
    content = upload.file.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise OnyxError(
            OnyxErrorCode.PAYLOAD_TOO_LARGE,
            f"{label} must be {max_bytes // (1024 * 1024)} MB or smaller",
        )
    return content


def sniff_mime_type(header: bytes, allowed_mime_types: frozenset[str]) -> str | None:
    """The MIME type that the leading bytes of a file identify, or None when it
    is not in `allowed_mime_types`. Uploads use it instead of the type the
    client declares."""
    try:
        matches = puremagic.magic_string(header)
    except (puremagic.PureError, ValueError):
        # PureError: nothing matched. ValueError: the body is empty.
        return None
    mime_type: str | None = matches[0].mime_type if matches else None
    if mime_type not in allowed_mime_types:
        return None
    return mime_type


class FileWithMimeType(BaseModel):
    data: bytes
    mime_type: str


class OnyxStaticFileManager:
    """Retrieve static resources with this class. Currently, these should all be located
    in the static directory ... e.g. static/images/logo.png"""

    @staticmethod
    def get_static(filename: str) -> FileWithMimeType | None:
        try:
            mime_type: str = "application/octet-stream"
            with open(filename, "rb") as f:
                file_content = f.read()
                matches = puremagic.magic_string(file_content)
                if matches:
                    mime_type = cast(str, matches[0].mime_type)
        except (OSError, FileNotFoundError, PermissionError) as e:
            logger.error("Failed to read file %s: %s", filename, e)
            return None
        except Exception as e:
            logger.error("Unexpected exception reading file %s: %s", filename, e)
            return None

        return FileWithMimeType(data=file_content, mime_type=mime_type)
