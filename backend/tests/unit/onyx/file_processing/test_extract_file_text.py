import io
from unittest.mock import Mock
from unittest.mock import patch

from onyx.file_processing.extract_file_text import detect_encoding
from onyx.file_processing.extract_file_text import extract_text_and_images
from onyx.file_processing.extract_file_text import ExtractionResult
from onyx.file_processing.extract_file_text import get_file_ext
from onyx.file_processing.extract_file_text import is_accepted_file_ext
from onyx.file_processing.extract_file_text import is_text_file
from onyx.file_processing.extract_file_text import OnyxExtensionType
from onyx.file_processing.extract_file_text import pdf_to_text
from onyx.file_processing.extract_file_text import read_pdf_file


class TestPDFProcessing:
    """Test PDF processing functionality with focus on error handling."""

    def test_read_pdf_file_empty_file(self):
        """Test that empty files are handled gracefully."""
        empty_file = io.BytesIO(b"")

        text, metadata, images = read_pdf_file(empty_file)

        assert text == ""
        assert metadata == {}
        assert images == []

    def test_read_pdf_file_valid_pdf(self):
        """Test successful PDF reading with valid content."""
        # Create a minimal PDF-like content (this is not a real PDF, just for testing)
        pdf_content = (
            b"%PDF-1.4\n"
            b"1 0 obj\n<<\n/Type /Catalog\n/Pages 2 0 R\n>>\nendobj\n"
            b"2 0 obj\n<<\n/Type /Pages\n/Kids [3 0 R]\n/Count 1\n>>\nendobj\n"
            b"3 0 obj\n<<\n/Type /Page\n/Parent 2 0 R\n/MediaBox [0 0 612 792]\n"
            b"/Contents 4 0 R\n>>\nendobj\n"
            b"4 0 obj\n<<\n/Length 44\n>>\nstream\n"
            b"BT\n/F1 12 Tf\n72 720 Td\n(Hello World) Tj\nET\nendstream\nendobj\n"
            b"xref\n0 5\n0000000000 65535 f \n0000000009 00000 n \n0000000058 00000 n \n"
            b"0000000115 00000 n \n0000000204 00000 n \n"
            b"trailer\n<<\n/Size 5\n/Root 1 0 R\n>>\nstartxref\n297\n%%EOF"
        )

        with patch(
            "onyx.file_processing.extract_file_text.PdfReader"
        ) as mock_pdf_reader:
            mock_reader = Mock()
            mock_reader.is_encrypted = False
            mock_reader.metadata = {}  # Set as empty dict instead of Mock
            mock_reader.pages = [Mock()]
            mock_reader.pages[0].extract_text.return_value = "Hello World"
            mock_pdf_reader.return_value = mock_reader

            text, metadata, images = read_pdf_file(io.BytesIO(pdf_content))

            assert text == "Hello World"
            assert metadata == {}
            assert images == []

    def test_read_pdf_file_encrypted_with_password(self):
        """Test encrypted PDF with password."""
        pdf_content = b"encrypted_pdf_content"

        with patch(
            "onyx.file_processing.extract_file_text.PdfReader"
        ) as mock_pdf_reader:
            mock_reader = Mock()
            mock_reader.is_encrypted = True
            mock_reader.decrypt.return_value = 1  # Success
            mock_reader.metadata = None
            mock_reader.pages = [Mock()]
            mock_reader.pages[0].extract_text.return_value = "Decrypted content"
            mock_pdf_reader.return_value = mock_reader

            text, metadata, images = read_pdf_file(
                io.BytesIO(pdf_content), pdf_pass="password"
            )

            assert text == "Decrypted content"
            assert metadata == {}
            assert images == []

    def test_read_pdf_file_encrypted_without_password(self):
        """Test encrypted PDF without password returns empty result."""
        pdf_content = b"encrypted_pdf_content"

        with patch(
            "onyx.file_processing.extract_file_text.PdfReader"
        ) as mock_pdf_reader:
            mock_reader = Mock()
            mock_reader.is_encrypted = True
            mock_pdf_reader.return_value = mock_reader

            text, metadata, images = read_pdf_file(io.BytesIO(pdf_content))

            assert text == ""
            assert metadata == {}
            assert images == []

    def test_read_pdf_file_with_metadata(self):
        """Test PDF with metadata extraction."""
        pdf_content = b"pdf_with_metadata"

        with patch(
            "onyx.file_processing.extract_file_text.PdfReader"
        ) as mock_pdf_reader:
            mock_reader = Mock()
            mock_reader.is_encrypted = False
            mock_reader.metadata = {
                "/Title": "Test Document",
                "/Author": "Test Author",
                "/Subject": "Test Subject",
            }
            mock_reader.pages = [Mock()]
            mock_reader.pages[0].extract_text.return_value = "Content"
            mock_pdf_reader.return_value = mock_reader

            text, metadata, images = read_pdf_file(io.BytesIO(pdf_content))

            assert text == "Content"
            assert metadata["Title"] == "Test Document"
            assert metadata["Author"] == "Test Author"
            assert metadata["Subject"] == "Test Subject"

    def test_read_pdf_file_pdf_stream_error(self):
        """Test handling of PdfStreamError."""
        pdf_content = b"invalid_pdf"

        with patch(
            "onyx.file_processing.extract_file_text.PdfReader"
        ) as mock_pdf_reader:
            from pypdf.errors import PdfStreamError

            mock_pdf_reader.side_effect = PdfStreamError("Invalid PDF")

            text, metadata, images = read_pdf_file(io.BytesIO(pdf_content))

            assert text == ""
            assert metadata == {}
            assert images == []

    def test_read_pdf_file_empty_file_error(self):
        """Test handling of EmptyFileError specifically."""
        pdf_content = b""

        with patch(
            "onyx.file_processing.extract_file_text.PdfReader"
        ) as mock_pdf_reader:
            # Simulate the specific error we're fixing
            mock_pdf_reader.side_effect = Exception("Cannot read an empty file")

            text, metadata, images = read_pdf_file(io.BytesIO(pdf_content))

            assert text == ""
            assert metadata == {}
            assert images == []

    def test_read_pdf_file_other_exception(self):
        """Test handling of other exceptions."""
        pdf_content = b"pdf_content"

        with patch(
            "onyx.file_processing.extract_file_text.PdfReader"
        ) as mock_pdf_reader:
            mock_pdf_reader.side_effect = Exception("Some other error")

            text, metadata, images = read_pdf_file(io.BytesIO(pdf_content))

            assert text == ""
            assert metadata == {}
            assert images == []

    def test_read_pdf_file_with_images(self):
        """Test PDF with image extraction enabled."""
        pdf_content = b"pdf_with_images"

        with patch(
            "onyx.file_processing.extract_file_text.PdfReader"
        ) as mock_pdf_reader, patch(
            "onyx.file_processing.extract_file_text.Image"
        ) as mock_image, patch(
            "onyx.file_processing.extract_file_text.get_image_extraction_and_analysis_enabled"
        ) as mock_enabled:

            mock_enabled.return_value = True

            mock_reader = Mock()
            mock_reader.is_encrypted = False
            mock_reader.metadata = None
            mock_reader.pages = [Mock()]
            mock_reader.pages[0].extract_text.return_value = "Content"
            mock_reader.pages[0].images = [Mock()]
            mock_reader.pages[0].images[0].data = b"image_data"
            mock_reader.pages[0].images[0].name = "test_image"
            mock_pdf_reader.return_value = mock_reader

            mock_image_instance = Mock()
            mock_image_instance.format = "PNG"
            mock_image.open.return_value = mock_image_instance

            text, metadata, images = read_pdf_file(
                io.BytesIO(pdf_content), extract_images=True
            )

            assert text == "Content"
            assert metadata == {}
            assert len(images) == 1
            assert images[0][1] == "page_1_image_test_image.png"


