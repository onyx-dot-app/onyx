"""Pydantic AI transport for Ollama's native API and context-size option."""

import asyncio
import base64
import json
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, cast
from uuid import uuid4

import httpx
from pydantic_ai import RunContext
from pydantic_ai import messages as pm
from pydantic_ai._instrumentation import get_instructions
from pydantic_ai.exceptions import ModelHTTPError, UnexpectedModelBehavior
from pydantic_ai.models import (
    Model,
    ModelRequestParameters,
    StreamedResponse,
    check_allow_model_requests,
)
from pydantic_ai.profiles import ModelProfile
from pydantic_ai.settings import ModelSettings
from pydantic_ai.usage import RequestUsage

from onyx.utils.url import ssrf_safe_get


def _download_image(url: str) -> bytes:
    # Image input is untrusted; keep it separate from provider credentials.
    with ssrf_safe_get(url, allow_private_network=False, trust_env=False) as response:
        response.raise_for_status()
        return response.content


def _usage(data: dict[str, Any]) -> RequestUsage:
    return RequestUsage(
        input_tokens=data.get("prompt_eval_count", 0),
        output_tokens=data.get("eval_count", 0),
        cache_read_tokens=data.get("prompt_eval_cached_count", 0),
    )


def _response(data: dict[str, Any], name: str) -> pm.ModelResponse:
    message = data.get("message", {})
    parts: list[pm.ModelResponsePart] = []
    if message.get("thinking"):
        parts.append(pm.ThinkingPart(message["thinking"], provider_name="ollama"))
    if message.get("content"):
        parts.append(pm.TextPart(message["content"]))
    for tool in message.get("tool_calls", []):
        function = tool["function"]
        parts.append(
            pm.ToolCallPart(
                function["name"], function["arguments"], tool.get("id") or str(uuid4())
            )
        )
    return pm.ModelResponse(
        parts=parts,
        model_name=name,
        provider_name="ollama",
        usage=_usage(data),
        finish_reason="length" if data.get("done_reason") == "length" else "stop",
    )


