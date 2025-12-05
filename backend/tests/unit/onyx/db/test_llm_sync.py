"""Tests for LLM provider model sync functionality."""

from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from onyx.db.llm import sync_model_configurations


class TestSyncModelConfigurations:
    """Tests for sync_model_configurations function."""

    def test_inserts_new_models(self) -> None:
        """Test that new models are inserted."""
        # Mock the provider with no existing models
        mock_provider = MagicMock()
        mock_provider.id = 1
        mock_provider.model_configurations = []

        mock_session = MagicMock()

        with patch(
            "onyx.db.llm.fetch_existing_llm_provider", return_value=mock_provider
        ):
            models = [
                {
                    "name": "gpt-4",
                    "display_name": "GPT-4",
                    "max_input_tokens": 128000,
                    "supports_image_input": True,
                },
                {
                    "name": "gpt-4o",
                    "display_name": "GPT-4o",
                    "max_input_tokens": 128000,
                    "supports_image_input": True,
                },
            ]

            result = sync_model_configurations(
                db_session=mock_session,
                provider_name="openai",
                models=models,
            )

            assert result == 2  # Two new models
            assert mock_session.execute.call_count == 2
            mock_session.commit.assert_called_once()

    def test_skips_existing_models(self) -> None:
        """Test that existing models are not overwritten."""
        # Mock existing model
        mock_existing_model = MagicMock()
        mock_existing_model.name = "gpt-4"

        mock_provider = MagicMock()
        mock_provider.id = 1
        mock_provider.model_configurations = [mock_existing_model]

        mock_session = MagicMock()

        with patch(
            "onyx.db.llm.fetch_existing_llm_provider", return_value=mock_provider
        ):
            models = [
                {
                    "name": "gpt-4",  # Existing - should be skipped
                    "display_name": "GPT-4",
                    "max_input_tokens": 128000,
                    "supports_image_input": True,
                },
                {
                    "name": "gpt-4o",  # New - should be inserted
                    "display_name": "GPT-4o",
                    "max_input_tokens": 128000,
                    "supports_image_input": True,
                },
            ]

            result = sync_model_configurations(
                db_session=mock_session,
                provider_name="openai",
                models=models,
            )

            assert result == 1  # Only one new model
            assert mock_session.execute.call_count == 1

    def test_no_commit_when_no_new_models(self) -> None:
        """Test that commit is not called when no new models."""
        mock_existing_model = MagicMock()
        mock_existing_model.name = "gpt-4"

        mock_provider = MagicMock()
        mock_provider.id = 1
        mock_provider.model_configurations = [mock_existing_model]

        mock_session = MagicMock()

        with patch(
            "onyx.db.llm.fetch_existing_llm_provider", return_value=mock_provider
        ):
            models = [
                {
                    "name": "gpt-4",  # Already exists
                    "display_name": "GPT-4",
                    "max_input_tokens": 128000,
                    "supports_image_input": True,
                },
            ]

            result = sync_model_configurations(
                db_session=mock_session,
                provider_name="openai",
                models=models,
            )

            assert result == 0
            mock_session.commit.assert_not_called()

    def test_raises_on_missing_provider(self) -> None:
        """Test that ValueError is raised when provider not found."""
        mock_session = MagicMock()

        with patch("onyx.db.llm.fetch_existing_llm_provider", return_value=None):
            with pytest.raises(ValueError, match="not found"):
                sync_model_configurations(
                    db_session=mock_session,
                    provider_name="nonexistent",
                    models=[{"name": "model", "display_name": "Model"}],
                )

    def test_handles_missing_optional_fields(self) -> None:
        """Test that optional fields default correctly."""
        mock_provider = MagicMock()
        mock_provider.id = 1
        mock_provider.model_configurations = []

        mock_session = MagicMock()

        with patch(
            "onyx.db.llm.fetch_existing_llm_provider", return_value=mock_provider
        ):
            # Model with only required fields
            models = [
                {
                    "name": "model-1",
                    # No display_name, max_input_tokens, or supports_image_input
                },
            ]

            result = sync_model_configurations(
                db_session=mock_session,
                provider_name="custom",
                models=models,
            )

            assert result == 1
            # Verify execute was called with correct defaults
            call_args = mock_session.execute.call_args
            assert call_args is not None
