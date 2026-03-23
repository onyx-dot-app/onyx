"""
Unit tests for image summarization error handling.

Verifies that:
1. LLM errors produce actionable error messages (not base64 dumps)
2. Unsupported MIME type logs include the magic bytes and size
3. The ValueError raised on LLM failure preserves the original exception
"""

from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from onyx.file_processing.image_summarization import _summarize_image
from onyx.file_processing.image_summarization import summarize_image_with_error_handling


class TestSummarizeImageErrorMessage:
    """_summarize_image must not dump base64 image data into error messages."""

    def test_error_message_contains_exception_type_not_base64(self) -> None:
        """The ValueError should contain the original exception info, not message payloads."""
        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = RuntimeError("Connection timeout")

        # A fake base64-encoded image string (should NOT appear in the error)
        fake_encoded = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUg..."

        with pytest.raises(ValueError, match="RuntimeError: Connection timeout"):
            _summarize_image(fake_encoded, mock_llm, query="test")

    def test_error_message_does_not_contain_base64(self) -> None:
        """Ensure base64 data is never included in the error message."""
        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = RuntimeError("API error")

        fake_encoded = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAUA"

        with pytest.raises(ValueError) as exc_info:
            _summarize_image(fake_encoded, mock_llm)

        error_str = str(exc_info.value)
        assert "base64" not in error_str
        assert "iVBOR" not in error_str

    def test_original_exception_is_chained(self) -> None:
        """The ValueError should chain the original exception via __cause__."""
        mock_llm = MagicMock()
        original = RuntimeError("upstream failure")
        mock_llm.invoke.side_effect = original

        with pytest.raises(ValueError) as exc_info:
            _summarize_image("data:image/png;base64,abc", mock_llm)

        assert exc_info.value.__cause__ is original


class TestUnsupportedMimeTypeLogging:
    """summarize_image_with_error_handling should log useful info for unsupported formats."""

    @patch(
        "onyx.file_processing.image_summarization.summarize_image_pipeline",
        side_effect=__import__(
            "onyx.file_processing.image_summarization",
            fromlist=["UnsupportedImageFormatError"],
        ).UnsupportedImageFormatError("unsupported"),
    )
    def test_logs_magic_bytes_and_size(
        self, mock_pipeline: MagicMock  # noqa: ARG002
    ) -> None:
        """The info log should include magic bytes hex and image size."""
        mock_llm = MagicMock()
        # TIFF magic bytes (not in the supported list)
        image_data = b"\x49\x49\x2a\x00" + b"\x00" * 100

        with patch("onyx.file_processing.image_summarization.logger") as mock_logger:
            result = summarize_image_with_error_handling(
                llm=mock_llm,
                image_data=image_data,
                context_name="test_image.tiff",
            )

        assert result is None
        mock_logger.info.assert_called_once()
        log_args = mock_logger.info.call_args
        # Check the format string args contain magic bytes and size
        assert "49492a00" in str(log_args)
        assert "104" in str(log_args)  # 4 + 100 bytes
