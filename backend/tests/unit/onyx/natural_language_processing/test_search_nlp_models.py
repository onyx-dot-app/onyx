from collections.abc import AsyncGenerator
from threading import Lock
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from litellm.exceptions import RateLimitError

from onyx.llm.constants import LlmProviderNames
from onyx.natural_language_processing.search_nlp_models import CloudEmbedding
from onyx.natural_language_processing.search_nlp_models import EmbeddingModel
from shared_configs.enums import EmbeddingProvider
from shared_configs.enums import EmbedTextType
from shared_configs.model_server_models import EmbedRequest
from shared_configs.model_server_models import EmbedResponse


@pytest.fixture
async def mock_http_client() -> AsyncGenerator[AsyncMock, None]:
    with patch("httpx.AsyncClient") as mock:
        client = AsyncMock(spec=AsyncClient)
        mock.return_value = client
        client.post = AsyncMock()
        async with client as c:
            yield c


@pytest.fixture
def sample_embeddings() -> list[list[float]]:
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
    mock_http_client: AsyncMock,  # noqa: ARG001
    sample_embeddings: list[list[float]],
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


# ------------------------------------------------------------------------------
# _batch_encode_texts tests
#
# Tests correct ordering of the embedding results, and that sync and async
# caller contexts both work.
# ------------------------------------------------------------------------------

_SEARCH_NLP_MODULE = "onyx.natural_language_processing.search_nlp_models"


def _text_for_idx(i: int) -> str:
    return f"text_{i}"


def _embedding_for_idx(i: int) -> list[float]:
    return [float(i)]


def _embedding_for_text(text: str) -> list[float]:
    return _embedding_for_idx(int(text.split("_")[1]))


def _fake_direct_api_call(embed_request: EmbedRequest) -> EmbedResponse:
    return EmbedResponse(
        embeddings=[_embedding_for_text(t) for t in embed_request.texts]
    )


def _fake_model_server_call(
    embed_request: EmbedRequest,
    tenant_id: str | None = None,  # noqa: ARG001
    request_id: str | None = None,  # noqa: ARG001
) -> EmbedResponse:
    return EmbedResponse(
        embeddings=[_embedding_for_text(t) for t in embed_request.texts]
    )


def _make_cloud_embedding_model() -> EmbeddingModel:
    with patch(f"{_SEARCH_NLP_MODULE}.get_tokenizer", return_value=MagicMock()):
        return EmbeddingModel(
            server_host="localhost",
            server_port=9000,
            model_name="text-embedding-3-small",
            normalize=True,
            query_prefix=None,
            passage_prefix=None,
            api_key="fake-key",
            api_url=None,
            provider_type=EmbeddingProvider.OPENAI,
        )


def _make_local_embedding_model() -> EmbeddingModel:
    with patch(f"{_SEARCH_NLP_MODULE}.get_tokenizer", return_value=MagicMock()):
        return EmbeddingModel(
            server_host="localhost",
            server_port=9000,
            model_name="nomic-ai/nomic-embed-text-v1",
            normalize=True,
            query_prefix=None,
            passage_prefix=None,
            api_key=None,
            api_url=None,
            provider_type=None,
        )


def test_batch_encode_multi_batch_partial_last() -> None:
    """
    Tests that the multi-threaded path with non-uniform batches preserves
    expected ordering and cardinality of embeddings given an input.
    """
    # Precondition.
    model = _make_cloud_embedding_model()
    n_texts = 13  # 3 batches of 4 + 1 partial batch of 1.
    texts = [_text_for_idx(i) for i in range(n_texts)]

    # Under test.
    with patch.object(
        EmbeddingModel,
        "_make_direct_api_call",
        new=AsyncMock(side_effect=_fake_direct_api_call),
    ):
        result = model.encode(
            texts=texts,
            text_type=EmbedTextType.PASSAGE,  # Arbitrary.
            api_embedding_batch_size=4,
        )

    # Postcondition.
    assert result == [_embedding_for_idx(i) for i in range(n_texts)]


def test_batch_encode_multi_batch_uniform() -> None:
    """
    Tests that the multi-threaded path with uniform batches preserves expected
    ordering and cardinality of embeddings given an input.
    """
    # Precondition.
    model = _make_cloud_embedding_model()
    n_texts = 16  # 4 batches of 4.
    texts = [_text_for_idx(i) for i in range(n_texts)]

    # Under test.
    with patch.object(
        EmbeddingModel,
        "_make_direct_api_call",
        new=AsyncMock(side_effect=_fake_direct_api_call),
    ):
        result = model.encode(
            texts=texts,
            text_type=EmbedTextType.PASSAGE,  # Arbitrary.
            api_embedding_batch_size=4,
        )

    # Postcondition.
    assert result == [_embedding_for_idx(i) for i in range(n_texts)]


def test_batch_encode_single_batch_sequential() -> None:
    """
    Tests that the sequential path with a single batch preserves expected
    ordering and cardinality of embeddings given an input.
    """
    # Precondition.
    model = _make_cloud_embedding_model()
    n_texts = 3  # Less than the batch size.
    texts = [_text_for_idx(i) for i in range(n_texts)]

    # Under test.
    with patch.object(
        EmbeddingModel,
        "_make_direct_api_call",
        new=AsyncMock(side_effect=_fake_direct_api_call),
    ):
        result = model.encode(
            texts=texts,
            text_type=EmbedTextType.PASSAGE,  # Arbitrary.
            api_embedding_batch_size=4,
        )

    # Postcondition.
    assert result == [_embedding_for_idx(i) for i in range(n_texts)]


