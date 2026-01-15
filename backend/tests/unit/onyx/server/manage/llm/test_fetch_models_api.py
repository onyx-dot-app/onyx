"""Tests for LLM model fetch endpoints.

These tests verify the full request/response flow for fetching models
from dynamic providers (Ollama, OpenRouter), including the
sync-to-DB behavior when provider_name is specified.
"""

from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

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
            results = get_ollama_available_models(request, None, mock_session)

            assert len(results) == 3
            assert all(isinstance(r, OllamaFinalModelResponse) for r in results)
            # Check display names are generated
            assert any("Llama" in r.display_name for r in results)
            assert any("Mistral" in r.display_name for r in results)

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
            get_ollama_available_models(request, None, mock_session)

            # Verify DB operations were called
            assert mock_session.execute.call_count == 3  # 3 models inserted
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
            get_ollama_available_models(request, None, mock_session)

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
            results = get_openrouter_available_models(request, None, mock_session)

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
            results = get_openrouter_available_models(request, None, mock_session)

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
            get_openrouter_available_models(request, None, mock_session)

            # Verify DB operations were called
            assert mock_session.execute.call_count == 3  # 3 models inserted
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
            get_openrouter_available_models(request, None, mock_session)

            # Only 2 new models should be inserted (claude already exists)
            assert mock_session.execute.call_count == 2

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
            get_openrouter_available_models(request, None, mock_session)

            # No DB operations should happen
            mock_session.execute.assert_not_called()
            mock_session.commit.assert_not_called()
