"""Requests the Bifrost embedding provider sends to the gateway's /v1/embeddings."""

import json
from collections.abc import Callable, Iterator
from typing import Any, cast
from unittest.mock import patch

import httpx
import pytest
from tenacity import stop_after_attempt, wait_none

from onyx.natural_language_processing.embedding_auth import (
    ApiKeyEmbeddingAuth,
    build_embedding_auth,
)
from onyx.natural_language_processing.exceptions import (
    EmbeddingRequestFailedError,
    EmbeddingRequestRejectedError,
)
from onyx.natural_language_processing.search_nlp_models import (
    AuthenticationError,
    CloudEmbedding,
)
from onyx.natural_language_processing.utils import (
    TiktokenTokenizer,
    _try_initialize_tokenizer,
)
from shared_configs.enums import EmbeddingProvider, EmbedTextType

_MODULE = "onyx.natural_language_processing.search_nlp_models"


class _FakeGateway:
    """Records each request and answers like an OpenAI-compatible /v1/embeddings.

    `respond` can override the reply for a request; return None to answer normally.
    """

    def __init__(
        self,
        respond: Callable[[dict[str, Any]], httpx.Response | None] | None = None,
        drop_last: bool = False,
    ) -> None:
        self.respond = respond
        self.drop_last = drop_last
        self.requests: list[httpx.Request] = []

    @property
    def payloads(self) -> list[dict[str, Any]]:
        return [json.loads(request.content) for request in self.requests]

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        payload = json.loads(request.content)
        if self.respond is not None and (override := self.respond(payload)):
            return override
        # Embed the text length so each result can be matched to its input.
        data = [
            {"index": i, "embedding": [float(len(text)), 0.0, 0.0]}
            for i, text in enumerate(payload["input"])
        ]
        if self.drop_last:
            data = data[:-1]
        # Reverse the order to prove the client sorts by `index`.
        return httpx.Response(200, json={"object": "list", "data": data[::-1]})


