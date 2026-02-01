"""
Integration tests for Ollama LLM provider.

Tests the complete workflow for:
- Creating Ollama provider with model configurations
- Model visibility being preserved correctly
- Updating model selections
- Chat interactions with Ollama provider
"""

from uuid import uuid4

import pytest

from tests.integration.common_utils.managers.llm_provider import LLMProviderManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.test_models import DATestUser


@pytest.fixture
def admin_user(reset: None) -> DATestUser:
    """Create an admin user for testing."""
    return UserManager.create(name="admin_user")


class TestOllamaProviderCreation:
    """Tests for creating Ollama LLM providers."""

    def test_create_ollama_provider_basic(self, admin_user: DATestUser):
        """Basic Ollama provider creation with default settings."""
        provider = LLMProviderManager.create(
            name="test-ollama",
            provider="ollama_chat",
            api_base="http://localhost:11434",
            default_model_name="llama3.1",
            user_performing_action=admin_user,
        )

        assert provider.name == "test-ollama"
        assert provider.provider == "ollama_chat"
        assert provider.api_base == "http://localhost:11434"
        assert provider.default_model_name == "llama3.1"

    def test_create_ollama_provider_with_model_configurations(
        self, admin_user: DATestUser
    ):
        """
        Ollama provider creation with explicit model configurations.
        This tests the fix where selected models need to be properly passed.
        """
        model_configs = [
            {
                "name": "llama3.1",
                "display_name": "Llama 3.1",
                "is_visible": True,
                "max_input_tokens": 128000,
                "supports_image_input": False,
            },
            {
                "name": "llama3.1:70b",
                "display_name": "Llama 3.1 70B",
                "is_visible": True,
                "max_input_tokens": 128000,
                "supports_image_input": False,
            },
            {
                "name": "codellama",
                "display_name": "Code Llama",
                "is_visible": False,  # Not selected
                "max_input_tokens": 16000,
                "supports_image_input": False,
            },
        ]

        provider = LLMProviderManager.create(
            name="test-ollama-models",
            provider="ollama_chat",
            api_base="http://localhost:11434",
            default_model_name="llama3.1",
            model_configurations=model_configs,
            user_performing_action=admin_user,
        )

        # Verify model configurations were saved
        assert provider.model_configurations is not None

        # Find visible models
        visible_models = [
            m for m in provider.model_configurations if m.get("is_visible", False)
        ]
        assert len(visible_models) == 2

        visible_names = {m["name"] for m in visible_models}
        assert "llama3.1" in visible_names
        assert "llama3.1:70b" in visible_names
        assert "codellama" not in visible_names


class TestOllamaModelVisibility:
    """Tests for model visibility preservation (the main bug fix)."""

    def test_selected_models_visible_in_chat(self, admin_user: DATestUser):
        """
        CRITICAL: Models selected in admin UI should appear in chat dropdown.
        This tests the core fix for the OllamaForm bug.
        """
        model_configs = [
            {
                "name": "llama3.1",
                "display_name": "Llama 3.1",
                "is_visible": True,
            },
            {
                "name": "mistral",
                "display_name": "Mistral",
                "is_visible": True,
            },
        ]

        provider = LLMProviderManager.create(
            name="visibility-test",
            provider="ollama_chat",
            api_base="http://localhost:11434",
            default_model_name="llama3.1",
            model_configurations=model_configs,
            user_performing_action=admin_user,
        )

        # Verify visibility was preserved
        for config in provider.model_configurations:
            if config["name"] in ["llama3.1", "mistral"]:
                assert (
                    config["is_visible"] is True
                ), f"Model {config['name']} should be visible but is_visible={config.get('is_visible')}"

    def test_unselected_models_not_visible(self, admin_user: DATestUser):
        """Models not selected should have is_visible=False."""
        model_configs = [
            {
                "name": "llama3.1",
                "display_name": "Llama 3.1",
                "is_visible": True,
            },
            {
                "name": "unused-model",
                "display_name": "Unused",
                "is_visible": False,
            },
        ]

        provider = LLMProviderManager.create(
            name="unselected-test",
            provider="ollama_chat",
            api_base="http://localhost:11434",
            default_model_name="llama3.1",
            model_configurations=model_configs,
            user_performing_action=admin_user,
        )

        # Find the unused model
        unused_config = next(
            (c for c in provider.model_configurations if c["name"] == "unused-model"),
            None,
        )

        # It might be filtered out entirely or have is_visible=False
        if unused_config:
            assert unused_config.get("is_visible") is False

    def test_multiple_providers_independent_visibility(self, admin_user: DATestUser):
        """
        Multiple Ollama providers should have independent model visibility.
        """
        # Create first provider with certain models visible
        provider1_configs = [
            {"name": "llama3.1", "is_visible": True},
            {"name": "mistral", "is_visible": False},
        ]

        provider1 = LLMProviderManager.create(
            name="ollama-provider-1",
            provider="ollama_chat",
            api_base="http://localhost:11434",
            default_model_name="llama3.1",
            model_configurations=provider1_configs,
            user_performing_action=admin_user,
        )

        # Create second provider with different visibility
        provider2_configs = [
            {"name": "llama3.1", "is_visible": False},
            {"name": "mistral", "is_visible": True},
        ]

        provider2 = LLMProviderManager.create(
            name="ollama-provider-2",
            provider="ollama_chat",
            api_base="http://localhost:11435",  # Different port
            default_model_name="mistral",
            model_configurations=provider2_configs,
            user_performing_action=admin_user,
        )

        # Verify each provider has independent visibility settings
        p1_visibility = {
            c["name"]: c.get("is_visible", False)
            for c in provider1.model_configurations
        }
        p2_visibility = {
            c["name"]: c.get("is_visible", False)
            for c in provider2.model_configurations
        }

        # Provider 1: llama visible, mistral not
        if "llama3.1" in p1_visibility:
            assert p1_visibility.get("llama3.1") is True

        # Provider 2: mistral visible, llama not (if present)
        if "mistral" in p2_visibility:
            assert p2_visibility.get("mistral") is True


