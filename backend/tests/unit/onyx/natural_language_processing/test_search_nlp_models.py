import asyncio
import json
from collections.abc import AsyncGenerator, Callable, Iterator
from threading import Lock
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from cohere import AsyncClient as RealCohereAsyncClient
from google import genai
from google.genai import _transformers as genai_transformers
from google.genai import types as genai_types
from google.oauth2.credentials import Credentials as TokenCredentials
from httpx import AsyncClient
from litellm.exceptions import RateLimitError
from tenacity import wait_none

from onyx.llm.constants import LlmProviderNames
from onyx.natural_language_processing.search_nlp_models import (
    AuthenticationError,
    CloudEmbedding,
    EmbeddingModel,
    _vertex_requires_single_content,
    clean_model_name,
)
from shared_configs.enums import EmbeddingProvider, EmbedTextType
from shared_configs.model_server_models import EmbedRequest, EmbedResponse


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


def test_clean_model_name_lowercases_names_for_opensearch_index() -> None:
    cleaned_model_name = clean_model_name("Qwen3-VL-Embedding-8B")

    assert cleaned_model_name == "qwen3_vl_embedding_8b"
    assert (
        f"danswer_chunk_{cleaned_model_name}" == "danswer_chunk_qwen3_vl_embedding_8b"
    )


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


def _build_google_embed_response(
    embeddings: list[list[float]],
) -> MagicMock:
    response = MagicMock()
    response.embeddings = [MagicMock(values=embedding) for embedding in embeddings]
    return response


@pytest.mark.asyncio
async def test_vertex_embed_keeps_task_type_for_existing_models(
    sample_embeddings: list[list[float]],
) -> None:
    """Existing Vertex models continue to receive task_type and unmodified text."""
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
    "model_name",
    ["gemini-embedding-2", "gemini-embedding-2-preview"],
)
@pytest.mark.parametrize(
    ("embedding_type", "expected_text"),
    [
        ("RETRIEVAL_QUERY", "task: search result | query: hello world"),
        ("RETRIEVAL_DOCUMENT", "title: none | text: hello world"),
    ],
)
async def test_vertex_embed_uses_instruction_prefix_for_gemini_embedding_2(
    model_name: str,
    embedding_type: str,
    expected_text: str,
    sample_embeddings: list[list[float]],
) -> None:
    """gemini-embedding-2 omits task_type and prefixes the text per Google's docs."""
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
                    ["hello world"],
                    model_name,
                    embedding_type,
                    None,
                )
            finally:
                await embedding.aclose()

            assert result == sample_embeddings[:1]

            embed_call = mock_client.aio.models.embed_content.await_args
            assert embed_call is not None
            config = embed_call.kwargs["config"]
            contents = embed_call.kwargs["contents"]

            assert config.task_type is None
            assert contents[0].parts[0].text == expected_text


@pytest.mark.asyncio
async def test_cohere_embed_supports_v3_response_format(
    sample_embeddings: list[list[float]],
) -> None:
    """v3 models hand back ``response.embeddings`` as a flat ``list[list[float]]``."""
    with patch(
        "onyx.natural_language_processing.search_nlp_models.CohereAsyncClient"
    ) as mock_cohere:
        mock_client = AsyncMock()
        mock_cohere.return_value = mock_client

        mock_response = MagicMock()
        mock_response.embeddings = sample_embeddings
        mock_client.embed = AsyncMock(return_value=mock_response)

        embedding = CloudEmbedding("fake-key", EmbeddingProvider.COHERE)
        try:
            result = await embedding._embed_cohere(
                ["test1", "test2"],
                "embed-english-v3.0",
                "search_document",
            )
        finally:
            await embedding.aclose()

        assert result == sample_embeddings


