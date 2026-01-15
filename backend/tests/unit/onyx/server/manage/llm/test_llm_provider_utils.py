"""Tests for LLM provider utilities."""

from onyx.server.manage.llm.utils import generate_bedrock_display_name
from onyx.server.manage.llm.utils import generate_ollama_display_name
from onyx.server.manage.llm.utils import infer_vision_support
from onyx.server.manage.llm.utils import is_reasoning_model
from onyx.server.manage.llm.utils import is_valid_bedrock_model
from onyx.server.manage.llm.utils import strip_openrouter_vendor_prefix


class TestGenerateBedrockDisplayName:
    """Tests for Bedrock display name generation."""

    def test_claude_model_basic(self) -> None:
        """Test basic Claude model name."""
        result = generate_bedrock_display_name(
            "anthropic.claude-3-5-sonnet-20241022-v2:0"
        )
        assert "Claude" in result
        assert "3.5" in result
        assert "Sonnet" in result

    def test_claude_model_with_region_prefix(self) -> None:
        """Test Claude model with region prefix (cross-region inference)."""
        result = generate_bedrock_display_name(
            "us.anthropic.claude-3-5-sonnet-20241022-v2:0"
        )
        assert "Claude" in result
        assert "(us)" in result

    def test_llama_model(self) -> None:
        """Test Llama model name."""
        result = generate_bedrock_display_name("meta.llama3-70b-instruct-v1:0")
        assert "Llama" in result
        assert "70B" in result or "70b" in result.lower()

    def test_nova_model(self) -> None:
        """Test Amazon Nova model name."""
        result = generate_bedrock_display_name("amazon.nova-pro-v1:0")
        assert "Nova" in result
        assert "Pro" in result

    def test_mistral_model(self) -> None:
        """Test Mistral model name."""
        result = generate_bedrock_display_name("mistral.mistral-large-2407-v1:0")
        assert "Mistral" in result

    def test_removes_version_suffix(self) -> None:
        """Test that version suffixes like :0 are removed."""
        result = generate_bedrock_display_name("anthropic.claude-3-opus:0")
        assert ":0" not in result

    def test_removes_date_stamps(self) -> None:
        """Test that date stamps like -20241022-v2 are removed."""
        result = generate_bedrock_display_name(
            "anthropic.claude-3-5-sonnet-20241022-v2:0"
        )
        assert "20241022" not in result


class TestGenerateOllamaDisplayName:
    """Tests for Ollama display name generation."""

    def test_llama_basic(self) -> None:
        """Test basic Llama model."""
        result = generate_ollama_display_name("llama3:latest")
        assert "Llama" in result

    def test_llama_with_size(self) -> None:
        """Test Llama with size tag."""
        result = generate_ollama_display_name("llama3:70b")
        assert "Llama" in result
        assert "70B" in result

    def test_qwen_model(self) -> None:
        """Test Qwen model."""
        result = generate_ollama_display_name("qwen2.5:7b")
        assert "Qwen" in result
        assert "7B" in result

    def test_mistral_model(self) -> None:
        """Test Mistral model."""
        result = generate_ollama_display_name("mistral:latest")
        assert "Mistral" in result

    def test_deepseek_model(self) -> None:
        """Test DeepSeek model."""
        result = generate_ollama_display_name("deepseek-r1:14b")
        assert "DeepSeek" in result
        assert "14B" in result

    def test_skips_latest_tag(self) -> None:
        """Test that 'latest' tag is not shown."""
        result = generate_ollama_display_name("llama3:latest")
        assert "latest" not in result.lower()

    def test_version_number_preserved(self) -> None:
        """Test that version numbers like 3.3 are preserved."""
        result = generate_ollama_display_name("llama3.3:70b")
        assert "3.3" in result or "3 3" in result  # Either format is acceptable


