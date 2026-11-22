from io import BytesIO

import numpy as np
import pytest
from PIL import Image

from onyx.file_processing.image_summarization import _resize_image_if_needed

_SIDE = 2000
# The top-left quarter of every transparent fixture is fully transparent.
_TRANSPARENT_BLOCK = _SIDE // 2
_TRANSPARENT_PALETTE_INDEX = 0


def _noise_rgb(side: int) -> Image.Image:
    rng = np.random.default_rng(0)
    return Image.fromarray(rng.integers(0, 256, (side, side, 3), dtype=np.uint8))


def _png(image: Image.Image, transparency: int | None = None) -> bytes:
    buffer = BytesIO()
    if transparency is None:
        image.save(buffer, format="PNG", compress_level=0)
    else:
        image.save(buffer, format="PNG", compress_level=0, transparency=transparency)
    return buffer.getvalue()


_EXIF_ORIENTATION_TAG = 0x0112
_ROTATE_90_CLOCKWISE = 6
_TRANSPARENT_RGB = (255, 0, 0)


def _noise_png(mode: str, side: int = _SIDE) -> bytes:
    """Noise compresses badly, so the PNG stays over the resize threshold."""
    rgb = _noise_rgb(side)
    if mode == "RGB":
        return _png(rgb)
    if mode == "RGBA":
        alpha = np.full((side, side), 255, dtype=np.uint8)
        alpha[:_TRANSPARENT_BLOCK, :_TRANSPARENT_BLOCK] = 0
        rgba = rgb.convert("RGBA")
        rgba.putalpha(Image.fromarray(alpha))
        return _png(rgba)
    if mode == "P":
        indices = np.array(rgb.convert("P"))
        indices[:_TRANSPARENT_BLOCK, :_TRANSPARENT_BLOCK] = _TRANSPARENT_PALETTE_INDEX
        palette_image = Image.fromarray(indices, mode="P")
        palette_image.putpalette(rgb.convert("P").getpalette() or [])
        return _png(palette_image, transparency=_TRANSPARENT_PALETTE_INDEX)
    if mode == "RGB with transparent colour":
        pixels = np.array(rgb)
        pixels[:_TRANSPARENT_BLOCK, :_TRANSPARENT_BLOCK] = _TRANSPARENT_RGB
        buffer = BytesIO()
        Image.fromarray(pixels).save(
            buffer, format="PNG", compress_level=0, transparency=_TRANSPARENT_RGB
        )
        return buffer.getvalue()
    raise ValueError(mode)


def test_small_image_is_returned_unchanged() -> None:
    data = _noise_png("RGB", side=200)
    assert _resize_image_if_needed(data) is data


@pytest.mark.parametrize("mode", ["RGB", "RGBA", "P"])
def test_large_image_becomes_small_jpeg(mode: str) -> None:
    data = _noise_png(mode)
    assert len(data) > 3 * 1024 * 1024

    resized = _resize_image_if_needed(data)

    with Image.open(BytesIO(resized)) as image:
        assert image.format == "JPEG"
        assert max(image.size) <= 1024
    assert len(resized) < 1024 * 1024


@pytest.mark.parametrize("mode", ["RGBA", "P", "RGB with transparent colour"])
def test_transparent_regions_become_white(mode: str) -> None:
    resized = _resize_image_if_needed(_noise_png(mode))

    with Image.open(BytesIO(resized)) as image:
        # Middle of the transparent quarter, after scaling down to 1024 px.
        r, g, b = image.convert("RGB").getpixel((256, 256))
    # JPEG compression shifts colours a little, so allow some tolerance.
    assert min(r, g, b) >= 240, f"want white, got {(r, g, b)}"


def test_exif_rotation_is_applied_before_the_tag_is_dropped() -> None:
    # Stored landscape, but the tag says a viewer should show it portrait.
    landscape = _noise_rgb(_SIDE).resize((3000, 2000))
    exif = Image.Exif()
    exif[_EXIF_ORIENTATION_TAG] = _ROTATE_90_CLOCKWISE
    buffer = BytesIO()
    landscape.save(buffer, format="JPEG", quality=100, exif=exif.tobytes())
    data = buffer.getvalue()
    assert len(data) > 3 * 1024 * 1024

    with Image.open(BytesIO(_resize_image_if_needed(data))) as image:
        width, height = image.size
    assert height > width, f"want portrait, got {width}x{height}"
