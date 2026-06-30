import base64
import binascii

from fastapi import APIRouter
from fastapi import Depends
from pydantic import BaseModel

from onyx.auth.permissions import require_permission
from onyx.db.enums import Permission
from onyx.db.models import User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.image_gen.exceptions import ImageGenerationNotConfiguredError
from onyx.image_gen.generation import generate_images_with_default_config
from onyx.image_gen.interfaces import ImageShape
from onyx.image_gen.interfaces import ReferenceImage
from onyx.utils.b64 import get_image_type
from onyx.utils.logger import setup_logger

logger = setup_logger()

router = APIRouter(prefix="/image-generation")

_MAX_IMAGES = 4
_MAX_REFERENCE_IMAGES = 16


class ReferenceImagePayload(BaseModel):
    data_base64: str
    mime_type: str | None = None


class ImageGenerationRequest(BaseModel):
    prompt: str
    shape: ImageShape = ImageShape.SQUARE
    n: int = 1
    quality: str | None = None
    reference_images: list[ReferenceImagePayload] = []


class GeneratedImagePayload(BaseModel):
    data_base64: str
    mime_type: str
    revised_prompt: str


class ImageGenerationResponse(BaseModel):
    images: list[GeneratedImagePayload]


def _decode_reference_images(
    payloads: list[ReferenceImagePayload],
) -> list[ReferenceImage]:
    references: list[ReferenceImage] = []
    for payload in payloads:
        try:
            data = base64.b64decode(payload.data_base64, validate=True)
        except (binascii.Error, ValueError):
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                "reference image is not valid base64",
            )
        try:
            mime_type = payload.mime_type or get_image_type(payload.data_base64)
        except ValueError:
            mime_type = "image/png"
        references.append(ReferenceImage(data=data, mime_type=mime_type))
    return references


@router.post("/generate")
def generate_image(
    request: ImageGenerationRequest,
    _user: User = Depends(require_permission(Permission.GENERATE_IMAGE)),
) -> ImageGenerationResponse:
    if not request.prompt.strip():
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, "prompt must not be empty")
    if not 1 <= request.n <= _MAX_IMAGES:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"n must be between 1 and {_MAX_IMAGES}",
        )
    if len(request.reference_images) > _MAX_REFERENCE_IMAGES:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"at most {_MAX_REFERENCE_IMAGES} reference images are allowed",
        )

    reference_images = _decode_reference_images(request.reference_images)

    try:
        generated = generate_images_with_default_config(
            prompt=request.prompt,
            shape=request.shape,
            n=request.n,
            quality=request.quality,
            reference_images=reference_images or None,
        )
    except ImageGenerationNotConfiguredError as e:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, str(e))
    except ValueError as e:
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, str(e))
    except Exception:
        logger.exception("Image generation failed")
        raise OnyxError(
            OnyxErrorCode.LLM_PROVIDER_ERROR,
            "Image generation failed.",
        )

    images: list[GeneratedImagePayload] = []
    for item in generated:
        try:
            mime_type = get_image_type(item.b64_data)
        except ValueError:
            mime_type = "image/png"
        images.append(
            GeneratedImagePayload(
                data_base64=item.b64_data,
                mime_type=mime_type,
                revised_prompt=item.revised_prompt,
            )
        )

    return ImageGenerationResponse(images=images)
