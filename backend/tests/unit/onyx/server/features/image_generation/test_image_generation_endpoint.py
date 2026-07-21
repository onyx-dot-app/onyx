import asyncio
import base64
import json
import threading
from collections.abc import Iterator
from typing import Any
from unittest.mock import patch

import pytest
from fastapi.responses import StreamingResponse

from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.image_gen.exceptions import ImageGenerationNotConfiguredError
from onyx.image_gen.generation import GeneratedImageData
from onyx.image_gen.interfaces import ImageShape
from onyx.server.features.image_generation.api import (
    ImageGenerationRequest,
    ReferenceImagePayload,
    generate_image,
)

_HELPER = (
    "onyx.server.features.image_generation.api.generate_images_with_default_config"
)
_ENSURE = "onyx.server.features.image_generation.api.ensure_image_generation_configured"
_KEEPALIVE = "onyx.server.features.image_generation.api._KEEPALIVE_INTERVAL_S"
_MAX_DURATION = "onyx.server.features.image_generation.api._MAX_STREAM_DURATION_S"

_PNG_B64 = base64.b64encode(b"\x89PNG\r\n\x1a\n").decode()
_JPEG_B64 = base64.b64encode(b"\xff\xd8\xff\xe0jpegbody").decode()
_NON_IMAGE_B64 = base64.b64encode(b"not an image at all").decode()


@pytest.fixture(autouse=True)
def _configured() -> Iterator[None]:
    with patch(_ENSURE):
        yield


def _as_bytes(chunk: str | bytes | memoryview) -> bytes:
    if isinstance(chunk, str):
        return chunk.encode()
    return bytes(chunk)


def _drain_stream(resp: Any) -> tuple[bytes, dict]:
    """Returns (keepalive bytes, final decoded JSON) from a StreamingResponse."""
    assert isinstance(resp, StreamingResponse)
    assert resp.headers["x-accel-buffering"] == "no"
    assert resp.headers["content-type"].startswith("application/json")

    async def _collect() -> bytes:
        body = b""
        async for chunk in resp.body_iterator:
            body += _as_bytes(chunk)
        return body

    body = asyncio.run(_collect())
    stripped = body.lstrip()
    return body[: len(body) - len(stripped)], json.loads(stripped)


def test_generate_success_detects_mime() -> None:
    with patch(
        _HELPER,
        return_value=[GeneratedImageData(b64_data=_PNG_B64, revised_prompt="revised")],
    ):
        _, parsed = _drain_stream(
            generate_image(ImageGenerationRequest(prompt="a cat"))
        )
    images = parsed["images"]
    assert len(images) == 1
    assert images[0]["mime_type"] == "image/png"
    assert images[0]["revised_prompt"] == "revised"
    assert images[0]["data_base64"] == _PNG_B64


def test_generate_detects_jpeg_mime() -> None:
    with patch(
        _HELPER,
        return_value=[GeneratedImageData(b64_data=_JPEG_B64, revised_prompt="r")],
    ):
        _, parsed = _drain_stream(
            generate_image(ImageGenerationRequest(prompt="a cat"))
        )
    assert parsed["images"][0]["mime_type"] == "image/jpeg"


def test_generate_unrecognized_bytes_fall_back_to_png() -> None:
    with patch(
        _HELPER,
        return_value=[GeneratedImageData(b64_data=_NON_IMAGE_B64, revised_prompt="r")],
    ):
        _, parsed = _drain_stream(
            generate_image(ImageGenerationRequest(prompt="a cat"))
        )
    assert parsed["images"][0]["mime_type"] == "image/png"


def test_empty_prompt_rejected() -> None:
    with pytest.raises(OnyxError) as exc:
        generate_image(ImageGenerationRequest(prompt="   "))
    assert exc.value.error_code == OnyxErrorCode.INVALID_INPUT


@pytest.mark.parametrize("n", [0, 5])
def test_n_out_of_range_rejected(n: int) -> None:
    with pytest.raises(OnyxError) as exc:
        generate_image(ImageGenerationRequest(prompt="a cat", n=n))
    assert exc.value.error_code == OnyxErrorCode.INVALID_INPUT


def test_invalid_base64_reference_rejected() -> None:
    req = ImageGenerationRequest(
        prompt="a cat",
        reference_images=[ReferenceImagePayload(data_base64="not!base64!")],
    )
    with pytest.raises(OnyxError) as exc:
        generate_image(req)
    assert exc.value.error_code == OnyxErrorCode.INVALID_INPUT


def test_oversized_reference_rejected() -> None:
    with patch(
        "onyx.server.features.image_generation.api._MAX_REFERENCE_IMAGE_BYTES", 4
    ):
        with pytest.raises(OnyxError) as exc:
            generate_image(
                ImageGenerationRequest(
                    prompt="a cat",
                    reference_images=[ReferenceImagePayload(data_base64=_PNG_B64)],
                ),
            )
    assert exc.value.error_code == OnyxErrorCode.INVALID_INPUT


def test_not_configured_raises_before_stream() -> None:
    with patch(_ENSURE, side_effect=ImageGenerationNotConfiguredError("none")):
        with pytest.raises(OnyxError) as exc:
            generate_image(ImageGenerationRequest(prompt="a cat"))
    assert exc.value.error_code == OnyxErrorCode.NOT_FOUND