class TestStripOpenrouterVendorPrefix:
    """Tests for OpenRouter vendor prefix stripping."""

    def test_strips_matching_prefix(self) -> None:
        """Test stripping matching vendor prefix."""
        result = strip_openrouter_vendor_prefix("Microsoft: Phi 4", "microsoft/phi-4")
        assert result == "Phi 4"

    def test_strips_mistral_prefix(self) -> None:
        """Test stripping Mistral prefix."""
        result = strip_openrouter_vendor_prefix(
            "Mistral: Mixtral 8x7B Instruct", "mistralai/mixtral-8x7b"
        )
        assert result == "Mixtral 8x7B Instruct"

    def test_preserves_when_no_prefix(self) -> None:
        """Test preserving name when no prefix pattern."""
        result = strip_openrouter_vendor_prefix(
            "Claude 3.5 Sonnet", "anthropic/claude-3.5-sonnet"
        )
        assert result == "Claude 3.5 Sonnet"

    def test_preserves_when_no_slash_in_id(self) -> None:
        """Test preserving name when no slash in model ID."""
        result = strip_openrouter_vendor_prefix("Some Model", "some-model")
        assert result == "Some Model"

    def test_handles_partial_vendor_match(self) -> None:
        """Test handling partial vendor name matches."""
        # "Mistral" should match "mistralai"
        result = strip_openrouter_vendor_prefix(
            "Mistral: Some Model", "mistralai/some-model"
        )
        assert result == "Some Model"


class TestIsValidBedrockModel:
    """Tests for Bedrock model validation."""

    def test_valid_claude_model(self) -> None:
        """Test valid Claude model."""
        assert is_valid_bedrock_model("anthropic.claude-3-5-sonnet", True) is True

    def test_invalid_embedding_model(self) -> None:
        """Test that embedding models are filtered."""
        assert is_valid_bedrock_model("amazon.titan-embed-text-v1", True) is False

    def test_invalid_image_model(self) -> None:
        """Test that image generation models are filtered."""
        assert is_valid_bedrock_model("stability.stable-diffusion-xl", True) is False

    def test_invalid_non_streaming(self) -> None:
        """Test that non-streaming models are filtered."""
        assert is_valid_bedrock_model("anthropic.claude-3-sonnet", False) is False

    def test_empty_model_id(self) -> None:
        """Test that empty model ID is invalid."""
        assert is_valid_bedrock_model("", True) is False


class TestInferVisionSupport:
    """Tests for vision support inference."""

    def test_claude_3_has_vision(self) -> None:
        """Test Claude 3 models have vision."""
        assert infer_vision_support("anthropic.claude-3-5-sonnet") is True

    def test_claude_4_has_vision(self) -> None:
        """Test Claude 4 models have vision."""
        assert infer_vision_support("anthropic.claude-4-opus") is True

    def test_nova_pro_has_vision(self) -> None:
        """Test Nova Pro has vision."""
        assert infer_vision_support("amazon.nova-pro-v1") is True

    def test_mistral_no_vision(self) -> None:
        """Test Mistral doesn't have vision (not in known list)."""
        assert infer_vision_support("mistral.mistral-large") is False


class TestIsReasoningModel:
    """Tests for reasoning model detection."""

    def test_o1_is_reasoning(self) -> None:
        """Test o1 models are detected as reasoning."""
        assert is_reasoning_model("openai/o1-preview", "O1 Preview") is True

    def test_o3_is_reasoning(self) -> None:
        """Test o3 models are detected as reasoning."""
        assert is_reasoning_model("openai/o3-mini", "O3 Mini") is True

    def test_deepseek_r1_is_reasoning(self) -> None:
        """Test DeepSeek R1 is detected as reasoning."""
        assert is_reasoning_model("deepseek/deepseek-r1", "DeepSeek R1") is True

    def test_qwq_is_reasoning(self) -> None:
        """Test QwQ is detected as reasoning."""
        assert is_reasoning_model("qwen/qwq-32b", "QwQ 32B") is True

    def test_gpt_4_not_reasoning(self) -> None:
        """Test GPT-4 is not detected as reasoning."""
        assert is_reasoning_model("openai/gpt-4", "GPT-4") is False

    def test_claude_not_reasoning(self) -> None:
        """Test Claude is not detected as reasoning."""
        assert (
            is_reasoning_model("anthropic/claude-3-5-sonnet", "Claude 3.5 Sonnet")
            is False
        )
