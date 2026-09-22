import base64
import json
from unittest.mock import patch

import httpx2 as httpx
import pytest
from openai import AsyncOpenAI

from onyx.image_gen.providers.pydantic_images import generate_openai_image


@pytest.mark.parametrize("model", ["gpt-image-1", "dall-e-3"])
def test_image_generation_uses_request_credentials_and_preserves_options(
    model: str,
) -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "created": 123,
                "data": [{"b64_json": base64.b64encode(b"\x89PNG\r\n\x1a\n").decode()}],
            },
        )

    client = AsyncOpenAI(
        api_key="tenant-key",
        base_url="https://tenant.example/v1",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
    )
    with patch("openai.AsyncOpenAI", return_value=client):
        result = generate_openai_image(
            prompt="a mountain",
            model=model,
            size="1024x1024",
            n=1,
            quality="high" if model == "gpt-image-1" else "standard",
            reference_images=None,
            api_key="tenant-key",
            api_base="https://tenant.example/v1",
        )
    assert result.data[0].b64_json == base64.b64encode(b"\x89PNG\r\n\x1a\n").decode()
    assert len(requests) == 1
    assert requests[0].headers["authorization"] == "Bearer tenant-key"
    assert requests[0].url.host == "tenant.example"
    payload = json.loads(requests[0].content)
    assert payload["model"] == model
    assert payload["size"] == "1024x1024"
    assert payload["n"] == 1
    assert client.is_closed()