def test_not_configured_mid_generation_maps_to_not_found_envelope() -> None:
    with patch(_HELPER, side_effect=ImageGenerationNotConfiguredError("none")):
        _, parsed = _drain_stream(
            generate_image(ImageGenerationRequest(prompt="a cat"))
        )
    assert parsed["error_code"] == OnyxErrorCode.NOT_FOUND.code
    assert parsed["detail"] == "none"


def test_reference_unsupported_maps_to_invalid_input_envelope() -> None:
    with patch(_HELPER, side_effect=ValueError("no edits")):
        _, parsed = _drain_stream(
            generate_image(
                ImageGenerationRequest(
                    prompt="a cat",
                    reference_images=[ReferenceImagePayload(data_base64=_PNG_B64)],
                ),
            )
        )
    assert parsed["error_code"] == OnyxErrorCode.INVALID_INPUT.code
    assert parsed["detail"] == "no edits"


def test_provider_error_maps_to_llm_provider_error_envelope() -> None:
    with patch(_HELPER, side_effect=RuntimeError("boom")):
        _, parsed = _drain_stream(
            generate_image(ImageGenerationRequest(prompt="a cat"))
        )
    assert parsed["error_code"] == OnyxErrorCode.LLM_PROVIDER_ERROR.code
    assert parsed["detail"] == "Image generation failed."


def test_reference_images_decoded_and_forwarded() -> None:
    captured: dict = {}

    def _capture(**kwargs: object) -> list[GeneratedImageData]:
        captured.update(kwargs)
        return [GeneratedImageData(b64_data=_PNG_B64, revised_prompt="r")]

    with patch(_HELPER, side_effect=_capture):
        _drain_stream(
            generate_image(
                ImageGenerationRequest(
                    prompt="a cat",
                    shape=ImageShape.LANDSCAPE,
                    quality="high",
                    reference_images=[ReferenceImagePayload(data_base64=_PNG_B64)],
                ),
            )
        )
    refs = captured["reference_images"]
    assert refs is not None and len(refs) == 1
    assert refs[0].data == base64.b64decode(_PNG_B64)
    assert captured["shape"] == ImageShape.LANDSCAPE
    assert captured["quality"] == "high"


def test_slow_generation_streams_repeated_keepalives_then_result() -> None:
    release = threading.Event()

    def _slow(**_: object) -> list[GeneratedImageData]:
        release.wait(10)
        return [GeneratedImageData(b64_data=_PNG_B64, revised_prompt="r")]

    with patch(_HELPER, side_effect=_slow), patch(_KEEPALIVE, 0.02):
        resp = generate_image(ImageGenerationRequest(prompt="a cat"))
        assert isinstance(resp, StreamingResponse)
        assert resp.headers["x-accel-buffering"] == "no"

        async def _consume() -> tuple[bytes, bytes]:
            iterator = resp.body_iterator.__aiter__()
            # Multiple keepalives before releasing proves the loop re-fires
            # rather than pinging once and blocking.
            keepalives = b""
            for _ in range(3):
                keepalives += _as_bytes(await iterator.__anext__())
            release.set()
            rest_bytes = b""
            async for chunk in iterator:
                rest_bytes += _as_bytes(chunk)
            return keepalives, rest_bytes

        first, rest = asyncio.run(_consume())
        assert first == b"   "
    parsed = json.loads(rest.lstrip())
    assert parsed["images"][0]["data_base64"] == _PNG_B64
    # Whitespace-prefixed body must still be decodable as a whole.
    assert json.loads((first + rest).decode()) == parsed


def test_slow_generation_error_streams_error_envelope() -> None:
    release = threading.Event()

    def _slow_fail(**_: object) -> list[GeneratedImageData]:
        release.wait(10)
        raise RuntimeError("boom")

    with patch(_HELPER, side_effect=_slow_fail), patch(_KEEPALIVE, 0.02):
        resp = generate_image(ImageGenerationRequest(prompt="a cat"))

        async def _consume() -> tuple[bytes, bytes]:
            iterator = resp.body_iterator.__aiter__()
            first_bytes = _as_bytes(await iterator.__anext__())
            release.set()
            rest_bytes = b""
            async for chunk in iterator:
                rest_bytes += _as_bytes(chunk)
            return first_bytes, rest_bytes

        keepalive, rest = asyncio.run(_consume())
    assert keepalive == b" "
    parsed = json.loads(rest.lstrip())
    assert parsed["error_code"] == OnyxErrorCode.LLM_PROVIDER_ERROR.code
    assert parsed["detail"] == "Image generation failed."


def test_stream_deadline_yields_timeout_envelope() -> None:
    release = threading.Event()

    def _hung(**_: object) -> list[GeneratedImageData]:
        release.wait(10)
        return [GeneratedImageData(b64_data=_PNG_B64, revised_prompt="r")]

    try:
        with (
            patch(_HELPER, side_effect=_hung),
            patch(_KEEPALIVE, 0.02),
            patch(_MAX_DURATION, 0.05),
        ):
            keepalive, parsed = _drain_stream(
                generate_image(ImageGenerationRequest(prompt="a cat"))
            )
    finally:
        release.set()
    assert parsed["error_code"] == OnyxErrorCode.GATEWAY_TIMEOUT.code
    assert parsed["detail"] == "Image generation timed out."
    assert keepalive