@pytest.mark.asyncio
async def test_cohere_embed_supports_v4_response_format(
    sample_embeddings: list[list[float]],
) -> None:
    """v4 models hand back ``response.embeddings`` as an EmbedByTypeResponseEmbeddings
    object with the float bucket on ``.float_``."""
    with patch(
        "onyx.natural_language_processing.search_nlp_models.CohereAsyncClient"
    ) as mock_cohere:
        mock_client = AsyncMock()
        mock_cohere.return_value = mock_client

        embeddings_by_type = MagicMock()
        embeddings_by_type.float_ = sample_embeddings

        mock_response = MagicMock()
        mock_response.embeddings = embeddings_by_type
        mock_client.embed = AsyncMock(return_value=mock_response)

        embedding = CloudEmbedding("fake-key", EmbeddingProvider.COHERE)
        try:
            result = await embedding._embed_cohere(
                ["test1", "test2"],
                "embed-v4.0",
                "search_document",
            )
        finally:
            await embedding.aclose()

        assert result == sample_embeddings


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
async def test_cloud_embedding_retries_on_transient_failure() -> None:
    """
    The @retry decorator on CloudEmbedding.embed should re-invoke the provider
    after a transient failure. We simulate a failure on the first attempt and
    a success on the second, and assert embed() returns the successful result.
    """
    call_count = 0

    async def flaky_embed_openai(
        self: CloudEmbedding,  # noqa: ARG001
        texts: list[str],
        model: str | None,  # noqa: ARG001
        reduced_dimension: int | None,  # noqa: ARG001
    ) -> list[list[float]]:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("simulated transient failure on attempt 1")
        return [[0.1, 0.2, 0.3] for _ in texts]

    with (
        patch.object(cast(Any, CloudEmbedding.embed).retry, "wait", wait_none()),
        patch.object(
            CloudEmbedding,
            CloudEmbedding._embed_openai.__name__,
            new=flaky_embed_openai,
        ),
    ):
        async with CloudEmbedding("fake-key", EmbeddingProvider.OPENAI) as embedding:
            result = await embedding.embed(
                texts=["test"],
                text_type=EmbedTextType.PASSAGE,
            )

    assert call_count == 2, (
        f"expected @retry to re-invoke the provider after a transient failure, "
        f"but the provider was called {call_count} time(s)"
    )
    assert result == [[0.1, 0.2, 0.3]]


@pytest.mark.asyncio
async def test_cloud_embedding_retries_on_vertex_429() -> None:
    """
    Reproduces the exact Vertex 429 RESOURCE_EXHAUSTED error path (a
    google.genai.errors.ClientError that is neither httpx.HTTPStatusError nor
    openai.AuthenticationError) and asserts embed() retries after such a
    failure. This is the production failure mode driving these retries.
    """
    from google.genai.errors import ClientError

    vertex_429_message = (
        "429 RESOURCE_EXHAUSTED. {'error': {'code': 429, "
        "'message': 'Resource exhausted. Please try again later. Please refer "
        "to https://cloud.google.com/vertex-ai/generative-ai/docs/error-code-429 "
        "for more details.', 'status': 'RESOURCE_EXHAUSTED'}}"
    )

    call_count = 0

    async def flaky_embed_vertex(
        self: CloudEmbedding,  # noqa: ARG001
        texts: list[str],
        model: str | None,  # noqa: ARG001
        embedding_type: str,  # noqa: ARG001
        reduced_dimension: int | None,  # noqa: ARG001
    ) -> list[list[float]]:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # google.genai.errors.ClientError requires (code, response_json, response)
            raise ClientError(429, {"message": vertex_429_message})
        return [[0.1, 0.2, 0.3] for _ in texts]

    with (
        patch.object(cast(Any, CloudEmbedding.embed).retry, "wait", wait_none()),
        patch.object(
            CloudEmbedding,
            CloudEmbedding._embed_vertex.__name__,
            new=flaky_embed_vertex,
        ),
    ):
        async with CloudEmbedding(
            '{"project_id": "fake", "type": "service_account"}',
            EmbeddingProvider.GOOGLE,
        ) as embedding:
            result = await embedding.embed(
                texts=["test"],
                text_type=EmbedTextType.PASSAGE,
            )

    assert call_count == 2, (
        f"expected @retry to re-invoke after a Vertex 429, "
        f"but the provider was called {call_count} time(s)"
    )
    assert result == [[0.1, 0.2, 0.3]]


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


