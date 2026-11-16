"""Exercise strict tool schemas through the real LiteLLM Responses bridge."""

import json
from contextlib import nullcontext
from copy import deepcopy
from typing import Any
from unittest.mock import patch

import httpx
import pytest
from pydantic import JsonValue

from onyx.llm.factory import get_llm
from onyx.llm.model_request import format_provider_message, serialize_tools
from onyx.llm.models import (
    GenerationOptions,
    GenerationRequest,
    ReasoningEffort,
    ToolCallEndEvent,
    ToolDefinition,
    UserMessage,
)
from onyx.llm.multi_llm import ProviderOperation


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize(
    "route",
    [
        "direct",
        "base",
        "base_url",
        "custom",
        "env",
        "azure",
        "raw",
        "raw_operation",
        "fine_tune",
        "unknown_deployment",
        "reject",
        "unrelated_error",
        "no_tools",
    ],
)
def test_strict_tools_round_trip(
    monkeypatch: pytest.MonkeyPatch, stream: bool, route: str
) -> None:
    bodies: list[dict[str, Any]] = []
    proxy = "https://proxy.example.com/v1"
    if route == "env":
        monkeypatch.setenv("OPENAI_API_BASE", proxy)
    else:
        monkeypatch.delenv("OPENAI_API_BASE", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    parameters: dict[str, JsonValue] = {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "limit": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
            "rows": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "value": {"anyOf": [{"type": "integer"}, {"type": "null"}]}
                    },
                    "required": ["value"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["query", "limit", "rows"],
        "additionalProperties": False,
    }
    external_parameters: dict[str, JsonValue] = {
        "type": "object",
        "properties": {
            "values": {"type": "object", "additionalProperties": {"type": "integer"}},
            "note": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        },
        "required": ["values"],
    }
    original = deepcopy(parameters)
    original_external = deepcopy(external_parameters)
    arguments = json.dumps(
        {"query": "roadmap", "limit": None, "rows": [{"value": None}]}
    )
    item = {
        "id": "fc_test",
        "type": "function_call",
        "call_id": "call_test",
        "name": "search",
        "arguments": arguments,
        "status": "completed",
    }

    external_arguments = {"values": {"arbitrary_key": 3}, "note": None}
    external_item = {
        **item,
        "id": "fc_external",
        "call_id": "call_external",
        "name": "external",
        "arguments": json.dumps(external_arguments),
    }

    def send(
        _client: httpx.Client, request: httpx.Request, **_kwargs: Any
    ) -> httpx.Response:
        body = json.loads(request.content)
        bodies.append(body)
        assert request.url.path.endswith("/responses")
        if route in ("reject", "unrelated_error") and len(bodies) == 1:
            return httpx.Response(
                400,
                request=request,
                json={
                    "error": {
                        "message": "Invalid strict tool schema"
                        if route == "reject"
                        else "Account has a strict spending restriction",
                        "code": "invalid_function_parameters"
                        if route == "reject"
                        else "account_restricted",
                        "type": "invalid_request_error",
                        "param": "tools[0]" if route == "reject" else None,
                    }
                },
            )
        response = {
            "id": "resp_test",
            "object": "response",
            "created_at": 1,
            "model": "gpt-6-luna",
            "status": "completed",
            "output": [item, external_item],
            "usage": {"input_tokens": 10, "output_tokens": 10, "total_tokens": 20},
        }
        if stream:
            events: list[dict[str, Any]] = []
            for output_index, output_item in enumerate([item, external_item]):
                output_arguments = output_item["arguments"]
                events.extend(
                    [
                        {
                            "type": "response.output_item.added",
                            "output_index": output_index,
                            "item": {
                                **output_item,
                                "arguments": "",
                                "status": "in_progress",
                            },
                        },
                        {
                            "type": "response.function_call_arguments.delta",
                            "output_index": output_index,
                            "item_id": output_item["id"],
                            "delta": output_arguments,
                        },
                        {
                            "type": "response.function_call_arguments.done",
                            "output_index": output_index,
                            "item_id": output_item["id"],
                            "arguments": output_arguments,
                        },
                        {
                            "type": "response.output_item.done",
                            "output_index": output_index,
                            "item": output_item,
                        },
                    ]
                )
            events.append({"type": "response.completed", "response": response})
            for number, event in enumerate(events):
                event["sequence_number"] = number
            return httpx.Response(
                200,
                request=request,
                headers={"content-type": "text/event-stream"},
                content="".join(
                    f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events
                ),
            )
        return httpx.Response(200, request=request, json=response)

    monkeypatch.setattr(httpx.Client, "send", send)
    client = get_llm(
        provider="azure" if route == "azure" else "openai",
        model="gpt-6-luna",
        deployment_name="deployment"
        if route == "azure"
        else "ft:gpt-6-luna:org:custom"
        if route == "fine_tune"
        else "unknown-deployment"
        if route == "unknown_deployment"
        else None,
        api_base=proxy
        if route == "base"
        else "https://test.openai.azure.com"
        if route == "azure"
        else None,
        custom_config={"OPENAI_API_BASE": proxy} if route == "custom" else None,
        model_kwargs={"base_url": proxy} if route == "base_url" else None,
        api_key="test-key",
        max_input_tokens=10000,
    )
    request = GenerationRequest(
        messages=[UserMessage(content="Search")],
        tools=[
            ToolDefinition(
                name="search", description="Search", parameters=parameters, strict=True
            ),
            ToolDefinition(
                name="external",
                description="External tool",
                parameters=external_parameters,
            ),
        ],
        options=GenerationOptions(reasoning_effort=ReasoningEffort.HIGH),
    )
    if route == "no_tools":
        request = request.model_copy(update={"tools": []})
    with (
        patch("onyx.llm.multi_llm._env_injection_enabled", return_value=False),
        (
            patch(
                "onyx.llm.multi_llm.find_model_obj",
                side_effect=AssertionError("Unnecessary strict eligibility lookup"),
            )
            if route == "no_tools"
            else nullcontext()
        ),
    ):
        if route == "unrelated_error":
            with pytest.raises(Exception, match="strict spending restriction"):
                list(client.stream(request)) if stream else client.invoke(request)
            assert len(bodies) == 1
            return
        if route in ("raw", "raw_operation"):
            operation = ProviderOperation() if route == "raw_operation" else None
            prompt = [format_provider_message(UserMessage(content="Search"))]
            if stream:
                list(
                    client.stream_raw(
                        prompt,
                        tools=serialize_tools(request.tools),
                        operation=operation,
                    )
                )
            else:
                client.invoke_raw(
                    prompt, tools=serialize_tools(request.tools), operation=operation
                )
            assert bodies[0]["tools"][0]["parameters"] == original
            assert bodies[0]["tools"][0]["strict"] is True
            return
        if stream:
            calls = [
                e.tool_call
                for e in client.stream(request)
                if isinstance(e, ToolCallEndEvent)
            ]
        else:
            calls = client.invoke(request).tool_calls
    if route == "no_tools":
        assert not bodies[0].get("tools")
        return
    strict = route in ("direct", "reject")
    assert bool(bodies[0]["tools"][0]["strict"]) is strict
    assert bodies[0]["tools"][0]["parameters"] == original
    assert not bodies[0]["tools"][1].get("strict")
    assert bodies[0]["tools"][1]["parameters"] == original_external
    assert calls[0].arguments == json.loads(arguments)
    assert calls[1].arguments == external_arguments
    assert parameters == original
    assert external_parameters == original_external
    if route == "reject":
        assert len(bodies) == 2
        assert bodies[1]["tools"][0]["strict"] is False
        assert bodies[1]["tools"][0]["parameters"] == original
        assert bodies[1]["reasoning"] == bodies[0]["reasoning"]
        assert bodies[1]["reasoning"]["effort"] == "high"


@pytest.mark.parametrize(
    ("schema", "expected"),
    [
        (
            {"anyOf": [{"type": "integer"}, {"type": "null"}]},
            {"anyOf": [{"type": "integer", "nullable": True}]},
        ),
        (
            {
                "anyOf": [
                    {"type": "string", "enum": ["square", "portrait", "landscape"]},
                    {"type": "null"},
                ]
            },
            {
                "anyOf": [
                    {
                        "type": "string",
                        "enum": ["square", "portrait", "landscape"],
                        "nullable": True,
                    }
                ]
            },
        ),
        (
            {
                "anyOf": [
                    {"type": "array", "items": {"type": "string"}},
                    {"type": "null"},
                ]
            },
            {
                "anyOf": [
                    {"type": "array", "items": {"type": "string"}, "nullable": True}
                ]
            },
        ),
    ],
)
def test_owned_nullable_arguments_survive_gemini_translation(
    schema: dict[str, Any], expected: dict[str, Any]
) -> None:
    from litellm.llms.vertex_ai.gemini.vertex_and_google_ai_studio_gemini import (
        VertexGeminiConfig,
    )

    parameters = {
        "type": "object",
        "properties": {"value": schema},
        "required": ["value"],
        "additionalProperties": False,
    }
    result = VertexGeminiConfig()._map_function(
        [{"type": "function", "function": {"name": "owned", "parameters": parameters}}],
        {},
    )
    translated = result[0]["function_declarations"][0]["parameters"]
    assert translated["properties"]["value"] == expected
    assert translated["required"] == ["value"]
