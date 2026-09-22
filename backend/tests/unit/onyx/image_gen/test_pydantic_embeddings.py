import json
from unittest.mock import patch

import httpx2 as httpx
import pytest
from openai import AsyncAzureOpenAI

from onyx.natural_language_processing.search_nlp_models import CloudEmbedding
from shared_configs.enums import EmbeddingProvider


@pytest.mark.asyncio
async def test_azure_embeddings_keep_deployment_credentials_and_order() -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "object": "list",
                "data": [
                    {"object": "embedding", "index": 0, "embedding": [1.0, 2.0]},
                    {"object": "embedding", "index": 1, "embedding": [3.0, 4.0]},
                ],
                "model": "embedding-deployment",
                "usage": {"prompt_tokens": 2, "total_tokens": 2},
            },
        )

    client = AsyncAzureOpenAI(
        api_key="tenant-azure-key",
        azure_endpoint="https://tenant.azure.example",
        api_version="2024-02-01",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
    )
    async with CloudEmbedding(
        api_key="tenant-azure-key",
        provider=EmbeddingProvider.AZURE,
        api_url="https://tenant.azure.example",
        api_version="2024-02-01",
    ) as embedding:
        with patch("openai.AsyncAzureOpenAI", return_value=client):
            result = await embedding._embed_azure(
                ["first", "second"], "embedding-deployment"
            )
    assert result == [[1.0, 2.0], [3.0, 4.0]]
    assert requests[0].headers["api-key"] == "tenant-azure-key"
    assert "/deployments/embedding-deployment/" in requests[0].url.path
    assert json.loads(requests[0].content)["input"] == ["first", "second"]
    assert client.is_closed()


@pytest.mark.parametrize(
    "endpoint,model,version,expected_path,expected_version",
    [
        (
            "https://azure.example",
            "embed",
            None,
            "/openai/deployments/embed/embeddings",
            "2024-10-21",
        ),
        (
            "https://proxy.example/team/openai/deployments/from-url/embeddings?api-version=2024-02-01&route=blue",
            None,
            None,
            "/team/openai/deployments/from-url/embeddings",
            "2024-02-01",
        ),
        (
            "https://proxy.example/team/openai/deployments/from-url/embeddings?api-version=2024-02-01",
            "explicit",
            "2024-10-21",
            "/team/openai/deployments/explicit/embeddings",
            "2024-10-21",
        ),
        (
            "https://proxy.example/team/openai/",
            "embed",
            None,
            "/team/openai/deployments/embed/embeddings",
            "2024-10-21",
        ),
        (
            "https://proxy.example/team",
            "embed",
            None,
            "/team/openai/deployments/embed/embeddings",
            "2024-10-21",
        ),
        (
            "https://proxy.example/team",
            None,
            None,
            "/team/openai/deployments/configured-model/embeddings",
            "2024-10-21",
        ),
    ],
)
@pytest.mark.asyncio
async def test_azure_embedding_normalizes_configured_endpoint(
    endpoint: str,
    model: str | None,
    version: str | None,
    expected_path: str,
    expected_version: str,
) -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "object": "list",
                "data": [{"object": "embedding", "index": 0, "embedding": [1.0]}],
                "model": "embed",
                "usage": {"prompt_tokens": 1, "total_tokens": 1},
            },
        )

    original_init = AsyncAzureOpenAI.__init__

    def initialize(
        self: AsyncAzureOpenAI,
        *,
        api_key: str,
        azure_endpoint: str,
        api_version: str,
        timeout: int,
        default_query: dict[str, str],
    ) -> None:
        original_init(
            self,
            api_key=api_key,
            azure_endpoint=azure_endpoint,
            api_version=api_version,
            timeout=timeout,
            default_query=default_query,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
        )

    async with CloudEmbedding(
        api_key="test-key",
        provider=EmbeddingProvider.AZURE,
        api_url=endpoint,
        api_version=version,
        timeout=17,
    ) as embedding:
        with patch.object(AsyncAzureOpenAI, "__init__", initialize):
            assert await embedding._embed_azure(
                ["text"], model, model_name="configured-model"
            ) == [[1.0]]
    request = requests[0]
    assert request.url.path == expected_path
    assert request.url.params["api-version"] == expected_version
    if "route=blue" in endpoint:
        assert request.url.params["route"] == "blue"
    assert request.extensions["timeout"]["read"] == 17
