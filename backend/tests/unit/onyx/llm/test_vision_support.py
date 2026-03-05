from unittest.mock import patch

import litellm

from onyx.llm.utils import _infer_vision_support
from onyx.llm.utils import get_model_map
from onyx.llm.utils import litellm_thinks_model_supports_image_input


class TestInferVisionSupport:
    """Tests for the pattern-based vision support fallback."""

    def test_claude_3_models(self) -> None:
        assert _infer_vision_support("claude-3-5-haiku") is True
        assert _infer_vision_support("claude-3-5-haiku@20241022") is True
        assert _infer_vision_support("claude-3-5-sonnet-v2@20241022") is True
        assert _infer_vision_support("claude-3-opus@20240229") is True
        assert _infer_vision_support("claude-3-7-sonnet@20250219") is True

    def test_claude_named_models(self) -> None:
        assert _infer_vision_support("claude-sonnet-4-6") is True
        assert _infer_vision_support("claude-opus-4-5") is True
        assert _infer_vision_support("claude-haiku-4-5@20251001") is True
        assert _infer_vision_support("claude-sonnet-4-6@default") is True

    def test_openai_models(self) -> None:
        assert _infer_vision_support("gpt-4o") is True
        assert _infer_vision_support("gpt-4o-mini") is True
        assert _infer_vision_support("gpt-4-turbo") is True
        assert _infer_vision_support("gpt-4.1") is True
        assert _infer_vision_support("gpt-5") is True
        assert _infer_vision_support("gpt-5-mini") is True

    def test_gemini_models(self) -> None:
        assert _infer_vision_support("gemini-2.5-flash") is True
        assert _infer_vision_support("gemini-2.5-pro") is True
        assert _infer_vision_support("gemini-3-pro-preview") is True

    def test_non_vision_models(self) -> None:
        assert _infer_vision_support("text-embedding-3-small") is False
        assert _infer_vision_support("mistral-large-latest") is False
        assert _infer_vision_support("deepseek-v3") is False
        assert _infer_vision_support("llama-3.1-70b") is False

    def test_case_insensitive(self) -> None:
        assert _infer_vision_support("Claude-3-5-Haiku") is True
        assert _infer_vision_support("GPT-4O") is True
        assert _infer_vision_support("GEMINI-2.5-PRO") is True


class TestLitellmVisionSupport:
    """Tests for litellm_thinks_model_supports_image_input with fallback behavior."""

    def test_vertex_ai_claude_haiku_missing_supports_vision(self) -> None:
        """claude-3-5-haiku on vertex_ai is missing supports_vision in litellm.
        The pattern fallback should detect it as vision-capable."""
        get_model_map.cache_clear()
        try:
            assert (
                litellm_thinks_model_supports_image_input(
                    "claude-3-5-haiku", "vertex_ai"
                )
                is True
            )
            assert (
                litellm_thinks_model_supports_image_input(
                    "claude-3-5-haiku@20241022", "vertex_ai"
                )
                is True
            )
        finally:
            get_model_map.cache_clear()

    def test_vertex_ai_claude_with_supports_vision_set(self) -> None:
        """Models that already have supports_vision=True in litellm should still work."""
        get_model_map.cache_clear()
        try:
            assert (
                litellm_thinks_model_supports_image_input(
                    "claude-3-5-sonnet-v2@20241022", "vertex_ai"
                )
                is True
            )
            assert (
                litellm_thinks_model_supports_image_input(
                    "claude-sonnet-4-6", "vertex_ai"
                )
                is True
            )
        finally:
            get_model_map.cache_clear()

    def test_model_not_in_litellm_uses_pattern_fallback(self) -> None:
        """A model not in litellm at all should fall back to pattern matching."""
        mock_model_cost: dict[str, dict] = {}
        with patch.object(litellm, "model_cost", mock_model_cost):
            get_model_map.cache_clear()
            try:
                # Known vision pattern → True
                assert (
                    litellm_thinks_model_supports_image_input(
                        "claude-3-future-model", "vertex_ai"
                    )
                    is True
                )
                # Unknown model → False
                assert (
                    litellm_thinks_model_supports_image_input(
                        "some-unknown-model", "some_provider"
                    )
                    is False
                )
            finally:
                get_model_map.cache_clear()

    def test_explicit_false_is_respected(self) -> None:
        """If litellm explicitly sets supports_vision=False, respect it."""
        mock_model_cost = {
            "test_provider/no-vision-model": {
                "supports_vision": False,
                "max_tokens": 4096,
            }
        }
        with patch.object(litellm, "model_cost", mock_model_cost):
            get_model_map.cache_clear()
            try:
                assert (
                    litellm_thinks_model_supports_image_input(
                        "no-vision-model", "test_provider"
                    )
                    is False
                )
            finally:
                get_model_map.cache_clear()

    def test_supports_vision_none_uses_fallback(self) -> None:
        """If supports_vision is explicitly None, fall back to pattern matching."""
        mock_model_cost = {
            "vertex_ai/claude-3-new-model": {
                "supports_vision": None,
                "max_tokens": 4096,
            }
        }
        with patch.object(litellm, "model_cost", mock_model_cost):
            get_model_map.cache_clear()
            try:
                assert (
                    litellm_thinks_model_supports_image_input(
                        "claude-3-new-model", "vertex_ai"
                    )
                    is True
                )
            finally:
                get_model_map.cache_clear()

    def test_supports_vision_missing_uses_fallback(self) -> None:
        """If supports_vision key is missing entirely, fall back to pattern matching."""
        mock_model_cost = {
            "vertex_ai/claude-3-5-haiku": {
                "max_tokens": 4096,
                # no supports_vision key
            }
        }
        with patch.object(litellm, "model_cost", mock_model_cost):
            get_model_map.cache_clear()
            try:
                assert (
                    litellm_thinks_model_supports_image_input(
                        "claude-3-5-haiku", "vertex_ai"
                    )
                    is True
                )
            finally:
                get_model_map.cache_clear()