def _bifrost(
    gateway: _FakeGateway, api_url: str, api_key: str | None = None
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


@pytest.fixture(autouse=True)
def _no_retry_waits() -> Iterator[None]:
    with (
        patch(f"{_MODULE}._BIFROST_RETRY_WAIT", wait_none()),
        patch.object(cast(Any, CloudEmbedding.embed).retry, "wait", wait_none()),
    ):
        yield


@pytest.mark.asyncio
async def test_openai_model_omits_task_type_and_sends_dimensions() -> None:
    gateway = _FakeGateway()
    async with _bifrost(gateway, "https://bifrost.example/", "sk-bf-test") as embedding:
        result = await embedding.embed(
            texts=["a", "bb"],
            text_type=EmbedTextType.QUERY,
            model_name="openai/text-embedding-3-large",
            reduced_dimension=256,
        )

    assert result == [[1.0, 0.0, 0.0], [2.0, 0.0, 0.0]]
    (request,) = gateway.requests
    assert str(request.url) == "https://bifrost.example/v1/embeddings"
    assert request.headers["Authorization"] == "Bearer sk-bf-test"
    assert gateway.payloads[0] == {
        "model": "openai/text-embedding-3-large",
        "input": ["a", "bb"],
        "dimensions": 256,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "api_url",
    [
        "https://bifrost.example",
        "https://bifrost.example/v1",
        "https://bifrost.example/v1/",
        "https://bifrost.example/v1/embeddings",
    ],
)
async def test_base_url_forms_reach_the_embeddings_endpoint(api_url: str) -> None:
    gateway = _FakeGateway()
    async with _bifrost(gateway, api_url) as embedding:
        await embedding.embed(
            texts=["a"],
            text_type=EmbedTextType.QUERY,
            model_name="openai/text-embedding-3-small",
        )

    assert str(gateway.requests[0].url) == "https://bifrost.example/v1/embeddings"


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
    async with _bifrost(gateway, "https://bifrost.example/v1") as embedding:
        result = await embedding.embed(
            texts=["a", "bb", "ccc"],
            text_type=text_type,
            model_name="gemini/gemini-embedding-001",
        )

    # Results keep the input order although requests run concurrently.
    assert [vector[0] for vector in result] == [1.0, 2.0, 3.0]
    assert sorted(p["input"][0] for p in gateway.payloads) == ["a", "bb", "ccc"]
    assert all(len(p["input"]) == 1 for p in gateway.payloads)
    assert all(p["task_type"] == task_type for p in gateway.payloads)
    assert all(p["taskType"] == task_type for p in gateway.payloads)
    assert all("Authorization" not in r.headers for r in gateway.requests)


@pytest.mark.asyncio
async def test_vertex_model_sends_task_type_without_the_gemini_alias() -> None:
    gateway = _FakeGateway()
    async with _bifrost(gateway, "https://bifrost.example") as embedding:
        await embedding.embed(
            texts=["a"],
            text_type=EmbedTextType.PASSAGE,
            model_name="vertex/text-embedding-005",
        )

    assert gateway.payloads == [
        {
            "model": "vertex/text-embedding-005",
            "input": ["a"],
            "task_type": "RETRIEVAL_DOCUMENT",
        }
    ]


@pytest.mark.asyncio
async def test_gemini_embedding_2_uses_instruction_text_and_no_task_type() -> None:
    gateway = _FakeGateway()
    async with _bifrost(gateway, "https://bifrost.example") as embedding:
        await embedding.embed(
            texts=["q1", "q2"],
            text_type=EmbedTextType.QUERY,
            model_name="vertex/gemini-embedding-2",
        )

    assert sorted(p["input"][0] for p in gateway.payloads) == [
        "task: search result | query: q1",
        "task: search result | query: q2",
    ]
    assert all(set(p) == {"model", "input"} for p in gateway.payloads)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("model_name", "texts_per_request"),
    [
        ("openai/text-embedding-3-small", 200),
        ("azure/text-embedding-3-small", 200),
        ("cohere/embed-english-v3.0", 96),
        ("mistral/mistral-embed", 96),
    ],
)
async def test_batch_size_follows_the_upstream_provider(
    model_name: str, texts_per_request: int
) -> None:
    gateway = _FakeGateway()
    async with _bifrost(gateway, "https://bifrost.example") as embedding:
        result = await embedding.embed(
            texts=[f"t{i}" for i in range(200)],
            text_type=EmbedTextType.PASSAGE,
            model_name=model_name,
        )

    assert len(result) == 200
    assert max(len(p["input"]) for p in gateway.payloads) == texts_per_request


@pytest.mark.asyncio
async def test_model_rejection_is_raised_once_with_the_gateway_reason() -> None:
    def reject(_: dict[str, Any]) -> httpx.Response:
        return httpx.Response(
            404,
            json={
                "is_bifrost_error": False,
                "status_code": 404,
                "error": {
                    "message": "The model `gpt-5-mini` does not support embeddings."
                },
            },
        )

    gateway = _FakeGateway(respond=reject)
    async with _bifrost(gateway, "https://bifrost.example") as embedding:
        with pytest.raises(
            EmbeddingRequestRejectedError, match="does not support embeddings"
        ):
            await embedding.embed(
                texts=["a"],
                text_type=EmbedTextType.QUERY,
                model_name="openai/gpt-5-mini",
            )

    assert len(gateway.requests) == 1


@pytest.mark.asyncio
async def test_rate_limit_retries_only_the_failed_request() -> None:
    attempts: dict[str, int] = {}

    def limit_first_try_of_b(payload: dict[str, Any]) -> httpx.Response | None:
        text = payload["input"][0]
        attempts[text] = attempts.get(text, 0) + 1
        if text == "b" and attempts[text] == 1:
            return httpx.Response(429, json={"error": {"message": "slow down"}})
        return None

    gateway = _FakeGateway(respond=limit_first_try_of_b)
    async with _bifrost(gateway, "https://bifrost.example") as embedding:
        result = await embedding.embed(
            texts=["a", "b", "c"],
            text_type=EmbedTextType.PASSAGE,
            model_name="gemini/gemini-embedding-001",
        )

    assert len(result) == 3
    assert attempts == {"a": 1, "b": 2, "c": 1}


