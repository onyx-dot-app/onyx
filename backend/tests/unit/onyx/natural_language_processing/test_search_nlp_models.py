from collections.abc import AsyncGenerator
from typing import List
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from litellm.exceptions import RateLimitError

from onyx.llm.constants import LlmProviderNames
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


def _build_google_embed_response(
    sample_embeddings: List[List[float]],
) -> MagicMock:
    response = MagicMock()
    response.embeddings = [
        MagicMock(values=embedding) for embedding in sample_embeddings
    ]
    return response


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
    mock_http_client: AsyncMock,  # noqa: ARG001
    sample_embeddings: List[List[float]],
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
            "Rate limit exceeded",
            llm_provider=LlmProviderNames.OPENAI,
            model="fake-model",
        )

        embedding = CloudEmbedding("fake-key", EmbeddingProvider.OPENAI)

        with pytest.raises(RateLimitError):
            await embedding.embed(
                texts=["test"],
                model_name="fake-model",
                text_type=EmbedTextType.QUERY,
            )


@pytest.mark.asyncio
async def test_vertex_embed_keeps_task_type_for_existing_models(
    sample_embeddings: List[List[float]],
) -> None:
    with patch(
        "google.oauth2.service_account.Credentials.from_service_account_info"
    ) as mock_credentials:
        mock_credentials.return_value = MagicMock()

        with patch("google.genai.Client") as mock_genai_client:
            mock_client = MagicMock()
            mock_client.aio.models.embed_content = AsyncMock(
                return_value=_build_google_embed_response(sample_embeddings[:1])
            )
            mock_client.aio.aclose = AsyncMock()
            mock_genai_client.return_value = mock_client

            embedding = CloudEmbedding(
                '{"project_id":"test-project"}',
                EmbeddingProvider.GOOGLE,
            )
            try:
                result = await embedding._embed_vertex(
                    ["query text"],
                    "text-embedding-005",
                    "RETRIEVAL_QUERY",
                    128,
                )
            finally:
                await embedding.aclose()

            assert result == sample_embeddings[:1]

            embed_call = mock_client.aio.models.embed_content.await_args
            assert embed_call is not None
            config = embed_call.kwargs["config"]
            contents = embed_call.kwargs["contents"]

            assert config.task_type == "RETRIEVAL_QUERY"
            assert config.output_dimensionality == 128
            assert config.auto_truncate is True
            assert contents[0].parts[0].text == "query text"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("embedding_type", "expected_instruction"),
    [
        (
            "RETRIEVAL_QUERY",
            "Represent this query for retrieving relevant documents.",
        ),
        (
            "RETRIEVAL_DOCUMENT",
            "Represent this document for retrieval.",
        ),
    ],
)
async def test_vertex_embed_uses_instruction_prefix_for_gemini_embedding_2(
    embedding_type: str,
    expected_instruction: str,
    sample_embeddings: List[List[float]],
) -> None:
    with patch(
        "google.oauth2.service_account.Credentials.from_service_account_info"
    ) as mock_credentials:
        mock_credentials.return_value = MagicMock()

        with patch("google.genai.Client") as mock_genai_client:
            mock_client = MagicMock()
            mock_client.aio.models.embed_content = AsyncMock(
                return_value=_build_google_embed_response(sample_embeddings[:1])
            )
            mock_client.aio.aclose = AsyncMock()
            mock_genai_client.return_value = mock_client

            embedding = CloudEmbedding(
                '{"project_id":"test-project"}',
                EmbeddingProvider.GOOGLE,
            )
            try:
                result = await embedding._embed_vertex(
                    ["document text"],
                    "google/gemini-embedding-2",
                    embedding_type,
                    256,
                )
            finally:
                await embedding.aclose()

            assert result == sample_embeddings[:1]

            embed_call = mock_client.aio.models.embed_content.await_args
            assert embed_call is not None
            config = embed_call.kwargs["config"]
            contents = embed_call.kwargs["contents"]

            assert config.task_type is None
            assert config.output_dimensionality == 256
            assert config.auto_truncate is True
            assert (
                contents[0].parts[0].text == f"{expected_instruction}\n\ndocument text"
            )
