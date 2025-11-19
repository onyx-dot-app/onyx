from collections.abc import AsyncGenerator
from typing import List
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from litellm.exceptions import RateLimitError

from onyx.natural_language_processing.search_nlp_models import CloudEmbedding
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
