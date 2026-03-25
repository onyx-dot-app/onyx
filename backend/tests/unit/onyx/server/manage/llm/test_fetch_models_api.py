"""Tests for LLM model fetch endpoints.

These tests verify the full request/response flow for fetching models
from dynamic providers (Ollama, OpenRouter, Litellm), including the
sync-to-DB behavior when provider_name is specified.
"""

from unittest.mock import MagicMock
from unittest.mock import patch

import httpx
import pytest

from onyx.error_handling.exceptions import OnyxError
from onyx.server.manage.llm.models import BifrostFinalModelResponse
from onyx.server.manage.llm.models import BifrostModelsRequest
from onyx.server.manage.llm.models import LitellmFinalModelResponse
from onyx.server.manage.llm.models import LitellmModelsRequest
from onyx.server.manage.llm.models import LMStudioFinalModelResponse
from onyx.server.manage.llm.models import LMStudioModelsRequest
from onyx.server.manage.llm.models import OllamaFinalModelResponse
from onyx.server.manage.llm.models import OllamaModelsRequest
from onyx.server.manage.llm.models import OpenRouterFinalModelResponse
from onyx.server.manage.llm.models import OpenRouterModelsRequest


class TestGetOllamaAvailableModels:
    """Tests for the Ollama model fetch endpoint."""

    @pytest.fixture
    def mock_ollama_tags_response(self) -> dict:
        """Mock response from Ollama /api/tags endpoint."""
        return {
            "models": [
                {"name": "llama3:latest"},
                {"name": "mistral:7b"},
                {"name": "qwen2.5:14b"},
            ]
        }

    @pytest.fixture
    def mock_ollama_show_response(self) -> dict:
        """Mock response from Ollama /api/show endpoint."""
        return {
            "details": {"family": "llama", "families": ["llama"]},
            "model_info": {
                "general.architecture": "llama",
                "llama.context_length": 8192,
            },
            "capabilities": [
                "completion"
            ],  # Required to pass supports_completion() check
        }

    def test_returns_model_list(
        self, mock_ollama_tags_response: dict, mock_ollama_show_response: dict
    ) -> None:
        """Test that endpoint returns properly formatted model list."""
        from onyx.server.manage.llm.api import get_ollama_available_models

        mock_session = MagicMock()

        with patch("onyx.server.manage.llm.api.httpx") as mock_httpx:
            # Mock GET for /api/tags
            mock_get_response = MagicMock()
            mock_get_response.json.return_value = mock_ollama_tags_response
            mock_get_response.raise_for_status = MagicMock()
            mock_httpx.get.return_value = mock_get_response

            # Mock POST for /api/show (called for each model)
            mock_post_response = MagicMock()
            mock_post_response.json.return_value = mock_ollama_show_response
            mock_post_response.raise_for_status = MagicMock()
            mock_httpx.post.return_value = mock_post_response

            request = OllamaModelsRequest(api_base="http://localhost:11434")
            results = get_ollama_available_models(request, MagicMock(), mock_session)

            assert len(results) == 3
            assert all(isinstance(r, OllamaFinalModelResponse) for r in results)
            # Check display names are generated
            assert any("Llama" in r.display_name for r in results)
            assert any("Mistral" in r.display_name for r in results)
            # Results should be alphabetically sorted by model name
            assert [r.name for r in results] == sorted(
                [r.name for r in results], key=str.lower
            )

    def test_syncs_to_db_when_provider_name_specified(
        self, mock_ollama_tags_response: dict, mock_ollama_show_response: dict
    ) -> None:
        """Test that models are synced to DB when provider_name is given."""
        from onyx.server.manage.llm.api import get_ollama_available_models

        mock_session = MagicMock()
        mock_provider = MagicMock()
        mock_provider.id = 1
        mock_provider.model_configurations = []

        with (
            patch("onyx.server.manage.llm.api.httpx") as mock_httpx,
            patch(
                "onyx.db.llm.fetch_existing_llm_provider", return_value=mock_provider
            ),
        ):
            mock_get_response = MagicMock()
            mock_get_response.json.return_value = mock_ollama_tags_response
            mock_get_response.raise_for_status = MagicMock()
            mock_httpx.get.return_value = mock_get_response

            mock_post_response = MagicMock()
            mock_post_response.json.return_value = mock_ollama_show_response
            mock_post_response.raise_for_status = MagicMock()
            mock_httpx.post.return_value = mock_post_response

            request = OllamaModelsRequest(
                api_base="http://localhost:11434",
                provider_name="my-ollama",
            )
            get_ollama_available_models(request, MagicMock(), mock_session)

            # Verify DB operations were called
            assert mock_session.execute.call_count == 6
            mock_session.commit.assert_called_once()

    def test_no_sync_when_provider_name_not_specified(
        self, mock_ollama_tags_response: dict, mock_ollama_show_response: dict
    ) -> None:
        """Test that models are NOT synced when provider_name is None."""
        from onyx.server.manage.llm.api import get_ollama_available_models

        mock_session = MagicMock()

        with patch("onyx.server.manage.llm.api.httpx") as mock_httpx:
            mock_get_response = MagicMock()
            mock_get_response.json.return_value = mock_ollama_tags_response
            mock_get_response.raise_for_status = MagicMock()
            mock_httpx.get.return_value = mock_get_response

            mock_post_response = MagicMock()
            mock_post_response.json.return_value = mock_ollama_show_response
            mock_post_response.raise_for_status = MagicMock()
            mock_httpx.post.return_value = mock_post_response

            request = OllamaModelsRequest(api_base="http://localhost:11434")
            get_ollama_available_models(request, MagicMock(), mock_session)

            # No DB operations should happen
            mock_session.execute.assert_not_called()
            mock_session.commit.assert_not_called()