def test_from_db_model_sends_the_stored_dim_for_self_hosted_models() -> None:
    """The model server uses it to keep the legacy load for a custom model that
    has a registry name (e.g. voyage-4-nano stored with 1024 dims)."""
    search_settings = MagicMock()
    search_settings.model_name = "voyageai/voyage-4-nano"
    search_settings.model_dim = 1024
    search_settings.normalize = True
    search_settings.query_prefix = None
    search_settings.passage_prefix = None
    search_settings.api_key = None
    search_settings.api_url = None
    search_settings.api_version = None
    search_settings.deployment_name = None
    search_settings.reduced_dimension = None
    search_settings.provider_type = None
    with patch(f"{_SEARCH_NLP_MODULE}.get_tokenizer", return_value=MagicMock()):
        model = EmbeddingModel.from_db_model(
            search_settings=search_settings, server_host="localhost", server_port=9000
        )

    with patch.object(
        EmbeddingModel,
        "_make_model_server_request",
        side_effect=_fake_model_server_call,
    ) as request:
        model.encode(texts=[_text_for_idx(0)], text_type=EmbedTextType.QUERY)

    assert request.call_args.args[0].expected_dim == 1024


def test_cloud_request_has_no_stored_dim() -> None:
    model = _make_cloud_embedding_model()
    model.model_dim = 1536

    with patch.object(
        EmbeddingModel,
        "_make_direct_api_call",
        new=AsyncMock(side_effect=_fake_direct_api_call),
    ) as request:
        model.encode(texts=[_text_for_idx(0)], text_type=EmbedTextType.QUERY)

    assert request.call_args.args[0].expected_dim is None


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


# ------------------------------------------------------------------------------
# Vertex AI through the real google-genai SDK
#
# These tests replace only the HTTP transport (httpx.MockTransport) and the
# credentials. The SDK builds the real requests and picks the real endpoint, so
# a call that the SDK refuses (more than one content for an :embedContent
# model) fails here the same way as in production.
# ------------------------------------------------------------------------------

_VERTEX_SERVICE_ACCOUNT_JSON = (
    '{"project_id": "fake-project", "type": "service_account"}'
)
_VERTEX_MODEL_PATH = (
    "/v1beta1/projects/fake-project/locations/global/publishers/google/models"
)
_VERTEX_ENV_VARS = (
    "GOOGLE_CLOUD_LOCATION",
    "GOOGLE_CLOUD_PROJECT",
    "GOOGLE_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_GENAI_USE_VERTEXAI",
)
_VERTEX_TEST_DIM = 4
_VERTEX_ERRORS: dict[int, tuple[str, str]] = {
    400: ("INVALID_ARGUMENT", "Request contains an invalid argument."),
    403: ("PERMISSION_DENIED", "Permission 'aiplatform.endpoints.predict' denied."),
    404: ("NOT_FOUND", "Publisher model not found."),
    429: ("RESOURCE_EXHAUSTED", "Resource exhausted. Please try again later."),
    503: ("UNAVAILABLE", "The service is currently unavailable."),
}


def _doc_texts(count: int) -> list[str]:
    return [f"doc {i}" for i in range(count)]


def _index_in_text(text: str) -> int:
    # Works for "doc 7" and for Gemini templates such as "title: none | text: doc 7".
    return int(text.rsplit(" ", 1)[-1])


def _vertex_vector(index: int) -> list[float]:
    # The fake server puts the text index first, so tests can check order.
    return [float(index)] + [0.0] * (_VERTEX_TEST_DIM - 1)


def _vertex_error_response(code: int) -> httpx.Response:
    status, message = _VERTEX_ERRORS[code]
    return httpx.Response(
        code, json={"error": {"code": code, "message": message, "status": status}}
    )


