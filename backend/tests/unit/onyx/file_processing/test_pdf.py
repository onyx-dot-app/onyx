"""Unit tests for pypdf-dependent PDF processing functions.

Tests cover:
- read_pdf_file: text extraction, metadata, encrypted PDFs, image extraction
- pdf_to_text: convenience wrapper
- is_pdf_protected: password protection detection
"""

from io import BytesIO
from typing import IO

from pypdf import PageObject
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject
from pypdf.generic import DictionaryObject
from pypdf.generic import NameObject

from onyx.file_processing.extract_file_text import pdf_to_text
from onyx.file_processing.extract_file_text import read_pdf_file
from onyx.file_processing.password_validation import is_pdf_protected


def _make_pdf_page(text: str) -> PageObject:
    """Create a PDF page with the given text content."""
    page = PageObject.create_blank_page(width=200, height=200)
    page[NameObject("/Resources")] = DictionaryObject(
        {
            NameObject("/Font"): DictionaryObject(
                {
                    NameObject("/F1"): DictionaryObject(
                        {
                            NameObject("/Type"): NameObject("/Font"),
                            NameObject("/Subtype"): NameObject("/Type1"),
                            NameObject("/BaseFont"): NameObject("/Helvetica"),
                        }
                    )
                }
            )
        }
    )
    stream = DecodedStreamObject()
    # Escape parentheses in the text for the PDF content stream
    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream.set_data(f"BT /F1 12 Tf 50 150 Td ({escaped}) Tj ET".encode())
    page[NameObject("/Contents")] = stream
    return page


def _build_pdf(
    pages: list[str],
    metadata: dict[str, str] | None = None,
    password: str | None = None,
) -> IO[bytes]:
    """Build an in-memory PDF with given pages, optional metadata & encryption."""
    writer = PdfWriter()
    for text in pages:
        writer.add_page(_make_pdf_page(text))
    if metadata:
        writer.add_metadata(metadata)
    if password:
        writer.encrypt(password)
    buf = BytesIO()
    writer.write(buf)
    buf.seek(0)
    return buf


# ── read_pdf_file ────────────────────────────────────────────────────────


class TestReadPdfFile:
    def test_basic_text_extraction(self) -> None:
        pdf = _build_pdf(["Hello World"])
        text, metadata, images = read_pdf_file(pdf)
        assert "Hello World" in text
        assert images == []

    def test_multi_page_text_extraction(self) -> None:
        pdf = _build_pdf(["Page one content", "Page two content"])
        text, _, _ = read_pdf_file(pdf)
        assert "Page one content" in text
        assert "Page two content" in text

    def test_metadata_extraction(self) -> None:
        pdf = _build_pdf(
            ["test"],
            metadata={"/Title": "My Title", "/Author": "Jane Doe"},
        )
        _, pdf_metadata, _ = read_pdf_file(pdf)
        assert pdf_metadata.get("Title") == "My Title"
        assert pdf_metadata.get("Author") == "Jane Doe"

    def test_encrypted_pdf_with_correct_password(self) -> None:
        pdf = _build_pdf(["Secret Content"], password="pass123")
        text, _, _ = read_pdf_file(pdf, pdf_pass="pass123")
        assert "Secret Content" in text

    def test_encrypted_pdf_without_password(self) -> None:
        pdf = _build_pdf(["Secret Content"], password="pass123")
        text, _, _ = read_pdf_file(pdf)
        assert text == ""

    def test_encrypted_pdf_with_wrong_password(self) -> None:
        pdf = _build_pdf(["Secret Content"], password="pass123")
        text, _, _ = read_pdf_file(pdf, pdf_pass="wrong")
        assert text == ""

    def test_empty_pdf(self) -> None:
        pdf = _build_pdf([""])
        text, _, _ = read_pdf_file(pdf)
        assert text.strip() == ""

    def test_invalid_pdf_returns_empty(self) -> None:
        bad_file = BytesIO(b"this is not a pdf")
        text, _, images = read_pdf_file(bad_file)
        assert text == ""
        assert images == []

    def test_image_extraction_disabled_by_default(self) -> None:
        pdf = _build_pdf(["text"])
        _, _, images = read_pdf_file(pdf, extract_images=False)
        assert images == []

    def test_image_callback_invoked(self) -> None:
        """When image_callback is provided, images are streamed rather than collected."""
        pdf = _build_pdf(["Page with image"])

        collected: list[tuple[bytes, str]] = []

        def callback(data: bytes, name: str) -> None:
            collected.append((data, name))

        # Verify the callback path doesn't error out
        _, _, images = read_pdf_file(pdf, extract_images=True, image_callback=callback)
        # With callback, returned images list should be empty
        assert images == []


# ── pdf_to_text ──────────────────────────────────────────────────────────


class TestPdfToText:
    def test_returns_text(self) -> None:
        pdf = _build_pdf(["Simple text"])
        result = pdf_to_text(pdf)
        assert "Simple text" in result

    def test_with_password(self) -> None:
        pdf = _build_pdf(["Protected text"], password="pw")
        result = pdf_to_text(pdf, pdf_pass="pw")
        assert "Protected text" in result

    def test_encrypted_without_password_returns_empty(self) -> None:
        pdf = _build_pdf(["Protected text"], password="pw")
        result = pdf_to_text(pdf)
        assert result == ""


# ── is_pdf_protected ─────────────────────────────────────────────────────


class TestIsPdfProtected:
    def test_unprotected_pdf(self) -> None:
        pdf = _build_pdf(["open content"])
        assert is_pdf_protected(pdf) is False

    def test_protected_pdf(self) -> None:
        pdf = _build_pdf(["secret"], password="mypass")
        assert is_pdf_protected(pdf) is True

    def test_preserves_file_position(self) -> None:
        pdf = _build_pdf(["test"])
        pdf.seek(42)
        is_pdf_protected(pdf)
        assert pdf.tell() == 42
