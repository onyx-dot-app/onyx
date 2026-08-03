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
from onyx.utils.b64 import get_image_type, get_image_type_from_bytes
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
_MAX_STREAM_DURATION_S = 5 * 60.0

_generation_executor = ThreadPoolExecutor(
    max_workers=32, thread_name_prefix="image-gen"
)
# max_workers bounds execution, not admission — without this a burst would
# queue unbounded 10-minute runs (each retaining its decoded reference images).
_MAX_PENDING_GENERATIONS = 64
_admission_semaphore = threading.BoundedSemaphore(_MAX_PENDING_GENERATIONS)


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
    size_error = OnyxError(
        OnyxErrorCode.INVALID_INPUT,
        f"reference image exceeds {_MAX_REFERENCE_IMAGE_BYTES // (1024 * 1024)} MB",
    )
    references: list[ReferenceImage] = []
    for payload in payloads:
        # base64 inflates by 4/3; reject before allocating the decoded copy.
        if len(payload.data_base64) > _MAX_REFERENCE_IMAGE_BYTES * 4 // 3 + 4:
            raise size_error
        try:
            data = base64.b64decode(payload.data_base64, validate=True)
        except (binascii.Error, ValueError):
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                "reference image is not valid base64",
            )
        if len(data) > _MAX_REFERENCE_IMAGE_BYTES:
            raise size_error
        try:
            mime_type = get_image_type_from_bytes(data)
        except ValueError:
            mime_type = payload.mime_type or "image/png"
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
        # Set when the stream gives up; a run still queued in the executor
        # skips the provider call instead of generating for a dead client.
        self.abandoned = threading.Event()
        self.images: list[GeneratedImageData] | None = None
        self.error: Exception | None = None

    def start(self) -> None:
        if not _admission_semaphore.acquire(blocking=False):
            raise OnyxError(
                OnyxErrorCode.RATE_LIMITED,
                "Too many image generations in progress; try again shortly.",
            )
        try:
            _generation_executor.submit(self._run)
        except BaseException:
            _admission_semaphore.release()
            raise

    def _run(self) -> None:
        try:
            if self.abandoned.is_set():
                return
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
            _admission_semaphore.release()


def _keepalive_stream(run: _GenerationRun) -> Iterator[bytes]:
    deadline = time.monotonic() + _MAX_STREAM_DURATION_S
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            logger.error(
                "Image generation exceeded %ss; abandoning stream",
                _MAX_STREAM_DURATION_S,
            )
            run.abandoned.set()
            yield _error_envelope(
                OnyxError(OnyxErrorCode.GATEWAY_TIMEOUT, "Image generation timed out.")
            )
            return
        if run.done.wait(min(_KEEPALIVE_INTERVAL_S, remaining)):
            break
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
