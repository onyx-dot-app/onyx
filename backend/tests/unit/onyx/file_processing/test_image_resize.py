from io import BytesIO

import numpy as np
import pytest
from PIL import Image

from onyx.file_processing.image_summarization import _resize_image_if_needed


def _noise_png(mode: str, side: int) -> bytes:
    rng = np.random.default_rng(0)
    rgb = Image.fromarray(rng.integers(0, 256, (side, side, 3), dtype=np.uint8))
    image = rgb.convert(mode) if mode != "RGB" else rgb
    if mode == "RGBA":
        image.putalpha(128)
    buffer = BytesIO()
    image.save(buffer, format="PNG", compress_level=0)
    return buffer.getvalue()


def test_small_image_is_returned_unchanged() -> None:
    data = _noise_png("RGB", 200)
    assert _resize_image_if_needed(data) is data


@pytest.mark.parametrize("mode", ["RGB", "RGBA", "P"])
def test_large_image_becomes_small_jpeg(mode: str) -> None:
    data = _noise_png(mode, 2000)
    assert len(data) > 3 * 1024 * 1024

    resized = _resize_image_if_needed(data)

    with Image.open(BytesIO(resized)) as image:
        assert image.format == "JPEG"
        assert max(image.size) <= 1024
    assert len(resized) < 1024 * 1024
