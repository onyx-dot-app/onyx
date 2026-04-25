"""
Unit tests verifying that LiteLLM error details are extracted and surfaced
in image summarization error messages.

When the LLM call fails, the error handler should include the status_code,
llm_provider, and model from LiteLLM exceptions so operators can diagnose
the root cause (rate limit, content filter, unsupported vision, etc.)
without needing to dig through LiteLLM internals.
"""

from unittest.mock import MagicMock

import pytest

from onyx.file_processing.image_summarization import _summarize_image


def _make_litellm_style_error(
    *,
    message: str = "API error",
    status_code: int | None = None,
    llm_provider: str | None = None,
    model: str | None = None,
) -> RuntimeError:
    """Create an exception with LiteLLM-style attributes."""
    exc = RuntimeError(message)
    if status_code is not None:
        exc.status_code = status_code  # ty: ignore[unresolved-attribute]
    if llm_provider is not None:
        exc.llm_provider = llm_provider  # ty: ignore[unresolved-attribute]
    if model is not None:
        exc.model = model  # ty: ignore[unresolved-attribute]
    return exc


class TestLiteLLMErrorExtraction:
    """Verify that LiteLLM error attributes are included in the ValueError."""

    def test_status_code_included(self) -> None:
        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = _make_litellm_style_error(
            message="Content filter triggered",
            status_code=400,
            llm_provider="azure",
            model="gpt-4o",
        )

        with pytest.raises(ValueError, match="status_code=400"):
            _summarize_image("data:image/png;base64,abc", mock_llm)

    def test_llm_provider_included(self) -> None:
        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = _make_litellm_style_error(
            message="Bad request",
            status_code=400,
            llm_provider="azure",
        )

        with pytest.raises(ValueError, match="llm_provider=azure"):
            _summarize_image("data:image/png;base64,abc", mock_llm)

    def test_model_included(self) -> None:
        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = _make_litellm_style_error(
            message="Bad request",
            model="gpt-4o",
        )

        with pytest.raises(ValueError, match="model=gpt-4o"):
            _summarize_image("data:image/png;base64,abc", mock_llm)

    def test_all_fields_in_single_message(self) -> None:
        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = _make_litellm_style_error(
            message="Rate limit exceeded",
            status_code=429,
            llm_provider="azure",
            model="gpt-4o",
        )

        with pytest.raises(ValueError) as exc_info:
            _summarize_image("data:image/png;base64,abc", mock_llm)

        msg = str(exc_info.value)
        assert "status_code=429" in msg
        assert "llm_provider=azure" in msg
        assert "model=gpt-4o" in msg
        assert "Rate limit exceeded" in msg

    def test_plain_exception_without_litellm_attrs(self) -> None:
        """Non-LiteLLM exceptions should still produce a useful message."""
        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = ConnectionError("Connection refused")

        with pytest.raises(ValueError) as exc_info:
            _summarize_image("data:image/png;base64,abc", mock_llm)

        msg = str(exc_info.value)
        assert "ConnectionError" in msg
        assert "Connection refused" in msg
        # Should not contain status_code/llm_provider/model
        assert "status_code" not in msg
        assert "llm_provider" not in msg

    def test_no_base64_in_error(self) -> None:
        """Error messages must not contain the full base64 image payload.

        Some LiteLLM exceptions echo the request body (including base64 images)
        in their message.  The truncation guard ensures the bulk of such a
        payload is stripped from the re-raised ValueError.
        """
        mock_llm = MagicMock()
        # Build a long base64-like payload that exceeds the 512-char truncation
        fake_b64_payload = "iVBORw0KGgo" * 100  # ~1100 chars
        fake_b64 = f"data:image/png;base64,{fake_b64_payload}"

        mock_llm.invoke.side_effect = RuntimeError(
            f"Request failed for payload: {fake_b64}"
        )

        with pytest.raises(ValueError) as exc_info:
            _summarize_image(fake_b64, mock_llm)

        msg = str(exc_info.value)
        # The full payload must not appear (truncation should have kicked in)
        assert fake_b64_payload not in msg
        assert "truncated" in msg

    def test_long_error_message_truncated(self) -> None:
        """Exception messages longer than 512 chars are truncated."""
        mock_llm = MagicMock()
        long_msg = "x" * 1000
        mock_llm.invoke.side_effect = RuntimeError(long_msg)

        with pytest.raises(ValueError) as exc_info:
            _summarize_image("data:image/png;base64,abc", mock_llm)

        msg = str(exc_info.value)
        assert "truncated" in msg
        # The full 1000-char string should not appear
        assert long_msg not in msg