class TestPDFToText:
    """Test the pdf_to_text wrapper function."""

    def test_pdf_to_text_success(self):
        """Test successful PDF text extraction."""
        pdf_content = b"pdf_content"

        with patch("onyx.file_processing.extract_file_text.read_pdf_file") as mock_read:
            mock_read.return_value = ("Extracted text", {}, [])

            result = pdf_to_text(io.BytesIO(pdf_content))

            assert result == "Extracted text"

    def test_pdf_to_text_empty_file_error(self):
        """Test handling of EmptyFileError in pdf_to_text."""
        pdf_content = b""

        with patch("onyx.file_processing.extract_file_text.read_pdf_file") as mock_read:
            mock_read.side_effect = Exception("Cannot read an empty file")

            result = pdf_to_text(io.BytesIO(pdf_content))

            assert result == ""

    def test_pdf_to_text_other_exception(self):
        """Test handling of other exceptions in pdf_to_text."""
        pdf_content = b"pdf_content"

        with patch("onyx.file_processing.extract_file_text.read_pdf_file") as mock_read:
            mock_read.side_effect = Exception("Some other error")

            result = pdf_to_text(io.BytesIO(pdf_content))

            assert result == ""


class TestFileValidation:
    """Test file validation utilities."""

    def test_is_text_file_with_text(self):
        """Test text file detection with valid text."""
        text_content = b"This is valid text content with printable characters."
        file_obj = io.BytesIO(text_content)

        assert is_text_file(file_obj) is True

    def test_is_text_file_with_binary(self):
        """Test text file detection with binary content."""
        binary_content = b"\x00\x01\x02\x03\x04\x05\x06\x07\x08\x09"
        file_obj = io.BytesIO(binary_content)

        assert is_text_file(file_obj) is False

    def test_detect_encoding_utf8(self):
        """Test encoding detection with UTF-8 content."""
        utf8_content = "Hello, 世界!".encode("utf-8")
        file_obj = io.BytesIO(utf8_content)

        encoding = detect_encoding(file_obj)

        assert encoding in ["utf-8", "ascii"]  # chardet might detect either

    def test_get_file_ext(self):
        """Test file extension extraction."""
        assert get_file_ext("document.pdf") == ".pdf"
        assert get_file_ext("file.docx") == ".docx"
        assert get_file_ext("no_extension") == ""
        assert get_file_ext("/path/to/file.txt") == ".txt"

    def test_is_accepted_file_ext(self):
        """Test file extension acceptance."""
        assert is_accepted_file_ext(".pdf", OnyxExtensionType.Document) is True
        assert is_accepted_file_ext(".txt", OnyxExtensionType.Plain) is True
        assert is_accepted_file_ext(".png", OnyxExtensionType.Multimedia) is True
        assert is_accepted_file_ext(".pdf", OnyxExtensionType.Plain) is False
        assert is_accepted_file_ext(".unknown", OnyxExtensionType.All) is False


