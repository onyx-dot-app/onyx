import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from google.auth.credentials import Credentials
from google.genai import errors as genai_errors
from google.genai import types as genai_types

from onyx.natural_language_processing.embedding_auth import build_embedding_auth
from onyx.natural_language_processing.embedding_providers.vertex_batching import (
    vertex_batches,
)
from onyx.natural_language_processing.embedding_request_policy import (
    EmbeddingRequestPolicy,
    EmbeddingRetryBackoff,
)
from onyx.natural_language_processing.search_nlp_models import CloudEmbedding
from onyx.natural_language_processing.vertex_auth import VertexEmbeddingConfig
from shared_configs.enums import EmbeddingProvider

_BATCHING = "onyx.natural_language_processing.embedding_providers.vertex_batching"


def _sizes(batches: list[list[str]]) -> list[int]:
    return [len(batch) for batch in batches]


def test_gemini_embedding_2_sends_one_text_per_request() -> None:
    assert _sizes(vertex_batches(["a", "b", "c"], "gemini-embedding-2")) == [1, 1, 1]


def test_text_embedding_batches_stay_under_the_token_limit() -> None:
    # About 2,000 estimated tokens each, so ten fit in 20,000.
    texts = ["x" * 5000] * 25
    assert _sizes(vertex_batches(texts, "text-embedding-005")) == [10, 10, 5]


def test_truncated_texts_count_at_most_the_truncation_length() -> None:
    texts = ["x" * 100_000] * 30
    assert _sizes(vertex_batches(texts, "text-multilingual-embedding-002")) == [
        9,
        9,
        9,
        3,
    ]


@pytest.mark.parametrize("model", ["gemini-embedding-001", "text-embedding-005"])
def test_batches_hold_at_most_the_configured_text_count(model: str) -> None:
    with patch(f"{_BATCHING}.VERTEXAI_EMBEDDING_LOCAL_BATCH_SIZE", 4):
        assert _sizes(vertex_batches(["a"] * 10, model)) == [4, 4, 2]


def test_gemini_embedding_001_has_no_token_limit() -> None:
    with patch(f"{_BATCHING}.VERTEXAI_EMBEDDING_LOCAL_BATCH_SIZE", 250):
        texts = ["x" * 5000] * 25
        assert _sizes(vertex_batches(texts, "gemini-embedding-001")) == [25]


def _token_limit_error() -> genai_errors.ClientError:
    message = (
        "Unable to submit request because the input token count is 30000 "
        "but the model supports up to 20000."
    )
    return genai_errors.ClientError(
        400,
        {"error": {"code": 400, "message": message, "status": "INVALID_ARGUMENT"}},
    )


def _embed(model: str, texts: list[str], client: MagicMock) -> list[list[float]]:
    auth = build_embedding_auth(
        EmbeddingProvider.GOOGLE,
        None,
        VertexEmbeddingConfig(
            auth_method="workload_identity", project_id="p", location="us-central1"
        ),
    )
    policy = EmbeddingRequestPolicy(
        retry_backoff=EmbeddingRetryBackoff(scale_seconds=0, max_seconds=0),
        retry_tries=1,
    )
    embedding = CloudEmbedding(
        api_key=None, provider=EmbeddingProvider.GOOGLE, auth=auth, policy=policy
    )
    client.aio.aclose = AsyncMock()
    with (
        patch("google.auth.default", return_value=(MagicMock(spec=Credentials), "p")),
        patch("google.genai.Client", return_value=client),
    ):
        return asyncio.run(
            embedding._embed_vertex(
                texts=texts,
                model=model,
                embedding_type="RETRIEVAL_DOCUMENT",
                reduced_dimension=None,
            )
        )


def _response(contents: list[genai_types.Content]) -> MagicMock:
    response = MagicMock()
    response.embeddings = [
        MagicMock(values=[float(len((content.parts or [])[0].text or ""))])
        for content in contents
    ]
    return response


def test_batch_over_the_token_limit_is_split() -> None:
    sizes: list[int] = []

    async def embed_content(
        contents: list[genai_types.Content], **_kwargs: object
    ) -> MagicMock:
        sizes.append(len(contents))
        if len(contents) > 2:
            raise _token_limit_error()
        return _response(contents)

    client = MagicMock()
    client.aio.models.embed_content = embed_content
    texts = ["a", "bb", "ccc", "dddd", "eeeee"]

    assert _embed("text-embedding-005", texts, client) == [
        [1.0],
        [2.0],
        [3.0],
        [4.0],
        [5.0],
    ]
    assert sorted(sizes) == [1, 2, 2, 3, 5]


def test_multi_input_batches_are_sent_in_parallel() -> None:
    both_sent = asyncio.Event()
    in_flight = 0

    async def embed_content(
        contents: list[genai_types.Content], **_kwargs: object
    ) -> MagicMock:
        nonlocal in_flight
        in_flight += 1
        if in_flight == 2:
            both_sent.set()
        await asyncio.wait_for(both_sent.wait(), timeout=5)
        return _response(contents)

    client = MagicMock()
    client.aio.models.embed_content = embed_content
    with patch(f"{_BATCHING}.VERTEXAI_EMBEDDING_LOCAL_BATCH_SIZE", 1):
        assert _embed("gemini-embedding-001", ["a", "bb"], client) == [[1.0], [2.0]]