def test_batch_encode_local_model_sequential() -> None:
    """
    Tests that the sequential path with a local model preserves expected
    ordering and cardinality of embeddings given an input.
    """
    # Precondition.
    model = _make_local_embedding_model()
    n_texts = 10  # 2 batches of 4 + 1 partial batch of 2.
    texts = [_text_for_idx(i) for i in range(n_texts)]

    # Under test.
    with patch.object(
        EmbeddingModel,
        "_make_model_server_request",
        side_effect=_fake_model_server_call,
    ):
        result = model.encode(
            texts=texts,
            text_type=EmbedTextType.PASSAGE,  # Arbitrary.
            local_embedding_batch_size=4,
        )

    # Postcondition.
    assert result == [_embedding_for_idx(i) for i in range(n_texts)]


def test_batch_encode_error_propagates() -> None:
    """
    Tests that a failing batch propagates its exception out of encode().
    """
    # Precondition.
    model = _make_cloud_embedding_model()
    texts = [_text_for_idx(i) for i in range(8)]

    call_count = {"n": 0}
    call_count_lock = Lock()

    def _fail_on_second_call(embed_request: EmbedRequest) -> EmbedResponse:
        with call_count_lock:
            call_count["n"] += 1
            if call_count["n"] == 2:
                raise RuntimeError("simulated provider failure")
        return _fake_direct_api_call(embed_request)

    # Under test and postcondition.
    with patch.object(
        EmbeddingModel,
        "_make_direct_api_call",
        new=AsyncMock(side_effect=_fail_on_second_call),
    ):
        with pytest.raises(RuntimeError, match="simulated provider failure"):
            model.encode(
                texts=texts,
                text_type=EmbedTextType.PASSAGE,  # Arbitrary.
                api_embedding_batch_size=2,
            )


def test_batch_encode_sync_caller_uses_thread_local_loop() -> None:
    """
    Tests that a sync call uses the thread-local event loop and does not call
    asyncio.run.
    """
    # Precondition.
    model = _make_cloud_embedding_model()
    texts = [_text_for_idx(i) for i in range(4)]

    # Under test.
    with (
        patch.object(
            EmbeddingModel,
            "_make_direct_api_call",
            new=AsyncMock(side_effect=_fake_direct_api_call),
        ),
        patch(f"{_SEARCH_NLP_MODULE}.asyncio.run") as mock_asyncio_run,
    ):
        result = model.encode(
            texts=texts,
            text_type=EmbedTextType.PASSAGE,  # Arbitrary.
            api_embedding_batch_size=4,
        )

    # Postcondition.
    assert result == [_embedding_for_idx(i) for i in range(4)]
    assert mock_asyncio_run.call_count == 0


@pytest.mark.asyncio
async def test_batch_encode_async_caller_single_batch_no_deadlock() -> None:
    """
    Tests that an async call using the sequential path calls asyncio.run exactly
    once, and that this call succeeds. In this path the caller is in an event
    loop, so calling asyncio.run would raise as a thread running an event loop
    cannot wait on itself. Calling asyncio.run in a thread with no event loop is
    safe.
    """
    # Precondition.
    model = _make_cloud_embedding_model()
    n_texts = 4  # 1 batch of 4.
    texts = [_text_for_idx(i) for i in range(n_texts)]

    # Under test.
    with (
        patch.object(
            EmbeddingModel,
            "_make_direct_api_call",
            new=AsyncMock(side_effect=_fake_direct_api_call),
        ),
        patch(
            f"{_SEARCH_NLP_MODULE}.asyncio.run",
            wraps=__import__("asyncio").run,
        ) as spy_asyncio_run,
    ):
        result = model.encode(
            texts=texts,
            text_type=EmbedTextType.PASSAGE,  # Arbitrary.
            api_embedding_batch_size=4,
        )

    # Postcondition.
    assert result == [_embedding_for_idx(i) for i in range(n_texts)]
    assert spy_asyncio_run.call_count == 1


@pytest.mark.asyncio
async def test_batch_encode_async_caller_multi_batch() -> None:
    """
    Tests that an async call using the multi-threaded path does not call
    asyncio.run, and that the encode call succeeds. In this path the caller is
    in an event loop, but the batches are processed in separate threads which do
    not have running event loops, so we do not expect to call asyncio.run.
    """
    # Precondition.
    model = _make_cloud_embedding_model()
    n_texts = 13  # 3 batches of 4 + 1 partial batch of 1.
    texts = [_text_for_idx(i) for i in range(n_texts)]

    # Under test.
    with (
        patch.object(
            EmbeddingModel,
            "_make_direct_api_call",
            new=AsyncMock(side_effect=_fake_direct_api_call),
        ),
        patch(
            f"{_SEARCH_NLP_MODULE}.asyncio.run",
            wraps=__import__("asyncio").run,
        ) as spy_asyncio_run,
    ):
        result = model.encode(
            texts=texts,
            text_type=EmbedTextType.PASSAGE,  # Arbitrary.
            api_embedding_batch_size=4,
        )

    # Postcondition.
    assert result == [_embedding_for_idx(i) for i in range(n_texts)]
    assert spy_asyncio_run.call_count == 0