class TestExtractTextAndImages:
    """Test the main extract_text_and_images function."""

    def test_extract_text_and_images_pdf(self):
        """Test PDF extraction through the main function."""
        pdf_content = b"pdf_content"

        with patch(
            "onyx.file_processing.extract_file_text.get_unstructured_api_key"
        ) as mock_unstructured, patch(
            "onyx.file_processing.extract_file_text.read_pdf_file"
        ) as mock_read:

            mock_unstructured.return_value = None  # No unstructured API key
            mock_read.return_value = ("PDF text", {"Title": "Test"}, [])

            result = extract_text_and_images(io.BytesIO(pdf_content), "test.pdf")

            assert isinstance(result, ExtractionResult)
            assert result.text_content == "PDF text"
            assert result.metadata["Title"] == "Test"
            assert result.embedded_images == []

    def test_extract_text_and_images_docx(self):
        """Test DOCX extraction through the main function."""
        docx_content = b"docx_content"

        with patch(
            "onyx.file_processing.extract_file_text.get_unstructured_api_key"
        ) as mock_unstructured, patch(
            "onyx.file_processing.extract_file_text.docx_to_text_and_images"
        ) as mock_docx:

            mock_unstructured.return_value = None  # No unstructured API key
            mock_docx.return_value = ("DOCX text", [])

            result = extract_text_and_images(io.BytesIO(docx_content), "test.docx")

            assert isinstance(result, ExtractionResult)
            assert result.text_content == "DOCX text"
            assert result.embedded_images == []

    def test_extract_text_and_images_text_file(self):
        """Test text file extraction through the main function."""
        text_content = b"This is a text file"

        with patch(
            "onyx.file_processing.extract_file_text.get_unstructured_api_key"
        ) as mock_unstructured, patch(
            "onyx.file_processing.extract_file_text.extract_result_from_text_file"
        ) as mock_text:

            mock_unstructured.return_value = None  # No unstructured API key
            mock_text.return_value = ExtractionResult(
                "Text content", [], {"encoding": "utf-8"}
            )

            result = extract_text_and_images(io.BytesIO(text_content), "test.txt")

            assert isinstance(result, ExtractionResult)
            assert result.text_content == "Text content"
            assert result.metadata["encoding"] == "utf-8"

    def test_extract_text_and_images_unknown_extension(self):
        """Test handling of unknown file extensions."""
        unknown_content = b"unknown content"

        with patch(
            "onyx.file_processing.extract_file_text.get_unstructured_api_key"
        ) as mock_unstructured:
            mock_unstructured.return_value = None  # No unstructured API key

            result = extract_text_and_images(
                io.BytesIO(unknown_content), "test.unknown"
            )

            assert isinstance(result, ExtractionResult)
            assert result.text_content == ""
            assert result.embedded_images == []
            assert result.metadata == {}

    def test_extract_text_and_images_exception_handling(self):
        """Test that exceptions are handled gracefully."""
        problematic_content = b"problematic"

        with patch(
            "onyx.file_processing.extract_file_text.get_unstructured_api_key"
        ) as mock_unstructured, patch(
            "onyx.file_processing.extract_file_text.get_file_ext"
        ) as mock_ext:

            mock_unstructured.return_value = None  # No unstructured API key
            mock_ext.side_effect = Exception("Test exception")

            result = extract_text_and_images(
                io.BytesIO(problematic_content), "test.pdf"
            )

            assert isinstance(result, ExtractionResult)
            assert result.text_content == ""
            assert result.embedded_images == []
            assert result.metadata == {}

    def test_extract_text_and_images_with_unstructured_api(self):
        """Test extraction when unstructured API is available."""
        pdf_content = b"pdf_content"

        with patch(
            "onyx.file_processing.extract_file_text.get_unstructured_api_key"
        ) as mock_unstructured, patch(
            "onyx.file_processing.extract_file_text.unstructured_to_text"
        ) as mock_unstructured_text:

            mock_unstructured.return_value = "fake_api_key"
            mock_unstructured_text.return_value = "Unstructured extracted text"

            result = extract_text_and_images(io.BytesIO(pdf_content), "test.pdf")

            assert isinstance(result, ExtractionResult)
            assert result.text_content == "Unstructured extracted text"
            assert result.embedded_images == []
            assert result.metadata == {}

    def test_extract_text_and_images_unstructured_fallback(self):
        """Test fallback to normal processing when unstructured fails."""
        pdf_content = b"pdf_content"

        with patch(
            "onyx.file_processing.extract_file_text.get_unstructured_api_key"
        ) as mock_unstructured, patch(
            "onyx.file_processing.extract_file_text.unstructured_to_text"
        ) as mock_unstructured_text, patch(
            "onyx.file_processing.extract_file_text.read_pdf_file"
        ) as mock_read:

            mock_unstructured.return_value = "fake_api_key"
            mock_unstructured_text.side_effect = Exception("Unstructured failed")
            mock_read.return_value = ("PDF text", {"Title": "Test"}, [])

            result = extract_text_and_images(io.BytesIO(pdf_content), "test.pdf")

            assert isinstance(result, ExtractionResult)
            assert result.text_content == "PDF text"
            assert result.metadata["Title"] == "Test"
            assert result.embedded_images == []
