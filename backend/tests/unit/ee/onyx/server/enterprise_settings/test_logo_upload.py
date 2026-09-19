"""Guards what the branding logo upload accepts.

The stored bytes are served unauthenticated from the app origin and are decoded
with Pillow when an email is built, so the upload has to agree with both: only
an inert raster type, and one that actually decodes.
"""

import io
from collections.abc import Generator
from pathlib import Path
from unittest.mock import MagicMock, patch

import puremagic
import pytest
from fastapi import UploadFile
from PIL import Image

from ee.onyx.server.enterprise_settings.store import (
    MAX_LOGO_PIXELS,
    MAX_LOGO_SIZE_BYTES,
    upload_logo,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError


@pytest.fixture
def file_store() -> Generator[MagicMock, None, None]:
    """Stands in for the store so a rejected body shows up as an unused mock."""
    store = MagicMock()
    with patch(
        "ee.onyx.server.enterprise_settings.store.get_default_file_store",
        return_value=store,
    ):
        yield store


def _png_bytes() -> bytes:
    buffer = io.BytesIO()
    # Noisy pixels so the compressed stream stays long, which keeps the
    # corruption below inside IDAT rather than on a chunk header.
    pixels = bytes((index * 37) % 256 for index in range(64 * 64 * 3))
    Image.frombytes("RGB", (64, 64), pixels).save(buffer, format="PNG")
    return buffer.getvalue()


def _png_with_a_broken_raster() -> bytes:
    body = bytearray(_png_bytes())
    # The 8-byte signature and the IHDR chunk end at byte 33; the IDAT chunk
    # header runs to byte 41. Scramble the compressed pixels after it.
    for index in range(50, 80):
        body[index] ^= 0xA5
    return bytes(body)


def _compression_bomb_bytes() -> bytes:
    """A real bomb: one flat grayscale plane over the pixel cap. It compresses to
    a few KB, so only a dimension check can stop it."""
    buffer = io.BytesIO()
    side = 5000
    assert side * side > MAX_LOGO_PIXELS
    Image.new("L", (side, side)).save(buffer, format="PNG")
    return buffer.getvalue()


def _upload(body: bytes, filename: str = "logo.png") -> UploadFile:
    return UploadFile(file=io.BytesIO(body), filename=filename)


def test_a_valid_png_is_stored_under_its_sniffed_type(file_store: MagicMock) -> None:
    assert upload_logo(file=_upload(_png_bytes())) is True

    assert file_store.save_file.call_args.kwargs["file_type"] == "image/png"


def test_a_png_header_with_a_broken_raster_is_rejected(file_store: MagicMock) -> None:
    body = _png_with_a_broken_raster()
    # Magic bytes alone still say PNG, so only the decode check can reject this.
    assert puremagic.magic_string(body)[0].mime_type == "image/png"

    with pytest.raises(OnyxError) as raised:
        upload_logo(file=_upload(body))

    assert raised.value.error_code is OnyxErrorCode.INVALID_INPUT
    file_store.save_file.assert_not_called()


def test_a_body_over_the_cap_is_rejected(file_store: MagicMock) -> None:
    oversized = _png_bytes() + b"\x00" * MAX_LOGO_SIZE_BYTES

    with pytest.raises(OnyxError) as raised:
        upload_logo(file=_upload(oversized))

    assert raised.value.error_code is OnyxErrorCode.PAYLOAD_TOO_LARGE
    file_store.save_file.assert_not_called()


def test_a_compression_bomb_under_the_byte_cap_is_rejected(
    file_store: MagicMock,
) -> None:
    body = _compression_bomb_bytes()
    # It is a real PNG and well under the byte cap, so neither of those stops
    # it. get_emailable_logo() would thumbnail it while sending an email.
    assert puremagic.magic_string(body)[0].mime_type == "image/png"
    assert len(body) < MAX_LOGO_SIZE_BYTES

    with pytest.raises(OnyxError) as raised:
        upload_logo(file=_upload(body))

    assert raised.value.error_code is OnyxErrorCode.INVALID_INPUT
    file_store.save_file.assert_not_called()


def test_a_disallowed_suffix_is_rejected(file_store: MagicMock) -> None:
    with pytest.raises(OnyxError) as raised:
        upload_logo(file=_upload(_png_bytes(), filename="logo.svg"))

    assert raised.value.error_code is OnyxErrorCode.INVALID_INPUT
    file_store.save_file.assert_not_called()


def test_a_broken_logo_on_disk_is_reported_rather_than_raised(
    tmp_path: Path, file_store: MagicMock
) -> None:
    # Seeding passes a path and reads the bool; it must not raise at startup.
    logo_path = tmp_path / "logo.png"
    logo_path.write_bytes(_png_with_a_broken_raster())

    assert upload_logo(file=str(logo_path)) is False
    file_store.save_file.assert_not_called()
