import base64
from unittest.mock import patch

import pytest

from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.image_gen.exceptions import ImageGenerationNotConfiguredError
from onyx.image_gen.generation import GeneratedImageData
from onyx.image_gen.interfaces import ImageShape
from onyx.server.features.image_generation.api import generate_image
from onyx.server.features.image_generation.api import ImageGenerationRequest
from onyx.server.features.image_generation.api import ReferenceImagePayload

_HELPER = (
    "onyx.server.features.image_generation.api.generate_images_with_default_config"
)

_PNG_B64 = base64.b64encode(b"\x89PNG\r\n\x1a\n").decode()
_JPEG_B64 = base64.b64encode(b"\xff\xd8\xff\xe0jpegbody").decode()
_NON_IMAGE_B64 = base64.b64encode(b"not an image at all").decode()


def test_generate_success_detects_mime() -> None:
    with patch(
        _HELPER,
        return_value=[GeneratedImageData(b64_data=_PNG_B64, revised_prompt="revised")],
    ):
        resp = generate_image(ImageGenerationRequest(prompt="a cat"))
    assert len(resp.images) == 1
    assert resp.images[0].mime_type == "image/png"
    assert resp.images[0].revised_prompt == "revised"
    assert resp.images[0].data_base64 == _PNG_B64


def test_generate_detects_jpeg_mime() -> None:
    with patch(
        _HELPER,
        return_value=[GeneratedImageData(b64_data=_JPEG_B64, revised_prompt="r")],
    ):
        resp = generate_image(ImageGenerationRequest(prompt="a cat"))
    assert resp.images[0].mime_type == "image/jpeg"


def test_generate_unrecognized_bytes_fall_back_to_png() -> None:
    with patch(
        _HELPER,
        return_value=[GeneratedImageData(b64_data=_NON_IMAGE_B64, revised_prompt="r")],
    ):
        resp = generate_image(ImageGenerationRequest(prompt="a cat"))
    assert resp.images[0].mime_type == "image/png"


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


def test_not_configured_maps_to_not_found() -> None:
    with patch(_HELPER, side_effect=ImageGenerationNotConfiguredError("none")):
        with pytest.raises(OnyxError) as exc:
            generate_image(ImageGenerationRequest(prompt="a cat"))
    assert exc.value.error_code == OnyxErrorCode.NOT_FOUND


def test_reference_unsupported_maps_to_invalid_input() -> None:
    with patch(_HELPER, side_effect=ValueError("no edits")):
        with pytest.raises(OnyxError) as exc:
            generate_image(
                ImageGenerationRequest(
                    prompt="a cat",
                    reference_images=[ReferenceImagePayload(data_base64=_PNG_B64)],
                ),
            )
    assert exc.value.error_code == OnyxErrorCode.INVALID_INPUT


def test_provider_error_maps_to_llm_provider_error() -> None:
    with patch(_HELPER, side_effect=RuntimeError("boom")):
        with pytest.raises(OnyxError) as exc:
            generate_image(ImageGenerationRequest(prompt="a cat"))
    assert exc.value.error_code == OnyxErrorCode.LLM_PROVIDER_ERROR


def test_reference_images_decoded_and_forwarded() -> None:
    captured: dict = {}

    def _capture(**kwargs: object) -> list[GeneratedImageData]:
        captured.update(kwargs)
        return [GeneratedImageData(b64_data=_PNG_B64, revised_prompt="r")]

    with patch(_HELPER, side_effect=_capture):
        generate_image(
            ImageGenerationRequest(
                prompt="a cat",
                shape=ImageShape.LANDSCAPE,
                quality="high",
                reference_images=[ReferenceImagePayload(data_base64=_PNG_B64)],
            ),
        )
    refs = captured["reference_images"]
    assert refs is not None and len(refs) == 1
    assert refs[0].data == base64.b64decode(_PNG_B64)
    assert captured["shape"] == ImageShape.LANDSCAPE
    assert captured["quality"] == "high"
