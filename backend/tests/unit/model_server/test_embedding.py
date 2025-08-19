import asyncio
import time
from typing import Any
from typing import List
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from model_server.encoders import embed_text
from model_server.encoders import local_rerank
from model_server.encoders import process_embed_request
from shared_configs.enums import EmbedTextType
from shared_configs.model_server_models import EmbedRequest


@pytest.mark.asyncio
async def test_embed_text_no_model_name() -> None:
    # Test that the function raises an error when no model name is provided
    with pytest.raises(
        ValueError,
        match="Model name must be provided to run embeddings",
    ):
        await embed_text(
            texts=["test1", "test2"],
            model_name=None,
            max_context_length=512,
            normalize_embeddings=True,
            prefix=None,
        )


@pytest.mark.asyncio
async def test_embed_text_local_model() -> None:
    with patch("model_server.encoders.get_embedding_model") as mock_get_model:
        mock_model = MagicMock()
        mock_model.encode.return_value = [[0.1, 0.2], [0.3, 0.4]]
        mock_get_model.return_value = mock_model

        result = await embed_text(
            texts=["test1", "test2"],
            model_name="fake-local-model",
            max_context_length=512,
            normalize_embeddings=True,
            prefix=None,
        )

        assert result == [[0.1, 0.2], [0.3, 0.4]]
        mock_model.encode.assert_called_once()


@pytest.mark.asyncio
async def test_local_rerank() -> None:
    with patch("model_server.encoders.get_local_reranking_model") as mock_get_model:
        mock_model = MagicMock()
        mock_array = MagicMock()
        mock_array.tolist.return_value = [0.8, 0.6]
        mock_model.predict.return_value = mock_array
        mock_get_model.return_value = mock_model

        result = await local_rerank(
            query="test query", docs=["doc1", "doc2"], model_name="fake-rerank-model"
        )

        assert result == [0.8, 0.6]
        mock_model.predict.assert_called_once()


@pytest.mark.asyncio
async def test_concurrent_embeddings() -> None:
    def mock_encode(*args: Any, **kwargs: Any) -> List[List[float]]:
        time.sleep(5)
        return [[0.1, 0.2, 0.3]]

    test_req = EmbedRequest(
        texts=["test"],
        model_name="'nomic-ai/nomic-embed-text-v1'",
        deployment_name=None,
        max_context_length=512,
        normalize_embeddings=True,
        api_key=None,
        provider_type=None,
        text_type=EmbedTextType.QUERY,
        manual_query_prefix=None,
        manual_passage_prefix=None,
        api_url=None,
        api_version=None,
        reduced_dimension=None,
    )

    with patch("model_server.encoders.get_embedding_model") as mock_get_model:
        mock_model = MagicMock()
        mock_model.encode = mock_encode
        mock_get_model.return_value = mock_model
        start_time = time.time()

        tasks = [process_embed_request(test_req) for _ in range(5)]
        await asyncio.gather(*tasks)

        end_time = time.time()

        # 5 * 5 seconds = 25 seconds, this test ensures that the embeddings are at least yielding the thread
        # However, the developer may still introduce unnecessary blocking above the mock and this test will
        # still pass as long as it's less than (7 - 5) / 5 seconds
        assert end_time - start_time < 7