class _FakeVertexServer:
    """Answers Vertex :embedContent and :predict requests."""

    def __init__(self) -> None:
        self.requests: list[tuple[str, dict[str, Any]]] = []
        self.client_kwargs: list[dict[str, Any]] = []
        self.in_flight = 0
        self.max_in_flight = 0
        # Response delay for each text index, so that calls finish out of order.
        self.delay_for_index: Callable[[int], float] = lambda _index: 0.0
        # Text -> status codes to send (one per attempt) before a success.
        self.transient_errors: dict[str, list[int]] = {}
        # Text -> status code to send on every attempt.
        self.permanent_errors: dict[str, int] = {}

    def embed_content_texts(self) -> list[str]:
        return [
            body["content"]["parts"][0]["text"]
            for path, body in self.requests
            if path.endswith(":embedContent")
        ]

    async def handle(self, request: httpx.Request) -> httpx.Response:
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            body = json.loads(request.content)
            self.requests.append((request.url.path, body))
            if request.url.path.endswith(":embedContent"):
                text = body["content"]["parts"][0]["text"]
                await asyncio.sleep(self.delay_for_index(_index_in_text(text)))
                pending = self.transient_errors.get(text)
                if pending:
                    return _vertex_error_response(pending.pop(0))
                if text in self.permanent_errors:
                    return _vertex_error_response(self.permanent_errors[text])
                return httpx.Response(
                    200,
                    json={
                        "embedding": {"values": _vertex_vector(_index_in_text(text))}
                    },
                )
            if request.url.path.endswith(":predict"):
                predictions = [
                    {
                        "embeddings": {
                            "values": _vertex_vector(
                                _index_in_text(instance["content"])
                            ),
                            "statistics": {"token_count": 1, "truncated": False},
                        }
                    }
                    for instance in body["instances"]
                ]
                return httpx.Response(200, json={"predictions": predictions})
            return _vertex_error_response(404)
        finally:
            self.in_flight -= 1


@pytest.fixture
def fake_vertex(monkeypatch: pytest.MonkeyPatch) -> Iterator[_FakeVertexServer]:
    """Sends the requests of every genai.Client that Onyx creates to a fake server."""
    for env_var in _VERTEX_ENV_VARS:
        monkeypatch.delenv(env_var, raising=False)

    server = _FakeVertexServer()
    real_client_cls = genai.Client

    def _client_factory(**kwargs: Any) -> genai.Client:
        server.client_kwargs.append(dict(kwargs))
        http_options = kwargs.pop("http_options", None) or genai_types.HttpOptions()
        update: dict[str, Any] = {
            "httpx_async_client": httpx.AsyncClient(
                transport=httpx.MockTransport(server.handle)
            )
        }
        if http_options.retry_options is not None:
            # Keep the attempts and status codes under test. Only shorten the waits.
            update["retry_options"] = http_options.retry_options.model_copy(
                update={"initial_delay": 0.001, "max_delay": 0.001, "jitter": 0.001}
            )
        return real_client_cls(
            **kwargs, http_options=http_options.model_copy(update=update)
        )

    with (
        patch("google.genai.Client", new=_client_factory),
        patch(
            "google.oauth2.service_account.Credentials.from_service_account_info",
            return_value=TokenCredentials(token="fake-token"),
        ),
    ):
        yield server


@pytest.mark.parametrize(
    "model_name",
    [
        "gemini-embedding-2",
        "gemini-embedding-2-preview",
        "gemini-embedding-001",
        "text-embedding-005",
        "text-embedding-004",
        "text-multilingual-embedding-002",
        "textembedding-gecko@003",
        "multimodalembedding@001",
        "publishers/google/models/gemini-embedding-2",
        "publishers/google/models/gemini-embedding-001",
        "Gemini-Embedding-2",
        "gemini-embedding-001 ",
        "intfloat/multilingual-e5-large-instruct-maas",
        "",
    ],
)
def test_vertex_requires_single_content_matches_sdk(model_name: str) -> None:
    """The SDK picks :embedContent (one content per call) with this same rule."""
    assert _vertex_requires_single_content(
        model_name
    ) == genai_transformers.t_is_vertex_embed_content_model(model_name)