class TestGetOpenRouterAvailableModels:
    """Tests for the OpenRouter model fetch endpoint."""

    @pytest.fixture
    def mock_openrouter_response(self) -> dict:
        """Mock response from OpenRouter API."""
        return {
            "data": [
                {
                    "id": "anthropic/claude-3.5-sonnet",
                    "name": "Claude 3.5 Sonnet",
                    "context_length": 200000,
                    "architecture": {"input_modalities": ["text", "image"]},
                },
                {
                    "id": "openai/gpt-4o",
                    "name": "GPT-4o",
                    "context_length": 128000,
                    "architecture": {"input_modalities": ["text", "image"]},
                },
                {
                    "id": "meta-llama/llama-3.1-70b",
                    "name": "Llama 3.1 70B",
                    "context_length": 131072,
                    "architecture": {"input_modalities": ["text"]},
                },
            ]
        }

    def test_returns_model_list(self, mock_openrouter_response: dict) -> None:
        """Test that endpoint returns properly formatted model list."""
        from onyx.server.manage.llm.api import get_openrouter_available_models

        mock_session = MagicMock()

        with patch("onyx.server.manage.llm.api.httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.json.return_value = mock_openrouter_response
            mock_response.raise_for_status = MagicMock()
            mock_get.return_value = mock_response

            request = OpenRouterModelsRequest(
                api_base="https://openrouter.ai/api/v1",
                api_key="test-key",
            )
            results = get_openrouter_available_models(
                request, MagicMock(), mock_session
            )

            assert len(results) == 3
            assert all(isinstance(r, OpenRouterFinalModelResponse) for r in results)
            # Check that models have correct context lengths
            claude = next(r for r in results if "claude" in r.name.lower())
            assert claude.max_input_tokens == 200000

    def test_infers_vision_support(self, mock_openrouter_response: dict) -> None:
        """Test that vision support is correctly inferred from modality."""
        from onyx.server.manage.llm.api import get_openrouter_available_models

        mock_session = MagicMock()

        with patch("onyx.server.manage.llm.api.httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.json.return_value = mock_openrouter_response
            mock_response.raise_for_status = MagicMock()
            mock_get.return_value = mock_response

            request = OpenRouterModelsRequest(
                api_base="https://openrouter.ai/api/v1",
                api_key="test-key",
            )
            results = get_openrouter_available_models(
                request, MagicMock(), mock_session
            )

            # Models with "image" in modality should have vision support
            claude = next(r for r in results if "claude" in r.name.lower())
            llama = next(r for r in results if "llama" in r.name.lower())

            assert claude.supports_image_input is True
            assert llama.supports_image_input is False

    def test_syncs_to_db_when_provider_name_specified(
        self, mock_openrouter_response: dict
    ) -> None:
        """Test that models are synced to DB when provider_name is given."""
        from onyx.server.manage.llm.api import get_openrouter_available_models

        mock_session = MagicMock()
        mock_provider = MagicMock()
        mock_provider.id = 1
        mock_provider.model_configurations = []

        with (
            patch("onyx.server.manage.llm.api.httpx.get") as mock_get,
            patch(
                "onyx.db.llm.fetch_existing_llm_provider", return_value=mock_provider
            ),
        ):
            mock_response = MagicMock()
            mock_response.json.return_value = mock_openrouter_response
            mock_response.raise_for_status = MagicMock()
            mock_get.return_value = mock_response

            request = OpenRouterModelsRequest(
                api_base="https://openrouter.ai/api/v1",
                api_key="test-key",
                provider_name="my-openrouter",
            )
            get_openrouter_available_models(request, MagicMock(), mock_session)

            # Verify DB operations were called
            assert mock_session.execute.call_count == 8
            mock_session.commit.assert_called_once()

    def test_preserves_existing_models_on_sync(
        self, mock_openrouter_response: dict
    ) -> None:
        """Test that existing models are not overwritten during sync."""
        from onyx.server.manage.llm.api import get_openrouter_available_models

        mock_session = MagicMock()

        # Provider already has claude model
        existing_model = MagicMock()
        existing_model.name = "anthropic/claude-3.5-sonnet"

        mock_provider = MagicMock()
        mock_provider.id = 1
        mock_provider.model_configurations = [existing_model]

        with (
            patch("onyx.server.manage.llm.api.httpx.get") as mock_get,
            patch(
                "onyx.db.llm.fetch_existing_llm_provider", return_value=mock_provider
            ),
        ):
            mock_response = MagicMock()
            mock_response.json.return_value = mock_openrouter_response
            mock_response.raise_for_status = MagicMock()
            mock_get.return_value = mock_response

            request = OpenRouterModelsRequest(
                api_base="https://openrouter.ai/api/v1",
                api_key="test-key",
                provider_name="my-openrouter",
            )
            get_openrouter_available_models(request, MagicMock(), mock_session)

            # Only 2 new models should be inserted (claude already exists)
            assert mock_session.execute.call_count == 5

    def test_no_sync_when_provider_name_not_specified(
        self, mock_openrouter_response: dict
    ) -> None:
        """Test that models are NOT synced when provider_name is None."""
        from onyx.server.manage.llm.api import get_openrouter_available_models

        mock_session = MagicMock()

        with patch("onyx.server.manage.llm.api.httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.json.return_value = mock_openrouter_response
            mock_response.raise_for_status = MagicMock()
            mock_get.return_value = mock_response

            request = OpenRouterModelsRequest(
                api_base="https://openrouter.ai/api/v1",
                api_key="test-key",
            )
            get_openrouter_available_models(request, MagicMock(), mock_session)

            # No DB operations should happen
            mock_session.execute.assert_not_called()
            mock_session.commit.assert_not_called()


class TestGetLMStudioAvailableModels:
    """Tests for the LM Studio model fetch endpoint."""

    @pytest.fixture
    def mock_lm_studio_response(self) -> dict:
        """Mock response from LM Studio /api/v1/models endpoint."""
        return {
            "models": [
                {
                    "key": "lmstudio-community/Meta-Llama-3-8B",
                    "type": "llm",
                    "display_name": "Meta Llama 3 8B",
                    "max_context_length": 8192,
                    "capabilities": {"vision": False},
                },
                {
                    "key": "lmstudio-community/Qwen2.5-VL-7B",
                    "type": "llm",
                    "display_name": "Qwen 2.5 VL 7B",
                    "max_context_length": 32768,
                    "capabilities": {"vision": True},
                },
                {
                    "key": "text-embedding-nomic-embed-text-v1.5",
                    "type": "embedding",
                    "display_name": "Nomic Embed Text v1.5",
                    "max_context_length": 2048,
                    "capabilities": {},
                },
                {
                    "key": "lmstudio-community/DeepSeek-R1-8B",
                    "type": "llm",
                    "display_name": "DeepSeek R1 8B",
                    "max_context_length": 65536,
                    "capabilities": {"vision": False},
                },
            ]
        }

    def test_returns_model_list(self, mock_lm_studio_response: dict) -> None:
        """Test that endpoint returns properly formatted LLM-only model list."""
        from onyx.server.manage.llm.api import get_lm_studio_available_models

        mock_session = MagicMock()

        with patch("onyx.server.manage.llm.api.httpx") as mock_httpx:
            mock_response = MagicMock()
            mock_response.json.return_value = mock_lm_studio_response
            mock_response.raise_for_status = MagicMock()
            mock_httpx.get.return_value = mock_response

            request = LMStudioModelsRequest(api_base="http://localhost:1234")
            results = get_lm_studio_available_models(request, MagicMock(), mock_session)

            # Only LLM-type models should be returned (embedding filtered out)
            assert len(results) == 3
            assert all(isinstance(r, LMStudioFinalModelResponse) for r in results)
            names = [r.name for r in results]
            assert "text-embedding-nomic-embed-text-v1.5" not in names
            # Results should be alphabetically sorted by model name
            assert names == sorted(names, key=str.lower)

    def test_infers_vision_support(self, mock_lm_studio_response: dict) -> None:
        """Test that vision support is correctly read from capabilities."""
        from onyx.server.manage.llm.api import get_lm_studio_available_models

        mock_session = MagicMock()

        with patch("onyx.server.manage.llm.api.httpx") as mock_httpx:
            mock_response = MagicMock()
            mock_response.json.return_value = mock_lm_studio_response
            mock_response.raise_for_status = MagicMock()
            mock_httpx.get.return_value = mock_response

            request = LMStudioModelsRequest(api_base="http://localhost:1234")
            results = get_lm_studio_available_models(request, MagicMock(), mock_session)

            qwen = next(r for r in results if "Qwen" in r.display_name)
            llama = next(r for r in results if "Llama" in r.display_name)

            assert qwen.supports_image_input is True
            assert llama.supports_image_input is False

    def test_infers_reasoning_from_model_name(self) -> None:
        """Test that reasoning is inferred from model name when not in capabilities."""
        from onyx.server.manage.llm.api import get_lm_studio_available_models

        mock_session = MagicMock()
        response = {
            "models": [
                {
                    "key": "lmstudio-community/DeepSeek-R1-8B",
                    "type": "llm",
                    "display_name": "DeepSeek R1 8B",
                    "max_context_length": 65536,
                    "capabilities": {},
                },
                {
                    "key": "lmstudio-community/Meta-Llama-3-8B",
                    "type": "llm",
                    "display_name": "Meta Llama 3 8B",
                    "max_context_length": 8192,
                    "capabilities": {},
                },
            ]
        }

        with patch("onyx.server.manage.llm.api.httpx") as mock_httpx:
            mock_response = MagicMock()
            mock_response.json.return_value = response
            mock_response.raise_for_status = MagicMock()
            mock_httpx.get.return_value = mock_response

            request = LMStudioModelsRequest(api_base="http://localhost:1234")
            results = get_lm_studio_available_models(request, MagicMock(), mock_session)

            deepseek = next(r for r in results if "DeepSeek" in r.display_name)
            llama = next(r for r in results if "Llama" in r.display_name)

            assert deepseek.supports_reasoning is True
            assert llama.supports_reasoning is False

    def test_uses_display_name_from_api(self, mock_lm_studio_response: dict) -> None:
        """Test that display_name from the API is used directly."""
        from onyx.server.manage.llm.api import get_lm_studio_available_models

        mock_session = MagicMock()

        with patch("onyx.server.manage.llm.api.httpx") as mock_httpx:
            mock_response = MagicMock()
            mock_response.json.return_value = mock_lm_studio_response
            mock_response.raise_for_status = MagicMock()
            mock_httpx.get.return_value = mock_response

            request = LMStudioModelsRequest(api_base="http://localhost:1234")
            results = get_lm_studio_available_models(request, MagicMock(), mock_session)

            llama = next(r for r in results if "Llama" in r.name)
            assert llama.display_name == "Meta Llama 3 8B"
            assert llama.max_input_tokens == 8192

    def test_strips_trailing_v1_from_api_base(self) -> None:
        """Test that /v1 suffix is stripped before building the native API URL."""
        from onyx.server.manage.llm.api import get_lm_studio_available_models

        mock_session = MagicMock()
        response = {
            "models": [
                {
                    "key": "test-model",
                    "type": "llm",
                    "display_name": "Test",
                    "max_context_length": 4096,
                    "capabilities": {},
                },
            ]
        }

        with patch("onyx.server.manage.llm.api.httpx") as mock_httpx:
            mock_response = MagicMock()
            mock_response.json.return_value = response
            mock_response.raise_for_status = MagicMock()
            mock_httpx.get.return_value = mock_response

            request = LMStudioModelsRequest(api_base="http://localhost:1234/v1")
            get_lm_studio_available_models(request, MagicMock(), mock_session)

            # Should hit /api/v1/models, not /v1/api/v1/models
            mock_httpx.get.assert_called_once()
            called_url = mock_httpx.get.call_args[0][0]
            assert called_url == "http://localhost:1234/api/v1/models"

    def test_falls_back_to_stored_api_key(self) -> None:
        """Test that stored API key is used when api_key_changed is False."""
        from onyx.server.manage.llm.api import get_lm_studio_available_models

        mock_session = MagicMock()
        mock_provider = MagicMock()
        mock_provider.custom_config = {"LM_STUDIO_API_KEY": "stored-secret"}

        response = {
            "models": [
                {
                    "key": "test-model",
                    "type": "llm",
                    "display_name": "Test",
                    "max_context_length": 4096,
                    "capabilities": {},
                },
            ]
        }

        with (
            patch("onyx.server.manage.llm.api.httpx") as mock_httpx,
            patch(
                "onyx.server.manage.llm.api.fetch_existing_llm_provider",
                return_value=mock_provider,
            ),
        ):
            mock_response = MagicMock()
            mock_response.json.return_value = response
            mock_response.raise_for_status = MagicMock()
            mock_httpx.get.return_value = mock_response

            request = LMStudioModelsRequest(
                api_base="http://localhost:1234",
                api_key="masked-value",
                api_key_changed=False,
                provider_name="my-lm-studio",
            )
            get_lm_studio_available_models(request, MagicMock(), mock_session)

            headers = mock_httpx.get.call_args[1]["headers"]
            assert headers["Authorization"] == "Bearer stored-secret"

    def test_uses_submitted_api_key_when_changed(self) -> None:
        """Test that submitted API key is used when api_key_changed is True."""
        from onyx.server.manage.llm.api import get_lm_studio_available_models

        mock_session = MagicMock()
        response = {
            "models": [
                {
                    "key": "test-model",
                    "type": "llm",
                    "display_name": "Test",
                    "max_context_length": 4096,
                    "capabilities": {},
                },
            ]
        }

        with patch("onyx.server.manage.llm.api.httpx") as mock_httpx:
            mock_response = MagicMock()
            mock_response.json.return_value = response
            mock_response.raise_for_status = MagicMock()
            mock_httpx.get.return_value = mock_response

            request = LMStudioModelsRequest(
                api_base="http://localhost:1234",
                api_key="new-secret",
                api_key_changed=True,
                provider_name="my-lm-studio",
            )
            get_lm_studio_available_models(request, MagicMock(), mock_session)

            headers = mock_httpx.get.call_args[1]["headers"]
            assert headers["Authorization"] == "Bearer new-secret"

    def test_raises_on_empty_models(self) -> None:
        """Test that an error is raised when no models are returned."""
        from onyx.error_handling.exceptions import OnyxError
        from onyx.server.manage.llm.api import get_lm_studio_available_models

        mock_session = MagicMock()

        with patch("onyx.server.manage.llm.api.httpx") as mock_httpx:
            mock_response = MagicMock()
            mock_response.json.return_value = {"models": []}
            mock_response.raise_for_status = MagicMock()
            mock_httpx.get.return_value = mock_response

            request = LMStudioModelsRequest(api_base="http://localhost:1234")
            with pytest.raises(OnyxError):
                get_lm_studio_available_models(request, MagicMock(), mock_session)

    def test_raises_on_only_non_llm_models(self) -> None:
        """Test that an error is raised when all models are non-LLM type."""
        from onyx.error_handling.exceptions import OnyxError
        from onyx.server.manage.llm.api import get_lm_studio_available_models

        mock_session = MagicMock()
        response = {
            "models": [
                {
                    "key": "embedding-model",
                    "type": "embedding",
                    "display_name": "Embedding",
                    "max_context_length": 2048,
                    "capabilities": {},
                },
            ]
        }

        with patch("onyx.server.manage.llm.api.httpx") as mock_httpx:
            mock_response = MagicMock()
            mock_response.json.return_value = response
            mock_response.raise_for_status = MagicMock()
            mock_httpx.get.return_value = mock_response

            request = LMStudioModelsRequest(api_base="http://localhost:1234")
            with pytest.raises(OnyxError):
                get_lm_studio_available_models(request, MagicMock(), mock_session)


class TestGetLitellmAvailableModels:
    """Tests for the Litellm proxy model fetch endpoint."""

    @pytest.fixture
    def mock_litellm_response(self) -> dict:
        """Mock response from Litellm /v1/models endpoint."""
        return {
            "data": [
                {
                    "id": "gpt-4o",
                    "object": "model",
                    "created": 1700000000,
                    "owned_by": "openai",
                },
                {
                    "id": "claude-3-5-sonnet",
                    "object": "model",
                    "created": 1700000001,
                    "owned_by": "anthropic",
                },
                {
                    "id": "gemini-pro",
                    "object": "model",
                    "created": 1700000002,
                    "owned_by": "google",
                },
            ]
        }

    def test_returns_model_list(self, mock_litellm_response: dict) -> None:
        """Test that endpoint returns properly formatted model list."""
        from onyx.server.manage.llm.api import get_litellm_available_models

        mock_session = MagicMock()

        with patch("onyx.server.manage.llm.api.httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.json.return_value = mock_litellm_response
            mock_response.raise_for_status = MagicMock()
            mock_get.return_value = mock_response

            request = LitellmModelsRequest(
                api_base="http://localhost:4000",
                api_key="test-key",
            )
            results = get_litellm_available_models(request, MagicMock(), mock_session)

            assert len(results) == 3
            assert all(isinstance(r, LitellmFinalModelResponse) for r in results)

    def test_model_fields_parsed_correctly(self, mock_litellm_response: dict) -> None:
        """Test that provider_name and model_name are correctly extracted."""
        from onyx.server.manage.llm.api import get_litellm_available_models

        mock_session = MagicMock()

        with patch("onyx.server.manage.llm.api.httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.json.return_value = mock_litellm_response
            mock_response.raise_for_status = MagicMock()
            mock_get.return_value = mock_response

            request = LitellmModelsRequest(
                api_base="http://localhost:4000",
                api_key="test-key",
            )
            results = get_litellm_available_models(request, MagicMock(), mock_session)

            gpt = next(r for r in results if r.model_name == "gpt-4o")
            assert gpt.provider_name == "openai"

            claude = next(r for r in results if r.model_name == "claude-3-5-sonnet")
            assert claude.provider_name == "anthropic"

    def test_results_sorted_by_model_name(self, mock_litellm_response: dict) -> None:
        """Test that results are alphabetically sorted by model_name."""
        from onyx.server.manage.llm.api import get_litellm_available_models

        mock_session = MagicMock()

        with patch("onyx.server.manage.llm.api.httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.json.return_value = mock_litellm_response
            mock_response.raise_for_status = MagicMock()
            mock_get.return_value = mock_response

            request = LitellmModelsRequest(
                api_base="http://localhost:4000",
                api_key="test-key",
            )
            results = get_litellm_available_models(request, MagicMock(), mock_session)

            model_names = [r.model_name for r in results]
            assert model_names == sorted(model_names, key=str.lower)

    def test_empty_data_raises_onyx_error(self) -> None:
        """Test that empty model list raises OnyxError."""
        from onyx.server.manage.llm.api import get_litellm_available_models

        mock_session = MagicMock()

        with patch("onyx.server.manage.llm.api.httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.json.return_value = {"data": []}
            mock_response.raise_for_status = MagicMock()
            mock_get.return_value = mock_response

            request = LitellmModelsRequest(
                api_base="http://localhost:4000",
                api_key="test-key",
            )
            with pytest.raises(OnyxError, match="No models found"):
                get_litellm_available_models(request, MagicMock(), mock_session)

    def test_missing_data_key_raises_onyx_error(self) -> None:
        """Test that response without 'data' key raises OnyxError."""
        from onyx.server.manage.llm.api import get_litellm_available_models

        mock_session = MagicMock()

        with patch("onyx.server.manage.llm.api.httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.json.return_value = {}
            mock_response.raise_for_status = MagicMock()
            mock_get.return_value = mock_response

            request = LitellmModelsRequest(
                api_base="http://localhost:4000",
                api_key="test-key",
            )
            with pytest.raises(OnyxError):
                get_litellm_available_models(request, MagicMock(), mock_session)

    def test_skips_unparseable_entries(self) -> None:
        """Test that malformed model entries are skipped without failing."""
        from onyx.server.manage.llm.api import get_litellm_available_models

        mock_session = MagicMock()
        response_with_bad_entry = {
            "data": [
                {
                    "id": "gpt-4o",
                    "object": "model",
                    "created": 1700000000,
                    "owned_by": "openai",
                },
                # Missing required fields
                {"bad_field": "bad_value"},
            ]
        }

        with patch("onyx.server.manage.llm.api.httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.json.return_value = response_with_bad_entry
            mock_response.raise_for_status = MagicMock()
            mock_get.return_value = mock_response

            request = LitellmModelsRequest(
                api_base="http://localhost:4000",
                api_key="test-key",
            )
            results = get_litellm_available_models(request, MagicMock(), mock_session)

            assert len(results) == 1
            assert results[0].model_name == "gpt-4o"

    def test_all_entries_unparseable_raises_onyx_error(self) -> None:
        """Test that OnyxError is raised when all entries fail to parse."""
        from onyx.server.manage.llm.api import get_litellm_available_models

        mock_session = MagicMock()
        response_all_bad = {
            "data": [
                {"bad_field": "bad_value"},
                {"another_bad": 123},
            ]
        }

        with patch("onyx.server.manage.llm.api.httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.json.return_value = response_all_bad
            mock_response.raise_for_status = MagicMock()
            mock_get.return_value = mock_response

            request = LitellmModelsRequest(
                api_base="http://localhost:4000",
                api_key="test-key",
            )
            with pytest.raises(OnyxError, match="No compatible models"):
                get_litellm_available_models(request, MagicMock(), mock_session)

    def test_api_base_trailing_slash_handled(self) -> None:
        """Test that trailing slashes in api_base are handled correctly."""
        from onyx.server.manage.llm.api import get_litellm_available_models

        mock_session = MagicMock()
        mock_litellm_response = {
            "data": [
                {
                    "id": "gpt-4o",
                    "object": "model",
                    "created": 1700000000,
                    "owned_by": "openai",
                },
            ]
        }

        with patch("onyx.server.manage.llm.api.httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.json.return_value = mock_litellm_response
            mock_response.raise_for_status = MagicMock()
            mock_get.return_value = mock_response

            request = LitellmModelsRequest(
                api_base="http://localhost:4000/",
                api_key="test-key",
            )
            get_litellm_available_models(request, MagicMock(), mock_session)

            # Should call /v1/models without double slashes
            call_args = mock_get.call_args
            assert call_args[0][0] == "http://localhost:4000/v1/models"

    def test_connection_failure_raises_onyx_error(self) -> None:
        """Test that connection failures are wrapped in OnyxError."""
        from onyx.server.manage.llm.api import get_litellm_available_models

        mock_session = MagicMock()

        with patch("onyx.server.manage.llm.api.httpx.get") as mock_get:
            mock_get.side_effect = httpx.ConnectError(
                "Connection refused", request=MagicMock()
            )

            request = LitellmModelsRequest(
                api_base="http://localhost:4000",
                api_key="test-key",
            )
            with pytest.raises(OnyxError, match="Failed to fetch LiteLLM proxy models"):
                get_litellm_available_models(request, MagicMock(), mock_session)

    def test_401_raises_authentication_error(self) -> None:
        """Test that a 401 response raises OnyxError with authentication message."""
        from onyx.server.manage.llm.api import get_litellm_available_models

        mock_session = MagicMock()

        with patch("onyx.server.manage.llm.api.httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 401
            mock_get.side_effect = httpx.HTTPStatusError(
                "Unauthorized", request=MagicMock(), response=mock_response
            )

            request = LitellmModelsRequest(
                api_base="http://localhost:4000",
                api_key="bad-key",
            )
            with pytest.raises(OnyxError, match="Authentication failed"):
                get_litellm_available_models(request, MagicMock(), mock_session)

    def test_404_raises_not_found_error(self) -> None:
        """Test that a 404 response raises OnyxError with endpoint not found message."""
        from onyx.server.manage.llm.api import get_litellm_available_models

        mock_session = MagicMock()

        with patch("onyx.server.manage.llm.api.httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 404
            mock_get.side_effect = httpx.HTTPStatusError(
                "Not Found", request=MagicMock(), response=mock_response
            )

            request = LitellmModelsRequest(
                api_base="http://localhost:4000",
                api_key="test-key",
            )
            with pytest.raises(OnyxError, match="endpoint not found"):
                get_litellm_available_models(request, MagicMock(), mock_session)


class TestGetBifrostAvailableModels:
    """Tests for the Bifrost model fetch endpoint."""

    @pytest.fixture
    def mock_bifrost_response(self) -> dict:
        """Mock response from Bifrost /v1/models endpoint."""
        return {
            "data": [
                {
                    "id": "anthropic/claude-3-5-sonnet",
                    "name": "Claude 3.5 Sonnet",
                    "context_length": 200000,
                },
                {
                    "id": "openai/gpt-4o",
                    "name": "GPT-4o",
                    "context_length": 128000,
                },
                {
                    "id": "deepseek/deepseek-r1",
                    "name": "DeepSeek R1",
                    "context_length": 64000,
                },
            ]
        }

    def test_returns_model_list(self, mock_bifrost_response: dict) -> None:
        """Test that endpoint returns properly formatted non-embedding models."""
        from onyx.server.manage.llm.api import get_bifrost_available_models

        mock_session = MagicMock()

        with patch("onyx.server.manage.llm.api.httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.json.return_value = mock_bifrost_response
            mock_response.raise_for_status = MagicMock()
            mock_get.return_value = mock_response

            request = BifrostModelsRequest(api_base="https://bifrost.example.com")
            results = get_bifrost_available_models(request, MagicMock(), mock_session)

            assert len(results) == 3
            assert all(isinstance(r, BifrostFinalModelResponse) for r in results)
            assert [r.name for r in results] == sorted(
                [r.name for r in results], key=str.lower
            )

    def test_infers_vision_support(self, mock_bifrost_response: dict) -> None:
        """Test that vision support is inferred from provider/model IDs."""
        from onyx.server.manage.llm.api import get_bifrost_available_models

        mock_session = MagicMock()

        with patch("onyx.server.manage.llm.api.httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.json.return_value = mock_bifrost_response
            mock_response.raise_for_status = MagicMock()
            mock_get.return_value = mock_response

            request = BifrostModelsRequest(api_base="https://bifrost.example.com")
            results = get_bifrost_available_models(request, MagicMock(), mock_session)

            claude = next(r for r in results if r.name == "anthropic/claude-3-5-sonnet")
            gpt4o = next(r for r in results if r.name == "openai/gpt-4o")
            deepseek = next(r for r in results if r.name == "deepseek/deepseek-r1")

            assert claude.supports_image_input is True
            assert gpt4o.supports_image_input is True
            assert deepseek.supports_image_input is False

    def test_existing_v1_suffix_is_not_duplicated(self) -> None:
        """Test that an existing /v1 suffix still hits a single /v1/models endpoint."""
        from onyx.server.manage.llm.api import get_bifrost_available_models

        mock_session = MagicMock()
        response = {"data": [{"id": "openai/gpt-4o", "name": "GPT-4o"}]}

        with patch("onyx.server.manage.llm.api.httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.json.return_value = response
            mock_response.raise_for_status = MagicMock()
            mock_get.return_value = mock_response

            request = BifrostModelsRequest(api_base="https://bifrost.example.com/v1")
            get_bifrost_available_models(request, MagicMock(), mock_session)

            called_url = mock_get.call_args[0][0]
            assert called_url == "https://bifrost.example.com/v1/models"

    def test_request_failure_is_logged_and_wrapped(self) -> None:
        """Test that request-layer failures are logged before raising OnyxError."""
        from onyx.server.manage.llm.api import get_bifrost_available_models

        mock_session = MagicMock()

        with (
            patch("onyx.server.manage.llm.api.httpx.get") as mock_get,
            patch("onyx.server.manage.llm.api.logger.warning") as mock_warning,
        ):
            mock_get.side_effect = httpx.ConnectError(
                "Connection refused", request=MagicMock()
            )

            request = BifrostModelsRequest(api_base="https://bifrost.example.com")
            with pytest.raises(OnyxError, match="Failed to fetch Bifrost models"):
                get_bifrost_available_models(request, MagicMock(), mock_session)

            mock_warning.assert_called_once()
