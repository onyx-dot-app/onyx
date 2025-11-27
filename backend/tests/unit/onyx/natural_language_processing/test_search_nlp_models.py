import os
from collections.abc import AsyncGenerator
from typing import List
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from litellm.exceptions import RateLimitError

from onyx.natural_language_processing.search_nlp_models import CloudEmbedding
from onyx.natural_language_processing.search_nlp_models import (
    ConnectorClassificationModel,
)
from onyx.natural_language_processing.search_nlp_models import (
    InformationContentClassificationModel,
)
from shared_configs.enums import EmbeddingProvider
from shared_configs.enums import EmbedTextType


@pytest.fixture
async def mock_http_client() -> AsyncGenerator[AsyncMock, None]:
    with patch("httpx.AsyncClient") as mock:
        client = AsyncMock(spec=AsyncClient)
        mock.return_value = client
        client.post = AsyncMock()
        async with client as c:
            yield c


@pytest.fixture
def sample_embeddings() -> List[List[float]]:
    return [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]


@pytest.mark.asyncio
async def test_cloud_embedding_context_manager() -> None:
    async with CloudEmbedding("fake-key", EmbeddingProvider.OPENAI) as embedding:
        assert not embedding._closed
    assert embedding._closed


@pytest.mark.asyncio
async def test_cloud_embedding_explicit_close() -> None:
    embedding = CloudEmbedding("fake-key", EmbeddingProvider.OPENAI)
    assert not embedding._closed
    await embedding.aclose()
    assert embedding._closed


@pytest.mark.asyncio
async def test_openai_embedding(
    mock_http_client: AsyncMock, sample_embeddings: List[List[float]]
) -> None:
    with patch("openai.AsyncOpenAI") as mock_openai:
        mock_client = AsyncMock()
        mock_openai.return_value = mock_client

        mock_response = MagicMock()
        mock_response.data = [MagicMock(embedding=emb) for emb in sample_embeddings]
        mock_client.embeddings.create = AsyncMock(return_value=mock_response)

        embedding = CloudEmbedding("fake-key", EmbeddingProvider.OPENAI)
        result = await embedding._embed_openai(
            ["test1", "test2"], "text-embedding-ada-002", None
        )

        assert result == sample_embeddings
        mock_client.embeddings.create.assert_called_once()


@pytest.mark.asyncio
async def test_rate_limit_handling() -> None:
    with patch(
        "onyx.natural_language_processing.search_nlp_models.CloudEmbedding.embed"
    ) as mock_embed:
        mock_embed.side_effect = RateLimitError(
            "Rate limit exceeded", llm_provider="openai", model="fake-model"
        )

        embedding = CloudEmbedding("fake-key", EmbeddingProvider.OPENAI)

        with pytest.raises(RateLimitError):
            await embedding.embed(
                texts=["test"],
                model_name="fake-model",
                text_type=EmbedTextType.QUERY,
            )


class TestInformationContentClassificationModel:
    """Test cases for InformationContentClassificationModel with DISABLE_MODEL_SERVER"""

    @patch.dict(os.environ, {"DISABLE_MODEL_SERVER": "true"})
    def test_predict_with_disable_model_server(self) -> None:
        """Test that predict returns default classifications when DISABLE_MODEL_SERVER is true"""
        model = InformationContentClassificationModel()
        queries = ["What is AI?", "How does Python work?"]

        results = model.predict(queries)

        assert len(results) == 2
        for result in results:
            assert result.predicted_label == 1  # 1 indicates informational content
            assert result.content_boost_factor == 1.0  # Default boost factor

    @patch.dict(os.environ, {"DISABLE_MODEL_SERVER": "false"})
    @patch("requests.post")
    def test_predict_with_model_server_enabled(self, mock_post: MagicMock) -> None:
        """Test that predict makes request when DISABLE_MODEL_SERVER is false"""
        mock_response = MagicMock()
        mock_response.json.return_value = [
            {"predicted_label": 1, "content_boost_factor": 1.0},
            {"predicted_label": 0, "content_boost_factor": 0.8},
        ]
        mock_post.return_value = mock_response

        model = InformationContentClassificationModel()
        queries = ["test1", "test2"]

        results = model.predict(queries)

        assert len(results) == 2
        assert results[0].predicted_label == 1
        assert results[0].content_boost_factor == 1.0
        assert results[1].predicted_label == 0
        assert results[1].content_boost_factor == 0.8
        mock_post.assert_called_once()


class TestConnectorClassificationModel:
    """Test cases for ConnectorClassificationModel with DISABLE_MODEL_SERVER"""

    @patch.dict(os.environ, {"DISABLE_MODEL_SERVER": "true"})
    def test_predict_with_disable_model_server(self) -> None:
        """Test that predict returns all connectors when DISABLE_MODEL_SERVER is true"""
        model = ConnectorClassificationModel()
        query = "Search for documentation"
        available_connectors = ["confluence", "slack", "github"]

        results = model.predict(query, available_connectors)

        assert results == available_connectors

    @patch.dict(os.environ, {"DISABLE_MODEL_SERVER": "false"})
    @patch("requests.post")
    def test_predict_with_model_server_enabled(self, mock_post: MagicMock) -> None:
        """Test that predict makes request when DISABLE_MODEL_SERVER is false"""
        mock_response = MagicMock()
        mock_response.json.return_value = {"connectors": ["confluence", "github"]}
        mock_post.return_value = mock_response

        model = ConnectorClassificationModel()
        query = "Search for documentation"
        available_connectors = ["confluence", "slack", "github"]

        results = model.predict(query, available_connectors)

        assert results == ["confluence", "github"]
        mock_post.assert_called_once()

    @patch.dict(os.environ, {"DISABLE_MODEL_SERVER": "1"})
    @patch("requests.post")
    def test_predict_with_disable_model_server_numeric(self, mock_post: MagicMock) -> None:
        """Test that predict makes request when DISABLE_MODEL_SERVER is 1 (not 'true')"""
        # "1" should NOT trigger disable (only "true" should)
        mock_response = MagicMock()
        mock_response.json.return_value = {"connectors": ["github"]}
        mock_post.return_value = mock_response

        model = ConnectorClassificationModel()
        query = "Find issues"
        available_connectors = ["jira", "github"]

        results = model.predict(query, available_connectors)

        assert results == ["github"]
        mock_post.assert_called_once()