def test_vertex_requires_single_content_for_registry_models() -> None:
    assert _vertex_requires_single_content("gemini-embedding-2")
    assert _vertex_requires_single_content("gemini-embedding-2-preview")
    assert not _vertex_requires_single_content("gemini-embedding-001")
    assert not _vertex_requires_single_content("text-embedding-005")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("text_type", "reduced_dimension", "template", "expected_config"),
    [
        (
            EmbedTextType.PASSAGE,
            None,
            "title: none | text: {text}",
            {"autoTruncate": True},
        ),
        (
            EmbedTextType.QUERY,
            768,
            "task: search result | query: {text}",
            {"autoTruncate": True, "outputDimensionality": 768},
        ),
    ],
)
async def test_vertex_gemini_embedding_2_sends_one_content_per_call(
    fake_vertex: _FakeVertexServer,
    text_type: EmbedTextType,
    reduced_dimension: int | None,
    template: str,
    expected_config: dict[str, Any],
) -> None:
    """12 texts become 12 single-content :embedContent calls, in text order."""
    texts = _doc_texts(12)

    with patch(f"{_SEARCH_NLP_MODULE}.VERTEXAI_EMBED_CONTENT_CONCURRENCY", 1):
        async with CloudEmbedding(
            _VERTEX_SERVICE_ACCOUNT_JSON, EmbeddingProvider.GOOGLE
        ) as embedding:
            result = await embedding.embed(
                texts=texts,
                text_type=text_type,
                model_name="gemini-embedding-2",
                reduced_dimension=reduced_dimension,
            )

    assert result == [_vertex_vector(i) for i in range(12)]
    assert fake_vertex.requests == [
        (
            f"{_VERTEX_MODEL_PATH}/gemini-embedding-2:embedContent",
            {
                "content": {"parts": [{"text": template.format(text=text)}]},
                "embedContentConfig": expected_config,
            },
        )
        for text in texts
    ]


@pytest.mark.asyncio
async def test_vertex_single_content_calls_are_bounded_and_keep_order(
    fake_vertex: _FakeVertexServer,
) -> None:
    texts = _doc_texts(12)
    # Later texts answer faster, so calls finish out of order.
    fake_vertex.delay_for_index = lambda index: 0.002 * (12 - index)

    with patch(f"{_SEARCH_NLP_MODULE}.VERTEXAI_EMBED_CONTENT_CONCURRENCY", 4):
        async with CloudEmbedding(
            _VERTEX_SERVICE_ACCOUNT_JSON, EmbeddingProvider.GOOGLE
        ) as embedding:
            result = await embedding.embed(
                texts=texts,
                text_type=EmbedTextType.PASSAGE,
                model_name="gemini-embedding-2",
            )

    assert result == [_vertex_vector(i) for i in range(12)]
    assert sorted(fake_vertex.embed_content_texts()) == sorted(
        f"title: none | text: {text}" for text in texts
    )
    assert len(fake_vertex.requests) == 12
    assert 2 <= fake_vertex.max_in_flight <= 4


@pytest.mark.asyncio
async def test_vertex_single_content_keeps_the_window_loop(
    fake_vertex: _FakeVertexServer,
) -> None:
    """A window starts only after all calls of the previous window are done."""
    with (
        patch(f"{_SEARCH_NLP_MODULE}.VERTEXAI_EMBEDDING_LOCAL_BATCH_SIZE", 5),
        patch(f"{_SEARCH_NLP_MODULE}.VERTEXAI_EMBED_CONTENT_CONCURRENCY", 4),
    ):
        async with CloudEmbedding(
            _VERTEX_SERVICE_ACCOUNT_JSON, EmbeddingProvider.GOOGLE
        ) as embedding:
            result = await embedding.embed(
                texts=_doc_texts(12),
                text_type=EmbedTextType.PASSAGE,
                model_name="gemini-embedding-2",
            )

    assert result == [_vertex_vector(i) for i in range(12)]
    sent = [_index_in_text(text) for text in fake_vertex.embed_content_texts()]
    assert sorted(sent[:5]) == [0, 1, 2, 3, 4]
    assert sorted(sent[5:10]) == [5, 6, 7, 8, 9]
    assert sorted(sent[10:]) == [10, 11]
    assert fake_vertex.max_in_flight <= 4


