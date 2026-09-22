"""Ollama native transport preserves context controls and response events."""

import asyncio
import base64
import json
import socket
from typing import cast
from unittest.mock import Mock, patch

import httpx
import pytest
import requests
from pydantic_ai import messages as pm
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.settings import ModelSettings
from pydantic_ai.tools import ToolDefinition

from onyx.llm.ollama_model import OllamaNativeModel
from onyx.utils.url import SSRFException


def image_response(
    content: bytes = b"image", location: str | None = None
) -> requests.Response:
    response = requests.Response()
    response.status_code = 302 if location else 200
    response._content = content
    response.raw = Mock()
    if location:
        response.headers["Location"] = location
    return response


def image_message(url: str) -> list[pm.ModelMessage]:
    return [pm.ModelRequest(parts=[pm.UserPromptPart([pm.ImageUrl(url)])])]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/image.png",
        "http://169.254.169.254/image.png",
        "http://10.0.0.1/image.png",
        "http://[::1]/image.png",
        "http://localhost/image.png",
        "https://user:password@public.example/image.png",
        "file:///etc/passwd",
    ],
)
async def test_image_rejects_private_urls_before_network(url: str) -> None:
    model = OllamaNativeModel("qwen3", "http://localhost:11434", "tenant-key")
    with patch("onyx.utils.url._pinned_get") as request:
        with pytest.raises(SSRFException):
            await model._messages(image_message(url))
    request.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "target",
    ["http://10.0.0.1/secret", "https://127.0.0.1/secret", "//169.254.169.254/secret"],
)
async def test_image_rejects_private_redirect(target: str) -> None:
    model = OllamaNativeModel("qwen3", "http://localhost:11434")
    with patch(
        "onyx.utils.url.requests.Session.get",
        return_value=image_response(location=target),
    ) as request:
        with pytest.raises(SSRFException):
            await model._messages(image_message("https://8.8.8.8/image.png"))
    assert request.call_count == 1
    assert request.call_args.args[0] == "https://8.8.8.8/image.png"


@pytest.mark.asyncio
async def test_image_follows_public_protocol_relative_redirect() -> None:
    responses = [image_response(location="//8.8.4.4/final.png"), image_response()]
    model = OllamaNativeModel("qwen3", "http://localhost:11434")
    with patch("onyx.utils.url.requests.Session.get", side_effect=responses) as request:
        messages = await model._messages(image_message("https://8.8.8.8/image.png"))
    assert request.call_args_list[1].args[0] == "https://8.8.4.4/final.png"
    assert messages[0]["images"] == [base64.b64encode(b"image").decode()]


@pytest.mark.asyncio
@pytest.mark.parametrize("scheme", ["http", "https"])
async def test_image_fetch_ignores_ambient_credentials_and_proxies(scheme: str) -> None:
    model = OllamaNativeModel("qwen3", "http://localhost:11434", "tenant-key")
    with (
        patch(
            "requests.sessions.get_netrc_auth", return_value=("ambient", "secret")
        ) as netrc,
        patch(
            "requests.sessions.get_environ_proxies",
            return_value={"all": "http://proxy"},
        ) as proxies,
        patch("requests.Session.send", return_value=image_response()) as send,
    ):
        await model._messages(image_message(f"{scheme}://8.8.8.8/image.png"))
    netrc.assert_not_called()
    proxies.assert_not_called()
    assert "Authorization" not in send.call_args.args[0].headers
    assert send.call_args.kwargs["proxies"] == {}


@pytest.mark.asyncio
async def test_image_pins_dns_and_closes_response() -> None:
    response = image_response()
    public = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))]
    rebound = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))]
    model = OllamaNativeModel("qwen3", "http://localhost:11434", "tenant-key")
    with (
        patch(
            "onyx.utils.url.socket.getaddrinfo", side_effect=[public, rebound]
        ) as dns,
        patch("onyx.utils.url.requests.Session.get", return_value=response) as request,
    ):
        messages = await model._messages(
            image_message("https://public.example/image.png")
        )
    assert messages[0]["images"] == [base64.b64encode(b"image").decode()]
    dns.assert_called_once_with("public.example", 443)
    assert request.call_args.args[0] == "https://8.8.8.8/image.png"
    assert request.call_args.kwargs["headers"] == {"Host": "public.example"}
    assert request.call_args.kwargs["allow_redirects"] is False
    cast(Mock, response.raw).release_conn.assert_called_once()


