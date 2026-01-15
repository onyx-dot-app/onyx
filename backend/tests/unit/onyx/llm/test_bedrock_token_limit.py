"""Tests for get_bedrock_token_limit function."""

from unittest.mock import patch

from onyx.llm.utils import get_bedrock_token_limit


class TestGetBedrockTokenLimit:
    """Tests for Bedrock token limit lookup."""

    def test_parse_from_model_id_suffix_200k(self) -> None:
        """Test parsing :200k suffix."""
        result = get_bedrock_token_limit("anthropic.claude-3-5-sonnet:200k")
        assert result == 200000

    def test_parse_from_model_id_suffix_128k(self) -> None:
        """Test parsing :128k suffix."""
        result = get_bedrock_token_limit("meta.llama3-70b:128k")
        assert result == 128000

    def test_parse_from_model_id_suffix_4k(self) -> None:
        """Test parsing :4k suffix."""
        result = get_bedrock_token_limit("some-model:4k")
        assert result == 4000

    def test_parse_from_model_id_suffix_1000k(self) -> None:
        """Test parsing :1000k suffix (1M context)."""
        result = get_bedrock_token_limit("amazon.nova-pro:1000k")
        assert result == 1000000

    def test_litellm_lookup_with_bedrock_prefix(self) -> None:
        """Test LiteLLM lookup works with bedrock/ prefix."""
        mock_model_map = {
            "bedrock/anthropic.claude-3-5-sonnet": {"max_input_tokens": 200000}
        }
        with patch("onyx.llm.utils.get_model_map", return_value=mock_model_map):
            result = get_bedrock_token_limit("anthropic.claude-3-5-sonnet")
            assert result == 200000

    def test_litellm_lookup_without_prefix(self) -> None:
        """Test LiteLLM lookup works without bedrock/ prefix."""
        mock_model_map = {"anthropic.claude-3-sonnet": {"max_input_tokens": 200000}}
        with patch("onyx.llm.utils.get_model_map", return_value=mock_model_map):
            result = get_bedrock_token_limit("anthropic.claude-3-sonnet")
            assert result == 200000

    def test_litellm_max_tokens_fallback(self) -> None:
        """Test fallback to max_tokens when max_input_tokens not present."""
        mock_model_map = {"bedrock/some-model": {"max_tokens": 32000}}
        with patch("onyx.llm.utils.get_model_map", return_value=mock_model_map):
            result = get_bedrock_token_limit("some-model")
            assert result == 32000

    def test_hardcoded_mapping_claude_3_5(self) -> None:
        """Test hardcoded mapping for Claude 3.5 models."""
        # Mock empty LiteLLM to force mapping lookup
        with patch("onyx.llm.utils.get_model_map", return_value={}):
            result = get_bedrock_token_limit(
                "anthropic.claude-3-5-sonnet-20241022-v2:0"
            )
            assert result == 200000

    def test_hardcoded_mapping_llama3_3(self) -> None:
        """Test hardcoded mapping for Llama 3.3 models (128K context)."""
        with patch("onyx.llm.utils.get_model_map", return_value={}):
            result = get_bedrock_token_limit("meta.llama3-3-70b-instruct-v1:0")
            assert result == 128000

    def test_hardcoded_mapping_llama3_70b(self) -> None:
        """Test hardcoded mapping for Llama 3 70B (8K context)."""
        with patch("onyx.llm.utils.get_model_map", return_value={}):
            result = get_bedrock_token_limit("meta.llama3-70b-instruct-v1:0")
            assert result == 8000

    def test_hardcoded_mapping_nova_pro(self) -> None:
        """Test hardcoded mapping for Nova Pro."""
        with patch("onyx.llm.utils.get_model_map", return_value={}):
            result = get_bedrock_token_limit("amazon.nova-pro-v1:0")
            assert result == 300000

    def test_hardcoded_mapping_mistral_large(self) -> None:
        """Test hardcoded mapping for Mistral Large."""
        with patch("onyx.llm.utils.get_model_map", return_value={}):
            result = get_bedrock_token_limit("mistral.mistral-large-2407-v1:0")
            assert result == 128000

    def test_default_fallback_unknown_model(self) -> None:
        """Test default fallback for unknown models."""
        with patch("onyx.llm.utils.get_model_map", return_value={}):
            result = get_bedrock_token_limit("unknown.model-v1:0")
            # Should fall back to GEN_AI_MODEL_FALLBACK_MAX_TOKENS (32000)
            assert result == 32000

    def test_cross_region_model_id(self) -> None:
        """Test cross-region model ID (us.anthropic.claude-...)."""
        with patch("onyx.llm.utils.get_model_map", return_value={}):
            result = get_bedrock_token_limit(
                "us.anthropic.claude-3-5-sonnet-20241022-v2:0"
            )
            assert result == 200000

    def test_case_insensitive_matching(self) -> None:
        """Test that matching is case-insensitive."""
        with patch("onyx.llm.utils.get_model_map", return_value={}):
            result = get_bedrock_token_limit("ANTHROPIC.CLAUDE-3-5-SONNET")
            assert result == 200000

    def test_suffix_takes_priority_over_litellm(self) -> None:
        """Test that :NNNk suffix takes priority over LiteLLM."""
        mock_model_map = {"bedrock/model": {"max_input_tokens": 50000}}
        with patch("onyx.llm.utils.get_model_map", return_value=mock_model_map):
            # The :100k suffix should be used, not the LiteLLM value
            result = get_bedrock_token_limit("model:100k")
            assert result == 100000

    def test_litellm_exception_falls_through(self) -> None:
        """Test that LiteLLM exceptions fall through to mapping."""
        with patch(
            "onyx.llm.utils.get_model_map", side_effect=Exception("LiteLLM error")
        ):
            # Should still work via hardcoded mapping
            result = get_bedrock_token_limit("anthropic.claude-3-5-sonnet")
            assert result == 200000