def test_vertex_gemini_embedding_2_encode_indexing_path(
    fake_vertex: _FakeVertexServer,
) -> None:
    """EmbeddingModel.encode (the indexing path) with 12 passages."""
    with patch(f"{_SEARCH_NLP_MODULE}.get_tokenizer", return_value=MagicMock()):
        model = EmbeddingModel(
            server_host="localhost",
            server_port=9000,
            model_name="gemini-embedding-2",
            normalize=False,
            query_prefix=None,
            passage_prefix=None,
            api_key=_VERTEX_SERVICE_ACCOUNT_JSON,
            api_url=None,
            provider_type=EmbeddingProvider.GOOGLE,
        )

    result = model.encode(texts=_doc_texts(12), text_type=EmbedTextType.PASSAGE)

    assert result == [_vertex_vector(i) for i in range(12)]
    assert len(fake_vertex.embed_content_texts()) == 12
    assert all(
        path.endswith("/gemini-embedding-2:embedContent")
        for path, _body in fake_vertex.requests
    )


@pytest.mark.asyncio
async def test_vertex_client_options_only_for_single_content_models(
    fake_vertex: _FakeVertexServer,
) -> None:
    async with CloudEmbedding(
        _VERTEX_SERVICE_ACCOUNT_JSON, EmbeddingProvider.GOOGLE
    ) as embedding:
        for model_name in ("gemini-embedding-2", "text-embedding-005"):
            await embedding.embed(
                texts=["doc 0"], text_type=EmbedTextType.QUERY, model_name=model_name
            )
        timeout_s = embedding.timeout

    single_content_kwargs, predict_kwargs = fake_vertex.client_kwargs
    http_options = single_content_kwargs["http_options"]
    assert isinstance(http_options, genai_types.HttpOptions)
    assert http_options.timeout == timeout_s * 1000
    assert http_options.retry_options == genai_types.HttpRetryOptions(
        attempts=5, http_status_codes=[408, 429, 500, 502, 503, 504]
    )
    # :predict models keep the old client call and the SDK defaults.
    assert set(predict_kwargs) == {"vertexai", "project", "location", "credentials"}


@pytest.mark.asyncio
async def test_vertex_single_content_retries_transient_errors_per_call(
    fake_vertex: _FakeVertexServer,
) -> None:
    """The SDK retries one failed text; the other texts are not sent again."""
    fake_vertex.transient_errors = {"title: none | text: doc 3": [429, 503]}

    async with CloudEmbedding(
        _VERTEX_SERVICE_ACCOUNT_JSON, EmbeddingProvider.GOOGLE
    ) as embedding:
        result = await embedding.embed(
            texts=_doc_texts(12),
            text_type=EmbedTextType.PASSAGE,
            model_name="gemini-embedding-2",
        )

    assert result == [_vertex_vector(i) for i in range(12)]
    assert len(fake_vertex.requests) == 12 + 2


@pytest.mark.asyncio
async def test_vertex_single_content_permission_error_is_authentication_error(
    fake_vertex: _FakeVertexServer,
) -> None:
    """A failed call is not hidden inside an ExceptionGroup."""
    fake_vertex.permanent_errors = {"title: none | text: doc 5": 403}

    with patch.object(cast(Any, CloudEmbedding.embed).retry, "wait", wait_none()):
        async with CloudEmbedding(
            _VERTEX_SERVICE_ACCOUNT_JSON, EmbeddingProvider.GOOGLE
        ) as embedding:
            with pytest.raises(AuthenticationError):
                await embedding.embed(
                    texts=_doc_texts(12),
                    text_type=EmbedTextType.PASSAGE,
                    model_name="gemini-embedding-2",
                )