class OllamaNativeModel(Model):
    def __init__(
        self,
        name: str,
        base_url: str,
        api_key: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(
            profile=ModelProfile(
                supports_tools=True,
                supports_json_schema_output=True,
                supports_thinking=True,
            )
        )
        self._name = name
        self._base = base_url.rstrip("/").removesuffix("/v1").removesuffix("/api")
        self._api_key = api_key
        self._client = client

    @property
    def model_name(self) -> str:
        return self._name

    @property
    def system(self) -> str:
        return "ollama"

    @property
    def base_url(self) -> str:
        return self._base

    @asynccontextmanager
    async def _http(self) -> AsyncIterator[httpx.AsyncClient]:
        if self._client is not None:
            yield self._client
        else:
            async with httpx.AsyncClient() as client:
                yield client

    async def _user_content(
        self, content_parts: Sequence[pm.UserContent]
    ) -> dict[str, Any]:
        text: list[str] = []
        images: list[str] = []
        for content in content_parts:
            if isinstance(content, str):
                text.append(content)
            elif isinstance(content, pm.TextContent):
                text.append(content.content)
            elif isinstance(content, pm.BinaryContent):
                images.append(base64.b64encode(content.data).decode())
            elif isinstance(content, pm.ImageUrl):
                if content.url.startswith("data:"):
                    images.append(content.url.split(",", 1)[1])
                else:
                    data = await asyncio.to_thread(_download_image, content.url)
                    images.append(base64.b64encode(data).decode())
            elif not isinstance(content, pm.CachePoint):
                raise ValueError("Ollama supports text and image input")
        return {"role": "user", "content": "\n".join(text), "images": images}

    async def _messages(self, messages: list[pm.ModelMessage]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for message in messages:
            if isinstance(message, pm.ModelRequest):
                for part in message.parts:
                    if isinstance(part, pm.SystemPromptPart):
                        result.append({"role": "system", "content": part.content})
                    elif isinstance(part, pm.ToolReturnPart):
                        result.append(
                            {
                                "role": "tool",
                                "tool_name": part.tool_name,
                                "content": part.model_response_str(),
                            }
                        )
                    elif isinstance(part, pm.RetryPromptPart):
                        result.append(
                            {
                                "role": "tool" if part.tool_name else "user",
                                "content": part.model_response(),
                            }
                        )
                    elif isinstance(part, pm.UserPromptPart):
                        if isinstance(part.content, str):
                            result.append({"role": "user", "content": part.content})
                            continue
                        result.append(await self._user_content(part.content))
            else:
                assistant: dict[str, Any] = {"role": "assistant", "content": ""}
                tools: list[dict[str, Any]] = []
                for response_part in message.parts:
                    if isinstance(response_part, pm.TextPart):
                        assistant["content"] += response_part.content
                    elif isinstance(response_part, pm.ThinkingPart):
                        assistant["thinking"] = (
                            assistant.get("thinking", "") + response_part.content
                        )
                    elif isinstance(response_part, pm.ToolCallPart):
                        tools.append(
                            {
                                "function": {
                                    "name": response_part.tool_name,
                                    "arguments": response_part.args_as_dict(),
                                }
                            }
                        )
                if tools:
                    assistant["tool_calls"] = tools
                result.append(assistant)
        return result

    async def _payload(
        self,
        messages: list[pm.ModelMessage],
        settings: ModelSettings,
        params: ModelRequestParameters,
        stream: bool,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model_name,
            "messages": await self._messages(messages),
            "stream": stream,
        }
        instructions = get_instructions(messages, params)
        if instructions:
            payload["messages"].insert(0, {"role": "system", "content": instructions})
        options: dict[str, Any] = {}
        for source, target in {
            "temperature": "temperature",
            "max_tokens": "num_predict",
            "top_p": "top_p",
            "top_k": "top_k",
            "seed": "seed",
            "stop_sequences": "stop",
        }.items():
            if source in settings:
                options[target] = cast(dict[str, Any], settings)[source]
        extra = settings.get("extra_body")
        if isinstance(extra, dict):
            extra = dict(extra)
            if "num_ctx" in extra:
                options["num_ctx"] = extra.pop("num_ctx")
            options.update(extra.pop("options", {}))
            payload.update(extra)
        if options:
            payload["options"] = options
        if params.thinking is not None:
            payload["think"] = "high" if params.thinking == "xhigh" else params.thinking
        if params.output_object:
            payload["format"] = params.output_object.json_schema
        tools = params.function_tools + params.output_tools
        choice = settings.get("tool_choice")
        if choice == "none":
            tools = []
        elif isinstance(choice, list):
            tools = [tool for tool in tools if tool.name in choice]
        if tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description or "",
                        "parameters": tool.parameters_json_schema,
                    },
                }
                for tool in tools
            ]
        return payload

    def _headers(self, settings: ModelSettings) -> dict[str, str]:
        headers = {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}
        return headers | settings.get("extra_headers", {})

    async def request(
        self,
        messages: list[pm.ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> pm.ModelResponse:
        check_allow_model_requests()
        settings, params = self.prepare_request(
            model_settings, model_request_parameters
        )
        settings = settings or ModelSettings()
        async with self._http() as client:
            response = await client.post(
                f"{self._base}/api/chat",
                json=await self._payload(messages, settings, params, False),
                headers=self._headers(settings),
                timeout=settings.get("timeout", 60),
            )
            if response.is_error:
                raise ModelHTTPError(
                    response.status_code, self.model_name, response.text
                )
            data = response.json()
            if data.get("error"):
                raise UnexpectedModelBehavior(data["error"])
            return _response(data, self.model_name)

    @asynccontextmanager
    async def request_stream(
        self,
        messages: list[pm.ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
        run_context: RunContext[Any] | None = None,  # noqa: ARG002 - Model interface
    ) -> AsyncIterator[StreamedResponse]:
        check_allow_model_requests()
        settings, params = self.prepare_request(
            model_settings, model_request_parameters
        )
        settings = settings or ModelSettings()
        async with self._http() as client:
            async with client.stream(
                "POST",
                f"{self._base}/api/chat",
                json=await self._payload(messages, settings, params, True),
                headers=self._headers(settings),
                timeout=settings.get("timeout", 60),
            ) as response:
                if response.is_error:
                    await response.aread()
                    raise ModelHTTPError(
                        response.status_code, self.model_name, response.text
                    )
                yield OllamaStreamedResponse(
                    model_request_parameters=params,
                    _name=self.model_name,
                    _url=self._base,
                    _response=response,
                )


@dataclass
class OllamaStreamedResponse(StreamedResponse):
    _name: str
    _url: str
    _response: httpx.Response
    _timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    async def _get_event_iterator(self) -> AsyncIterator[pm.ModelResponseStreamEvent]:
        tool_index = 0
        async for line in self._response.aiter_lines():
            if not line:
                continue
            data = json.loads(line)
            if data.get("error"):
                raise UnexpectedModelBehavior(data["error"])
            message = data.get("message", {})
            if message.get("thinking"):
                for event in self._parts_manager.handle_thinking_delta(
                    vendor_part_id="thinking",
                    content=message["thinking"],
                    provider_name="ollama",
                ):
                    yield event
            if message.get("content"):
                for event in self._parts_manager.handle_text_delta(
                    vendor_part_id="text", content=message["content"]
                ):
                    yield event
            for tool in message.get("tool_calls", []):
                function = tool["function"]
                yield self._parts_manager.handle_part(
                    vendor_part_id=f"tool-{tool_index}",
                    part=pm.ToolCallPart(
                        function["name"],
                        function["arguments"],
                        tool.get("id") or str(uuid4()),
                    ),
                )
                tool_index += 1
            if data.get("done"):
                self._usage = _usage(data)
                self._finish_reason = (
                    "length" if data.get("done_reason") == "length" else "stop"
                )

    async def close_stream(self) -> None:
        await self._response.aclose()

    @property
    def model_name(self) -> str:
        return self._name

    @property
    def provider_name(self) -> str:
        return "ollama"

    @property
    def provider_url(self) -> str:
        return self._url

    @property
    def timestamp(self) -> datetime:
        return self._timestamp
