"""Validation of uploaded profile photos.

Every user in the workspace can load a profile photo from the app origin, so
only inert raster types are accepted. Each upload is decoded and encoded again
as a small WebP: this proves that the bytes decode, removes metadata such as
EXIF GPS positions, and keeps the file small for avatar sizes.
"""

from io import BytesIO

from PIL import Image, ImageOps

from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.utils.file import MAX_UPLOAD_IMAGE_PIXELS, sniff_mime_type
from onyx.utils.logger import setup_logger

logger = setup_logger()

PROFILE_IMAGE_UPLOAD_MIME_TYPES: frozenset[str] = frozenset(
    {"image/png", "image/jpeg", "image/webp"}
)
MAX_PROFILE_IMAGE_UPLOAD_BYTES = 10 * 1024 * 1024
# Covers the largest avatar the web app renders on high-density screens.
PROFILE_IMAGE_MAX_SIDE_PX = 512
PROFILE_IMAGE_WEBP_QUALITY = 85
PROFILE_IMAGE_MIME_TYPE = "image/webp"

_INVALID_IMAGE_DETAIL = "Profile photo must be a PNG, JPEG, or WebP image"


def normalize_profile_image(upload: bytes) -> bytes:
    """Return the upload as a WebP that fits in PROFILE_IMAGE_MAX_SIDE_PX.

    Raises OnyxError(INVALID_INPUT) when the bytes are not an allowed image,
    do not decode, or decode to more than MAX_UPLOAD_IMAGE_PIXELS.
    """
    if sniff_mime_type(upload, PROFILE_IMAGE_UPLOAD_MIME_TYPES) is None:
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, _INVALID_IMAGE_DETAIL)

    try:
        with Image.open(BytesIO(upload)) as image:
            # A JPEG decodes at a reduced scale, so a large camera photo stays
            # cheap. Other formats ignore this.
            image.draft("RGB", (PROFILE_IMAGE_MAX_SIDE_PX, PROFILE_IMAGE_MAX_SIDE_PX))
            # size comes from the header, so this check runs before the decode.
            width, height = image.size
            if width * height > MAX_UPLOAD_IMAGE_PIXELS:
                raise OnyxError(
                    OnyxErrorCode.INVALID_INPUT,
                    "Profile photo dimensions are too large",
                )
            # Applies the EXIF rotation; the copy it returns has no EXIF data.
            oriented = ImageOps.exif_transpose(image)
            oriented.thumbnail((PROFILE_IMAGE_MAX_SIDE_PX, PROFILE_IMAGE_MAX_SIDE_PX))
            has_alpha = (
                oriented.mode in ("RGBA", "LA", "PA") or "transparency" in oriented.info
            )
            output = BytesIO()
            oriented.convert("RGBA" if has_alpha else "RGB").save(
                output, format="WEBP", quality=PROFILE_IMAGE_WEBP_QUALITY
            )
    except OnyxError:
        raise
    except Exception as error:
        # Pillow reports a broken raster with many exception types, including
        # SyntaxError, so the catch has to be broad.
        logger.warning("Profile photo upload does not decode: %s", error)
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, _INVALID_IMAGE_DETAIL) from error

    return output.getvalue()