@pytest.mark.asyncio
async def test_vertex_single_content_error_keeps_provider_message(
    fake_vertex: _FakeVertexServer,
) -> None:
    fake_vertex.permanent_errors = {"title: none | text: doc 5": 400}

    with patch.object(cast(Any, CloudEmbedding.embed).retry, "wait", wait_none()):
        async with CloudEmbedding(
            _VERTEX_SERVICE_ACCOUNT_JSON, EmbeddingProvider.GOOGLE
        ) as embedding:
            with pytest.raises(RuntimeError, match="INVALID_ARGUMENT") as exc_info:
                await embedding.embed(
                    texts=_doc_texts(12),
                    text_type=EmbedTextType.PASSAGE,
                    model_name="gemini-embedding-2",
                )

    assert "TaskGroup" not in str(exc_info.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("model_name", ["gemini-embedding-001", "text-embedding-005"])
async def test_vertex_predict_models_still_batch(
    fake_vertex: _FakeVertexServer, model_name: str
) -> None:
    """:predict models still send up to 50 texts per call, one call at a time."""
    texts = _doc_texts(60)

    with patch(f"{_SEARCH_NLP_MODULE}.VERTEXAI_EMBEDDING_LOCAL_BATCH_SIZE", 50):
        async with CloudEmbedding(
            _VERTEX_SERVICE_ACCOUNT_JSON, EmbeddingProvider.GOOGLE
        ) as embedding:
            result = await embedding.embed(
                texts=texts,
                text_type=EmbedTextType.PASSAGE,
                model_name=model_name,
            )

    assert result == [_vertex_vector(i) for i in range(60)]
    predict_path = f"{_VERTEX_MODEL_PATH}/{model_name}:predict"
    assert fake_vertex.requests == [
        (
            predict_path,
            {
                "instances": [
                    {"content": text, "task_type": "RETRIEVAL_DOCUMENT"}
                    for text in window
                ],
                "parameters": {"autoTruncate": True},
            },
        )
        for window in (texts[:50], texts[50:])
    ]
    assert fake_vertex.max_in_flight == 1


# ------------------------------------------------------------------------------
# Cohere through the real cohere SDK
# ------------------------------------------------------------------------------


class _FakeCohereServer:
    """Answers Cohere v1 /embed requests like the API does for embedding_types."""

    def __init__(self, dim: int) -> None:
        self.dim = dim
        self.requests: list[tuple[str, dict[str, Any]]] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.requests.append((request.url.path, body))
        vectors = [
            [float(_index_in_text(text))] + [0.0] * (self.dim - 1)
            for text in body["texts"]
        ]
        return httpx.Response(
            200,
            json={
                "id": "fake",
                "response_type": "embeddings_by_type",
                "embeddings": {"float": vectors},
                "texts": body["texts"],
                "meta": {"api_version": {"version": "1"}},
            },
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("model_name", "dim"),
    [
        ("embed-v5.0-pro", 2048),
        ("embed-v5.0-fast", 2048),
        ("embed-v4.0", 1536),
        ("embed-english-v3.0", 1024),
        ("embed-english-light-v3.0", 384),
    ],
)
@pytest.mark.parametrize(
    ("text_type", "input_type"),
    [
        (EmbedTextType.PASSAGE, "search_document"),
        (EmbedTextType.QUERY, "search_query"),
    ],
)
async def test_cohere_embed_uses_v1_embed_for_all_models(
    model_name: str, dim: int, text_type: EmbedTextType, input_type: str
) -> None:
    """v5 uses the same v1 /embed call as v3 and v4; 130 texts become 96 + 34."""
    server = _FakeCohereServer(dim)
    texts = _doc_texts(130)

    def _client_factory(api_key: str) -> RealCohereAsyncClient:
        return RealCohereAsyncClient(
            api_key=api_key,
            httpx_client=httpx.AsyncClient(
                transport=httpx.MockTransport(server.handle)
            ),
        )

    with patch(f"{_SEARCH_NLP_MODULE}.CohereAsyncClient", new=_client_factory):
        async with CloudEmbedding("fake-key", EmbeddingProvider.COHERE) as embedding:
            result = await embedding.embed(
                texts=texts, text_type=text_type, model_name=model_name
            )

    assert len(result) == 130
    assert all(len(vector) == dim for vector in result)
    assert [vector[0] for vector in result] == [float(i) for i in range(130)]
    request_body = {
        "model": model_name,
        "input_type": input_type,
        "truncate": "END",
        "embedding_types": ["float"],
    }
    assert server.requests == [
        ("/v1/embed", {**request_body, "texts": texts[:96]}),
        ("/v1/embed", {**request_body, "texts": texts[96:]}),
    ]
