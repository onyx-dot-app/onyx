"""Verify final-answer evidence through the native LiteLLM Ollama adapters."""

import json
from typing import Any
from unittest.mock import patch

import httpx
import pytest

from onyx.llm.models import (
    AssistantMessage,
    GenerationOptions,
    GenerationRequest,
    ToolCall,
    ToolChoiceOptions,
    ToolDefinition,
    ToolResultMessage,
    UserMessage,
)
from onyx.llm.multi_llm import LitellmLLM
from tests.unit.onyx.agents.fakes import collect_generation


@pytest.mark.parametrize("provider", ["ollama", "ollama_chat"])
@pytest.mark.parametrize("streaming", [False, True])
def test_final_answer_preserves_evidence_without_offering_tools(
    monkeypatch: pytest.MonkeyPatch, provider: str, streaming: bool
) -> None:
    sent: list[dict[str, Any]] = []

    def send(_: httpx.Client, request: httpx.Request, **_kwargs: Any) -> httpx.Response:
        assert request.url.path == (
            "/api/generate" if provider == "ollama" else "/api/chat"
        )
        sent.append(json.loads(request.content))
        response = {
            "model": "llama3.2",
            "created_at": "2026-01-01T00:00:00Z",
            "response": "Sunny, 20C",
            "message": {"role": "assistant", "content": "Sunny, 20C"},
            "done": True,
            "done_reason": "stop",
            "prompt_eval_count": 50,
            "eval_count": 5,
        }
        chunks = [response]
        if streaming:
            chunks = [
                {**response, "done": False},
                {
                    **response,
                    "response": "",
                    "message": {"role": "assistant", "content": ""},
                },
            ]
        return httpx.Response(
            200,
            content="\n".join(json.dumps(chunk) for chunk in chunks) + "\n",
            request=request,
        )

    monkeypatch.setattr(httpx.Client, "send", send)
    llm = LitellmLLM(
        api_key=None,
        api_base="http://ollama.test",
        model_provider=provider,
        model_name="llama3.2",
        max_input_tokens=10000,
    )
    request = GenerationRequest(
        messages=[
            UserMessage(content="What is the weather?"),
            AssistantMessage(
                content=[
                    ToolCall(
                        id="weather-1", name="get_weather", arguments={"city": "Paris"}
                    )
                ]
            ),
            ToolResultMessage(
                tool_call_id="weather-1", tool_name="get_weather", content="Sunny, 20C"
            ),
        ],
        tools=[
            ToolDefinition(name="get_weather", description="Get weather", parameters={})
        ],
        allowed_tool_names=frozenset(),
        options=GenerationOptions(tool_choice=ToolChoiceOptions.NONE),
    )
    with patch("onyx.llm.multi_llm._env_injection_enabled", return_value=False):
        result = (
            collect_generation(list(llm.stream(request)))
            if streaming
            else llm.invoke(request)
        )
    assert result.text == "Sunny, 20C"
    assert not result.tool_calls
    assert len(sent) == 1
    body = sent[0]
    assert not body.get("tools")
    assert not body.get("options", {}).get("tools")
    evidence = json.dumps(body["prompt"] if provider == "ollama" else body["messages"])
    assert all(
        value in evidence
        for value in ("get_weather", "Paris", "Sunny, 20C", "weather-1")
    )
