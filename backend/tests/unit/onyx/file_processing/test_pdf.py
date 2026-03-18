"""Unit tests for pypdf-dependent PDF processing functions.

Tests cover:
- read_pdf_file: text extraction, metadata, encrypted PDFs, image extraction
- pdf_to_text: convenience wrapper
- is_pdf_protected: password protection detection

Fixture PDFs live in ./fixtures/ and are pre-built so the test layer has no
dependency on pypdf internals (pypdf.generic).
"""

from io import BytesIO
from pathlib import Path

from onyx.file_processing.extract_file_text import pdf_to_text
from onyx.file_processing.extract_file_text import read_pdf_file
from onyx.file_processing.password_validation import is_pdf_protected

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> BytesIO:
    return BytesIO((FIXTURES / name).read_bytes())


# ── read_pdf_file ────────────────────────────────────────────────────────


class TestReadPdfFile:
    def test_basic_text_extraction(self) -> None:
        text, _, images = read_pdf_file(_load("simple.pdf"))
        assert "Hello World" in text
        assert images == []

    def test_multi_page_text_extraction(self) -> None:
        text, _, _ = read_pdf_file(_load("multipage.pdf"))
        assert "Page one content" in text
        assert "Page two content" in text

    def test_metadata_extraction(self) -> None:
        _, pdf_metadata, _ = read_pdf_file(_load("with_metadata.pdf"))
        assert pdf_metadata.get("Title") == "My Title"
        assert pdf_metadata.get("Author") == "Jane Doe"

    def test_encrypted_pdf_with_correct_password(self) -> None:
        text, _, _ = read_pdf_file(_load("encrypted.pdf"), pdf_pass="pass123")
        assert "Secret Content" in text

    def test_encrypted_pdf_without_password(self) -> None:
        text, _, _ = read_pdf_file(_load("encrypted.pdf"))
        assert text == ""

    def test_encrypted_pdf_with_wrong_password(self) -> None:
        text, _, _ = read_pdf_file(_load("encrypted.pdf"), pdf_pass="wrong")
        assert text == ""

    def test_empty_pdf(self) -> None:
        text, _, _ = read_pdf_file(_load("empty.pdf"))
        assert text.strip() == ""

    def test_invalid_pdf_returns_empty(self) -> None:
        text, _, images = read_pdf_file(BytesIO(b"this is not a pdf"))
        assert text == ""
        assert images == []

    def test_image_extraction_disabled_by_default(self) -> None:
        _, _, images = read_pdf_file(_load("with_image.pdf"))
        assert images == []

    def test_image_extraction_collects_images(self) -> None:
        _, _, images = read_pdf_file(_load("with_image.pdf"), extract_images=True)
        assert len(images) == 1
        img_bytes, img_name = images[0]
        assert len(img_bytes) > 0
        assert img_name  # non-empty name

    def test_image_callback_streams_instead_of_collecting(self) -> None:
        """With image_callback, images are streamed via callback and not accumulated."""
        collected: list[tuple[bytes, str]] = []

        def callback(data: bytes, name: str) -> None:
            collected.append((data, name))

        _, _, images = read_pdf_file(
            _load("with_image.pdf"), extract_images=True, image_callback=callback
        )
        # Callback received the image
        assert len(collected) == 1
        assert len(collected[0][0]) > 0
        # Returned list is empty when callback is used
        assert images == []


# ── pdf_to_text ──────────────────────────────────────────────────────────


class TestPdfToText:
    def test_returns_text(self) -> None:
        assert "Hello World" in pdf_to_text(_load("simple.pdf"))

    def test_with_password(self) -> None:
        assert "Secret Content" in pdf_to_text(
            _load("encrypted.pdf"), pdf_pass="pass123"
        )

    def test_encrypted_without_password_returns_empty(self) -> None:
        assert pdf_to_text(_load("encrypted.pdf")) == ""


# ── is_pdf_protected ─────────────────────────────────────────────────────


class TestIsPdfProtected:
    def test_unprotected_pdf(self) -> None:
        assert is_pdf_protected(_load("simple.pdf")) is False

    def test_protected_pdf(self) -> None:
        assert is_pdf_protected(_load("encrypted.pdf")) is True

    def test_preserves_file_position(self) -> None:
        pdf = _load("simple.pdf")
        pdf.seek(42)
        is_pdf_protected(pdf)
        assert pdf.tell() == 42