@pytest.mark.asyncio
async def test_an_exhausted_request_is_not_replayed_by_the_outer_retry() -> None:
    attempts: dict[str, int] = {}

    def always_fail_b(payload: dict[str, Any]) -> httpx.Response | None:
        text = payload["input"][0]
        attempts[text] = attempts.get(text, 0) + 1
        if text == "b":
            return httpx.Response(503, json={"error": {"message": "unavailable"}})
        return None

    gateway = _FakeGateway(respond=always_fail_b)
    with (
        patch(f"{_MODULE}._BIFROST_REQUEST_TRIES", 3),
        patch.object(
            cast(Any, CloudEmbedding.embed).retry, "stop", stop_after_attempt(5)
        ),
    ):
        async with _bifrost(gateway, "https://bifrost.example") as embedding:
            with pytest.raises(
                EmbeddingRequestFailedError, match="HTTP 503: unavailable"
            ):
                await embedding.embed(
                    texts=["a", "b", "c"],
                    text_type=EmbedTextType.PASSAGE,
                    model_name="gemini/gemini-embedding-001",
                )

    # Only the failing input is retried, and the inputs that succeeded are not resent.
    assert attempts == {"a": 1, "b": 3, "c": 1}


@pytest.mark.asyncio
async def test_an_unauthorized_key_is_an_authentication_error() -> None:
    gateway = _FakeGateway(
        respond=lambda _: httpx.Response(401, json={"error": {"message": "bad key"}})
    )
    async with _bifrost(gateway, "https://bifrost.example", "sk-bf-wrong") as embedding:
        with pytest.raises(AuthenticationError):
            await embedding.embed(
                texts=["a"],
                text_type=EmbedTextType.QUERY,
                model_name="openai/text-embedding-3-small",
            )

    assert len(gateway.requests) == 1


@pytest.mark.asyncio
async def test_a_missing_embedding_in_the_response_is_an_error() -> None:
    gateway = _FakeGateway(drop_last=True)
    async with _bifrost(gateway, "https://bifrost.example") as embedding:
        with pytest.raises(
            EmbeddingRequestFailedError, match="1 embeddings for 2 inputs"
        ):
            await embedding.embed(
                texts=["a", "b"],
                text_type=EmbedTextType.QUERY,
                model_name="openai/text-embedding-3-small",
            )

    assert len(gateway.requests) == 1


def test_bifrost_auth_allows_a_missing_key() -> None:
    auth = build_embedding_auth(EmbeddingProvider.BIFROST, None)
    assert isinstance(auth, ApiKeyEmbeddingAuth)
    auth.validate_credentials()
    assert auth.resolve_credentials().api_key.get_secret_value() == ""


def test_other_api_key_providers_still_require_a_key() -> None:
    auth = build_embedding_auth(EmbeddingProvider.LITELLM, None)
    with pytest.raises(ValueError, match="API key not provided"):
        auth.validate_credentials()


def _fake_encoding_for_model(model_name: str) -> object:
    if "/" in model_name:
        raise KeyError(model_name)
    return object()


@pytest.mark.parametrize(
    ("provider", "uses_tiktoken"),
    [(EmbeddingProvider.BIFROST, True), (EmbeddingProvider.LITELLM, False)],
)
def test_only_bifrost_strips_the_provider_prefix_for_the_tokenizer(
    provider: EmbeddingProvider, uses_tiktoken: bool
) -> None:
    with (
        patch("tiktoken.encoding_for_model", side_effect=_fake_encoding_for_model),
        patch.dict(TiktokenTokenizer._instances, clear=True),
    ):
        tokenizer = _try_initialize_tokenizer("openai/tokenizer-test", provider)

    assert isinstance(tokenizer, TiktokenTokenizer) is uses_tiktoken