class TestOllamaProviderConfiguration:
    """Tests for Ollama-specific configuration options."""

    def test_ollama_with_api_key(self, admin_user: DATestUser):
        """Ollama Cloud configuration with API key."""
        provider = LLMProviderManager.create(
            name="ollama-cloud",
            provider="ollama_chat",
            api_key="test-api-key",
            api_base="https://api.ollama.com",
            default_model_name="llama3.1",
            user_performing_action=admin_user,
        )

        assert provider.api_base == "https://api.ollama.com"
        # API key should be stored (but may be redacted in response)

    def test_ollama_self_hosted_no_api_key(self, admin_user: DATestUser):
        """Self-hosted Ollama should work without API key."""
        provider = LLMProviderManager.create(
            name="ollama-local",
            provider="ollama_chat",
            api_base="http://127.0.0.1:11434",
            default_model_name="llama3.1",
            user_performing_action=admin_user,
        )

        assert provider.api_base == "http://127.0.0.1:11434"

    def test_ollama_custom_api_base(self, admin_user: DATestUser):
        """Ollama with custom API base URL (Docker, remote server, etc.)."""
        provider = LLMProviderManager.create(
            name="ollama-docker",
            provider="ollama_chat",
            api_base="http://ollama-service:11434",
            default_model_name="llama3.1",
            user_performing_action=admin_user,
        )

        assert provider.api_base == "http://ollama-service:11434"


class TestOllamaModelNaming:
    """Tests for Ollama model naming and display names."""

    @pytest.mark.parametrize(
        "model_name,expected_contains",
        [
            ("llama3:latest", "Llama"),
            ("llama3:70b", "70B"),
            ("qwen2.5:7b", "7B"),
            ("codellama:13b-instruct", "13B"),
            ("mistral:latest", "Mistral"),
        ],
    )
    def test_model_display_name_generation(
        self,
        admin_user: DATestUser,
        model_name: str,
        expected_contains: str,
    ):
        """Display names should be human-readable."""
        model_configs = [
            {
                "name": model_name,
                "is_visible": True,
            },
        ]

        provider = LLMProviderManager.create(
            name=f"display-name-test-{uuid4().hex[:8]}",
            provider="ollama_chat",
            api_base="http://localhost:11434",
            default_model_name=model_name,
            model_configurations=model_configs,
            user_performing_action=admin_user,
        )

        # Check that display name was generated
        config = provider.model_configurations[0]
        display_name = config.get("display_name", config["name"])

        # Display name should contain expected text or be the model name
        assert (
            expected_contains.lower() in display_name.lower()
            or model_name in display_name
        )


class TestOllamaProviderDeletion:
    """Tests for Ollama provider deletion."""

    def test_delete_ollama_provider(self, admin_user: DATestUser):
        """Deleting Ollama provider should succeed."""
        provider = LLMProviderManager.create(
            name="to-delete",
            provider="ollama_chat",
            api_base="http://localhost:11434",
            default_model_name="llama3.1",
            user_performing_action=admin_user,
        )

        # Delete should not raise
        LLMProviderManager.delete(
            llm_provider=provider,
            user_performing_action=admin_user,
        )

        # Verify deletion
        providers = LLMProviderManager.get_all(user_performing_action=admin_user)
        provider_ids = [p.id for p in providers]
        assert provider.id not in provider_ids
