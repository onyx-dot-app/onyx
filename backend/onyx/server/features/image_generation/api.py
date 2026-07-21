import base64
import binascii
import contextvars
import json
import threading
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from onyx.auth.permissions import require_permission
from onyx.db.enums import Permission
from onyx.db.models import User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.image_gen.exceptions import ImageGenerationNotConfiguredError
from onyx.image_gen.generation import (
    GeneratedImageData,
    ensure_image_generation_configured,
    generate_images_with_default_config,
)
from onyx.image_gen.interfaces import ImageShape, ReferenceImage
from onyx.utils.b64 import get_image_type
from onyx.utils.logger import setup_logger

logger = setup_logger()

router = APIRouter(prefix="/image-generation")

_MAX_IMAGES = 4
_MAX_REFERENCE_IMAGES = 16
_MAX_REFERENCE_IMAGE_BYTES = 20 * 1024 * 1024

# Keepalives stop LB idle timeouts (e.g. ALB's 60s default) from killing
# slow generations; leading whitespace is valid JSON, so clients are unaffected.
_KEEPALIVE_INTERVAL_S = 15.0
# The keepalives defeat the LB idle timeout that used to reap hung provider
# calls, so the stream needs its own ceiling.
_MAX_STREAM_DURATION_S = 10 * 60.0

_generation_executor = ThreadPoolExecutor(
    max_workers=32, thread_name_prefix="image-gen"
)


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
        if len(data) > _MAX_REFERENCE_IMAGE_BYTES:
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                f"reference image exceeds {_MAX_REFERENCE_IMAGE_BYTES // (1024 * 1024)} MB",
            )
        try:
            mime_type = payload.mime_type or get_image_type(payload.data_base64)
        except ValueError:
            mime_type = "image/png"
        references.append(ReferenceImage(data=data, mime_type=mime_type))
    return references


def _map_generation_error(error: BaseException) -> OnyxError:
    if isinstance(error, ImageGenerationNotConfiguredError):
        return OnyxError(OnyxErrorCode.NOT_FOUND, str(error))
    if isinstance(error, ValueError):
        return OnyxError(OnyxErrorCode.INVALID_INPUT, str(error))
    logger.error("Image generation failed", exc_info=error)
    return OnyxError(
        OnyxErrorCode.LLM_PROVIDER_ERROR,
        "Image generation failed.",
    )


def _build_response(generated: list[GeneratedImageData]) -> ImageGenerationResponse:
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


def _error_envelope(error: OnyxError) -> bytes:
    return json.dumps(
        {"error_code": error.error_code.code, "detail": error.detail}
    ).encode()


class _GenerationRun:
    def __init__(
        self,
        request: ImageGenerationRequest,
        reference_images: list[ReferenceImage],
    ) -> None:
        self._prompt = request.prompt
        self._shape = request.shape
        self._n = request.n
        self._quality = request.quality
        self._reference_images = reference_images
        self._context = contextvars.copy_context()
        self.done = threading.Event()
        self.images: list[GeneratedImageData] | None = None
        self.error: Exception | None = None

    def start(self) -> None:
        _generation_executor.submit(self._run)

    def _run(self) -> None:
        try:
            self.images = self._context.run(
                generate_images_with_default_config,
                prompt=self._prompt,
                shape=self._shape,
                n=self._n,
                quality=self._quality,
                reference_images=self._reference_images or None,
            )
        except Exception as e:
            self.error = e
        finally:
            self.done.set()


def _keepalive_stream(run: _GenerationRun) -> Iterator[bytes]:
    deadline = time.monotonic() + _MAX_STREAM_DURATION_S
    while not run.done.wait(_KEEPALIVE_INTERVAL_S):
        if time.monotonic() > deadline:
            logger.error(
                "Image generation exceeded %ss; abandoning stream",
                _MAX_STREAM_DURATION_S,
            )
            yield _error_envelope(
                OnyxError(OnyxErrorCode.GATEWAY_TIMEOUT, "Image generation timed out.")
            )
            return
        yield b" "
    if run.error is not None:
        yield _error_envelope(_map_generation_error(run.error))
        return
    if run.images is None:
        yield _error_envelope(
            OnyxError(OnyxErrorCode.LLM_PROVIDER_ERROR, "Image generation failed.")
        )
        return
    yield _build_response(run.images).model_dump_json().encode()


@router.post("/generate", responses={200: {"model": ImageGenerationResponse}})
def generate_image(
    request: ImageGenerationRequest,
    _user: User = Depends(require_permission(Permission.GENERATE_IMAGE)),
) -> StreamingResponse:
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

    # Fail with a real 404 before the 200 is committed — older CLIs can't read
    # the in-band envelope, and this is the most common generation error.
    try:
        ensure_image_generation_configured()
    except ImageGenerationNotConfiguredError as e:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, str(e))

    run = _GenerationRun(request, reference_images)
    run.start()

    return StreamingResponse(
        _keepalive_stream(run),
        media_type="application/json",
        # Without this nginx buffers the keepalive bytes and the LB still sees an idle connection.
        headers={"X-Accel-Buffering": "no"},
    )
