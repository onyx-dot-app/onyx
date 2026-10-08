"""Requests the Bifrost embedding provider sends to the gateway's /v1/embeddings."""

import json
from typing import Any, cast
from unittest.mock import patch

import httpx
import pytest
from tenacity import wait_none

from onyx.natural_language_processing.embedding_auth import (
    ApiKeyEmbeddingAuth,
    build_embedding_auth,
)
from onyx.natural_language_processing.search_nlp_models import CloudEmbedding
from onyx.natural_language_processing.utils import (
    TiktokenTokenizer,
    _try_initialize_tokenizer,
)
from shared_configs.enums import EmbeddingProvider, EmbedTextType


class _FakeGateway:
    """Records each request and answers like an OpenAI-compatible /v1/embeddings."""

    def __init__(self, dimension: int = 3, status_code: int = 200) -> None:
        self.dimension = dimension
        self.status_code = status_code
        self.requests: list[httpx.Request] = []

    @property
    def payloads(self) -> list[dict[str, Any]]:
        return [json.loads(request.content) for request in self.requests]

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.status_code != 200:
            return httpx.Response(
                self.status_code, json={"error": {"message": "not an embedding model"}}
            )
        inputs = json.loads(request.content)["input"]
        # Reverse the order to prove the client sorts by `index`.
        data = [
            {"index": i, "embedding": [float(i)] * self.dimension}
            for i in range(len(inputs))
        ][::-1]
        return httpx.Response(200, json={"object": "list", "data": data})


def _bifrost(
    gateway: _FakeGateway, api_url: str, api_key: str | None
) -> CloudEmbedding:
    embedding = CloudEmbedding(
        api_key=api_key,
        provider=EmbeddingProvider.BIFROST,
        api_url=api_url,
        auth=build_embedding_auth(EmbeddingProvider.BIFROST, api_key),
    )
    embedding.http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(gateway.handler)
    )
    return embedding


@pytest.mark.asyncio
async def test_openai_model_omits_task_type_and_sends_dimensions() -> None:
    gateway = _FakeGateway()
    async with _bifrost(gateway, "https://bifrost.example/", "sk-bf-test") as embedding:
        result = await embedding.embed(
            texts=["a", "b"],
            text_type=EmbedTextType.QUERY,
            model_name="openai/text-embedding-3-large",
            reduced_dimension=256,
        )

    assert result == [[0.0] * 3, [1.0] * 3]
    (request,) = gateway.requests
    assert str(request.url) == "https://bifrost.example/v1/embeddings"
    assert request.headers["Authorization"] == "Bearer sk-bf-test"
    assert gateway.payloads[0] == {
        "model": "openai/text-embedding-3-large",
        "input": ["a", "b"],
        "dimensions": 256,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("text_type", "task_type"),
    [
        (EmbedTextType.QUERY, "RETRIEVAL_QUERY"),
        (EmbedTextType.PASSAGE, "RETRIEVAL_DOCUMENT"),
    ],
)
async def test_gemini_model_sends_task_type_one_input_per_request(
    text_type: EmbedTextType, task_type: str
) -> None:
    gateway = _FakeGateway()
    async with _bifrost(gateway, "https://bifrost.example/v1", None) as embedding:
        result = await embedding.embed(
            texts=["a", "b", "c"],
            text_type=text_type,
            model_name="gemini/gemini-embedding-001",
        )

    assert len(result) == 3
    assert [str(r.url) for r in gateway.requests] == [
        "https://bifrost.example/v1/embeddings"
    ] * 3
    assert [p["input"] for p in gateway.payloads] == [["a"], ["b"], ["c"]]
    assert all(p["task_type"] == task_type for p in gateway.payloads)
    assert all(p["taskType"] == task_type for p in gateway.payloads)
    assert all("Authorization" not in r.headers for r in gateway.requests)


@pytest.mark.asyncio
async def test_gemini_embedding_2_uses_instruction_text_one_input_per_request() -> None:
    gateway = _FakeGateway()
    async with _bifrost(gateway, "https://bifrost.example", None) as embedding:
        await embedding.embed(
            texts=["q1", "q2"],
            text_type=EmbedTextType.QUERY,
            model_name="vertex/gemini-embedding-2",
        )

    assert gateway.payloads == [
        {
            "model": "vertex/gemini-embedding-2",
            "input": ["task: search result | query: q1"],
        },
        {
            "model": "vertex/gemini-embedding-2",
            "input": ["task: search result | query: q2"],
        },
    ]


@pytest.mark.asyncio
async def test_gateway_rejection_raises_after_retries() -> None:
    gateway = _FakeGateway(status_code=400)
    with patch.object(cast(Any, CloudEmbedding.embed).retry, "wait", wait_none()):
        async with _bifrost(gateway, "https://bifrost.example", None) as embedding:
            with pytest.raises(RuntimeError, match="Status 400"):
                await embedding.embed(
                    texts=["a"],
                    text_type=EmbedTextType.QUERY,
                    model_name="openai/gpt-5-mini",
                )


def test_bifrost_auth_allows_a_missing_key() -> None:
    auth = build_embedding_auth(EmbeddingProvider.BIFROST, None)
    assert isinstance(auth, ApiKeyEmbeddingAuth)
    auth.validate_credentials()
    assert auth.resolve_credentials().api_key.get_secret_value() == ""


def test_tokenizer_strips_the_gateway_provider_prefix() -> None:
    def encoding_for_model(model_name: str) -> object:
        if "/" in model_name:
            raise KeyError(model_name)
        return object()

    model_name = "openai/bifrost-tokenizer-test"
    with (
        patch("tiktoken.encoding_for_model", side_effect=encoding_for_model),
        patch.dict(TiktokenTokenizer._instances, clear=True),
    ):
        tokenizer = _try_initialize_tokenizer(model_name, EmbeddingProvider.BIFROST)

    assert isinstance(tokenizer, TiktokenTokenizer)
