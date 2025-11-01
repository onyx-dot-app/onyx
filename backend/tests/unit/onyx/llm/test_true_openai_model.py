from onyx.llm.utils import get_model_map
from onyx.llm.utils import is_true_openai_model


class TestIsTrueOpenAIModel:
    """Tests for the is_true_openai_model function using real LiteLLM model registry."""

    def test_real_openai_gpt4(self):
        """Test that real OpenAI GPT-4 model is correctly identified."""
        assert is_true_openai_model("openai", "gpt-4") is True

    def test_real_openai_gpt4_turbo(self):
        """Test that real OpenAI GPT-4-turbo model is correctly identified."""
        assert is_true_openai_model("openai", "gpt-4-turbo") is True

    def test_real_openai_gpt35_turbo(self):
        """Test that real OpenAI GPT-3.5-turbo model is correctly identified."""
        assert is_true_openai_model("openai", "gpt-3.5-turbo") is True

    def test_real_openai_gpt4o(self):
        """Test that real OpenAI GPT-4o model is correctly identified."""
        assert is_true_openai_model("openai", "gpt-4o") is True

    def test_real_openai_gpt4o_mini(self):
        """Test that real OpenAI GPT-4o-mini model is correctly identified."""
        assert is_true_openai_model("openai", "gpt-4o-mini") is True

    def test_real_openai_o1_preview(self):
        """Test that real OpenAI o1-preview reasoning model is correctly identified."""
        assert is_true_openai_model("openai", "o1-preview") is True

    def test_real_openai_o1_mini(self):
        """Test that real OpenAI o1-mini reasoning model is correctly identified."""
        assert is_true_openai_model("openai", "o1-mini") is True

    def test_openai_with_provider_prefix(self):
        """Test that OpenAI model with provider prefix is correctly identified."""
        assert is_true_openai_model("openai", "openai/gpt-4") is False

    def test_real_openai_with_date_version(self):
        """Test that OpenAI model with date version is correctly identified."""
        # Check if this specific dated version exists in the registry
        model_map = get_model_map()
        if "openai/gpt-4-0613" in model_map:
            assert is_true_openai_model("openai", "gpt-4-0613") is True

    def test_non_openai_provider_anthropic(self):
        """Test that non-OpenAI provider (Anthropic) returns False."""
        assert is_true_openai_model("anthropic", "claude-3-5-sonnet-20241022") is False

    def test_non_openai_provider_gemini(self):
        """Test that non-OpenAI provider (Gemini) returns False."""
        assert is_true_openai_model("gemini", "gemini-1.5-pro") is False

    def test_non_openai_provider_ollama(self):
        """Test that Ollama provider returns False."""
        assert is_true_openai_model("ollama", "llama3.1") is False

    def test_openai_compatible_not_in_registry(self):
        """Test that OpenAI-compatible model not in registry returns False."""
        # Custom model served via vLLM or LiteLLM proxy
        assert is_true_openai_model("openai", "custom-llama-model") is False

    def test_openai_compatible_starts_with_o_not_in_registry(self):
        """Test that model starting with 'o' but not in registry returns False."""
        # This would have returned True with the old implementation
        assert is_true_openai_model("openai", "ollama-model") is False

    def test_empty_model_name(self):
        """Test that empty model name returns False."""
        assert is_true_openai_model("openai", "") is False

    def test_empty_provider(self):
        """Test that empty provider returns False."""
        assert is_true_openai_model("", "gpt-4") is False

    def test_case_sensitivity(self):
        """Test that model names are case-sensitive."""
        # Model names should be case-sensitive
        assert is_true_openai_model("openai", "GPT-4") is False

    def test_none_values_handled(self):
        """Test that None values are handled gracefully."""
        # Should not crash with None values
        assert is_true_openai_model("openai", None) is False  # type: ignore

    def test_litellm_proxy_custom_model(self):
        """Test that custom models via LiteLLM proxy return False."""
        # Custom model name not in OpenAI registry
        assert is_true_openai_model("openai", "my-custom-gpt") is False

    def test_vllm_hosted_model(self):
        """Test that vLLM-hosted models with OpenAI-compatible API return False."""
        # vLLM hosting a custom model with OpenAI-compatible API
        assert is_true_openai_model("openai", "TheBloke/Llama-2-7B-GPTQ") is False

    def test_azure_openai_model(self):
        """Test that Azure OpenAI models are not identified as true OpenAI."""
        # Azure uses a different provider
        assert is_true_openai_model("azure", "gpt-4") is False

    def test_openrouter_openai_model(self):
        """Test that OpenRouter proxied OpenAI models return False."""
        # OpenRouter is a proxy service, not true OpenAI
        assert is_true_openai_model("openrouter", "openai/gpt-4") is False

    def test_together_ai_model(self):
        """Test that Together AI models return False."""
        assert is_true_openai_model("together_ai", "mistralai/Mixtral-8x7B") is False

    def test_model_with_custom_suffix(self):
        """Test that models with custom suffixes not in registry return False."""
        # Custom deployment with suffix
        assert is_true_openai_model("openai", "gpt-4-my-deployment") is False

    def test_real_openai_text_embedding_models(self):
        """Test that real OpenAI text-embedding models are correctly identified."""
        # Check if embedding models are in the registry
        model_map = get_model_map()
        if "openai/text-embedding-ada-002" in model_map:
            assert is_true_openai_model("openai", "text-embedding-ada-002") is True
        if "openai/text-embedding-3-small" in model_map:
            assert is_true_openai_model("openai", "text-embedding-3-small") is True

    def test_deprecated_openai_models(self):
        """Test that deprecated but real OpenAI models are still identified correctly."""
        # Check for older models that might still be in registry
        model_map = get_model_map()
        if "openai/gpt-3.5-turbo-instruct" in model_map:
            assert is_true_openai_model("openai", "gpt-3.5-turbo-instruct") is True