@pytest.mark.asyncio
async def test_concurrent_image_fetches_do_not_share_provider_credentials() -> None:
    images = {"/one.png": b"one", "/two.png": b"two"}

    def fetch(url: str, **kwargs: object) -> requests.Response:
        assert kwargs["headers"] == {"Host": "8.8.8.8"}
        return image_response(images[url.removeprefix("https://8.8.8.8")])

    provider_payloads: dict[str, dict] = {}

    async def provider(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/chat"
        provider_payloads[request.headers["Authorization"]] = json.loads(
            request.content
        )
        return httpx.Response(200, json={"message": {"content": "done"}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
        first = OllamaNativeModel(
            "qwen3", "http://localhost:11434", "tenant-one", client
        )
        second = OllamaNativeModel(
            "qwen3", "http://localhost:11434", "tenant-two", client
        )
        with patch("onyx.utils.url.requests.Session.get", side_effect=fetch):
            await asyncio.gather(
                first.request(
                    image_message("https://8.8.8.8/one.png"),
                    None,
                    ModelRequestParameters(),
                ),
                second.request(
                    image_message("https://8.8.8.8/two.png"),
                    None,
                    ModelRequestParameters(),
                ),
            )
    for tenant, content in [("one", b"one"), ("two", b"two")]:
        assert provider_payloads[f"Bearer tenant-{tenant}"]["messages"][0][
            "images"
        ] == [base64.b64encode(content).decode()]


@pytest.mark.asyncio
async def test_native_context_size_and_tool_history() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/chat"
        assert request.headers["Authorization"] == "Bearer tenant-key"
        payload = json.loads(request.content)
        assert payload["options"] == {
            "num_ctx": 32768,
            "num_predict": 512,
            "temperature": 0.2,
        }
        assert payload["messages"][0]["tool_calls"][0]["function"]["arguments"] == {
            "q": "term"
        }
        assert payload["messages"][1] == {
            "role": "tool",
            "tool_name": "search",
            "content": "found",
        }
        return httpx.Response(
            200,
            json={
                "message": {"role": "assistant", "content": "answer"},
                "done": True,
                "prompt_eval_count": 100,
                "eval_count": 20,
                "prompt_eval_cached_count": 30,
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        model = OllamaNativeModel(
            "qwen3", "http://ollama.example/v1", "tenant-key", client
        )
        response = await model.request(
            [
                pm.ModelResponse(
                    parts=[pm.ToolCallPart("search", {"q": "term"}, "call-1")]
                ),
                pm.ModelRequest(parts=[pm.ToolReturnPart("search", "found", "call-1")]),
            ],
            ModelSettings(
                max_tokens=512, temperature=0.2, extra_body={"num_ctx": 32768}
            ),
            ModelRequestParameters(),
        )
    assert response.parts == [pm.TextPart("answer")]
    assert response.usage.input_tokens == 100 and response.usage.cache_read_tokens == 30


@pytest.mark.asyncio
async def test_native_stream_thinking_tools_text_and_usage() -> None:
    chunks = [
        {"message": {"thinking": "consider"}},
        {"message": {"content": "answer"}},
        {
            "message": {
                "tool_calls": [
                    {"function": {"name": "search", "arguments": {"q": "term"}}}
                ]
            }
        },
        {
            "done": True,
            "done_reason": "stop",
            "prompt_eval_count": 50,
            "eval_count": 10,
        },
    ]

    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["stream"] is True
        assert payload["options"]["num_ctx"] == 64000
        assert payload["tools"][0]["function"]["name"] == "search"
        return httpx.Response(
            200, content="\n".join(json.dumps(chunk) for chunk in chunks)
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        model = OllamaNativeModel("qwen3", "http://ollama.example", client=client)
        async with model.request_stream(
            [pm.ModelRequest(parts=[pm.UserPromptPart("hi")])],
            ModelSettings(extra_body={"num_ctx": 64000}),
            ModelRequestParameters(function_tools=[ToolDefinition(name="search")]),
        ) as stream:
            events = [event async for event in stream]
            response = stream.get()
    assert any(isinstance(event, pm.PartStartEvent) for event in events)
    assert isinstance(response.parts[0], pm.ThinkingPart)
    assert isinstance(response.parts[1], pm.TextPart)
    assert isinstance(response.parts[2], pm.ToolCallPart)
    assert response.parts[2].args_as_dict() == {"q": "term"}
    assert response.usage.input_tokens == 50 and response.usage.output_tokens == 10
