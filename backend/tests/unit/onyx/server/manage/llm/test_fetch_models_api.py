"""Tests for LLM model fetch endpoints.

These tests verify the full request/response flow for fetching models
from dynamic providers (Ollama, OpenRouter, Litellm), including the
sync-to-DB behavior when provider_name is specified.
"""

from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from onyx.server.manage.llm.models import LitellmFinalModelResponse
from onyx.server.manage.llm.models import LitellmModelsRequest
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

    def test_empty_data_raises_http_exception(self) -> None:
        """Test that empty model list raises HTTPException."""
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
            with pytest.raises(HTTPException) as exc_info:
                get_litellm_available_models(request, MagicMock(), mock_session)

            assert exc_info.value.status_code == 400
            assert "No models found" in str(exc_info.value.detail)

    def test_missing_data_key_raises_http_exception(self) -> None:
        """Test that response without 'data' key raises HTTPException."""
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
            with pytest.raises(HTTPException) as exc_info:
                get_litellm_available_models(request, MagicMock(), mock_session)

            assert exc_info.value.status_code == 400

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

    def test_all_entries_unparseable_raises_http_exception(self) -> None:
        """Test that HTTPException is raised when all entries fail to parse."""
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
            with pytest.raises(HTTPException) as exc_info:
                get_litellm_available_models(request, MagicMock(), mock_session)

            assert exc_info.value.status_code == 400
            assert "No compatible models" in str(exc_info.value.detail)

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

    def test_connection_failure_raises_http_exception(self) -> None:
        """Test that connection failures are wrapped in HTTPException."""
        from onyx.server.manage.llm.api import get_litellm_available_models

        mock_session = MagicMock()

        with patch("onyx.server.manage.llm.api.httpx.get") as mock_get:
            mock_get.side_effect = Exception("Connection refused")

            request = LitellmModelsRequest(
                api_base="http://localhost:4000",
                api_key="test-key",
            )
            with pytest.raises(HTTPException) as exc_info:
                get_litellm_available_models(request, MagicMock(), mock_session)

            assert exc_info.value.status_code == 400
            assert "Failed to fetch Litellm models" in str(exc_info.value.detail)
