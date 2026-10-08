"""Drives the mock LLM server with a real openai_compatible LitellmLLM, the way
the api_server calls it in integration tests."""

import json
from typing import Any
from unittest.mock import patch
from uuid import uuid4

import httpx
import pytest

from onyx.llm.model_request import ChatCompletionMessage, SystemMessage, UserMessage
from onyx.llm.model_response import ModelResponseStream
from onyx.llm.models import (
    AssistantMessage,
    GenerationDoneEvent,
    GenerationOptions,
    GenerationRequest,
    ToolCallEndEvent,
    ToolChoiceOptions,
    ToolDefinition,
    apply_generation_event,
)
from onyx.llm.models import (
    UserMessage as AppUserMessage,
)
from onyx.llm.multi_llm import LitellmLLM
from tests.external_dependency_unit.llm.mock_llm_server.conftest import make_llm
from tests.integration.common_utils.managers.mock_llm import MockLLMScript
from tests.integration.mock_services.mock_llm_server.models import (
    Reply,
    RequestConditions,
    Script,
    ToolCall,
)

PROMPT: list[ChatCompletionMessage] = [
    SystemMessage(content="You are a test."),
    UserMessage(content="hi"),
]


def _tool(name: str) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": name,
            "parameters": {
                "type": "object",
                "properties": {
                    "queries": {"type": "array", "items": {"type": "string"}}
                },
                "required": ["queries"],
            },
        },
    }


TOOLS = [_tool("internal_search"), _tool("web_search")]

# Tool-free requests only reach conversations that allow them.
TOOL_FREE = RequestConditions(has_tools=False)

PARALLEL_REPLY = Reply(
    reasoning="Let me think about it.",
    text="Searching now.",
    tool_calls=[
        ToolCall(id="call_a", name="internal_search", arguments={"queries": ["alpha"]}),
        ToolCall(
            id="call_b", name="web_search", arguments={"queries": ["beta", "gamma"]}
        ),
    ],
)


def _collect(chunks: list[ModelResponseStream]) -> dict[str, Any]:
    reasoning = ""
    content = ""
    calls: dict[int, dict[str, str]] = {}
    finish_reasons: list[str] = []
    usages = []
    for chunk in chunks:
        delta = chunk.choice.delta
        reasoning += delta.reasoning_content or ""
        content += delta.content or ""
        for tool_call in delta.tool_calls or []:
            entry = calls.setdefault(
                tool_call.index, {"id": "", "name": "", "args": ""}
            )
            entry["id"] = tool_call.id or entry["id"]
            if tool_call.function is not None:
                entry["name"] = tool_call.function.name or entry["name"]
                entry["args"] += tool_call.function.arguments or ""
        if chunk.choice.finish_reason:
            finish_reasons.append(chunk.choice.finish_reason)
        if chunk.usage is not None:
            usages.append(chunk.usage)
    return {
        "reasoning": reasoning,
        "content": content,
        "calls": [calls[i] for i in sorted(calls)],
        "finish_reasons": finish_reasons,
        "usages": usages,
    }


def test_stream_reasoning_text_and_parallel_tool_calls(
    script: MockLLMScript, llm: LitellmLLM
) -> None:
    script.conversation("main", PARALLEL_REPLY)

    result = _collect(list(llm.stream_raw(prompt=PROMPT, tools=TOOLS)))

    assert result["reasoning"] == "Let me think about it."
    assert result["content"] == "Searching now."
    assert [(c["id"], c["name"], json.loads(c["args"])) for c in result["calls"]] == [
        ("call_a", "internal_search", {"queries": ["alpha"]}),
        ("call_b", "web_search", {"queries": ["beta", "gamma"]}),
    ]
    assert result["finish_reasons"] == ["tool_calls"]

    (request,) = script.requests
    assert request.body["stream"] is True
    assert request.body["model"] == "mock-model"
    assert request.tools == ["internal_search", "web_search"]
    assert [m.role for m in request.messages] == ["system", "user"]
    assert request.conversation == "main" and request.reply_index == 0
    script.verify()


@pytest.mark.parametrize("streaming", [False, True])
def test_public_generation_preserves_reasoning_and_parallel_tool_calls(
    script: MockLLMScript, llm: LitellmLLM, streaming: bool
) -> None:
    script.conversation("main", PARALLEL_REPLY)
    request = GenerationRequest(
        system_prompt="You are a test.",
        messages=[AppUserMessage(content="hi")],
        tools=[ToolDefinition.model_validate(tool["function"]) for tool in TOOLS],
        options=GenerationOptions(tool_choice=ToolChoiceOptions.AUTO),
    )
    if streaming:
        events = list(llm.stream(request))
        assert isinstance(events[-1], GenerationDoneEvent)
        assert [
            event.tool_call.id
            for event in events
            if isinstance(event, ToolCallEndEvent)
        ] == ["call_a", "call_b"]
        result = AssistantMessage()
        for event in events:
            apply_generation_event(result, event)
    else:
        result = llm.invoke(request)

    assert result.text == "Searching now."
    assert result.thinking == "Let me think about it."
    assert [(call.id, call.name, call.arguments) for call in result.tool_calls] == [
        ("call_a", "internal_search", {"queries": ["alpha"]}),
        ("call_b", "web_search", {"queries": ["beta", "gamma"]}),
    ]
    assert result.stop_reason == "tool_calls"
    assert result.usage is not None and result.usage.completion_tokens > 0
    assert script.requests[0].tool_choice == "auto"
    script.verify()


def test_text_reply_finishes_with_stop(script: MockLLMScript, llm: LitellmLLM) -> None:
    script.conversation("main", Reply(text="All done."), conditions=TOOL_FREE)

    result = _collect(list(llm.stream_raw(prompt=PROMPT)))

    assert result["content"] == "All done."
    assert result["finish_reasons"] == ["stop"]


def test_stream_usage_follows_include_usage(
    script: MockLLMScript, llm: LitellmLLM
) -> None:
    script.conversation(
        "main",
        Reply(text="one"),
        Reply(text="two"),
        Reply(text="three"),
        conditions=TOOL_FREE,
    )

    onyx_result = _collect(list(llm.stream_raw(prompt=PROMPT)))
    assert script.requests[0].body["stream_options"] == {"include_usage": True}
    assert len(onyx_result["usages"]) == 1
    assert onyx_result["usages"][0].completion_tokens > 0

    def raw_stream(include_usage: bool) -> list[dict[str, Any]]:
        body: dict[str, Any] = {
            "model": "mock-model",
            "stream": True,
            "messages": [{"role": "user", "content": "hi"}],
        }
        if include_usage:
            body["stream_options"] = {"include_usage": True}
        response = httpx.post(f"{script.api_base}/chat/completions", json=body)
        response.raise_for_status()
        return [
            json.loads(line.removeprefix("data: "))
            for line in response.text.splitlines()
            if line.startswith("data: {")
        ]

    without_usage = raw_stream(include_usage=False)
    assert not any("usage" in chunk for chunk in without_usage)
    with_usage = raw_stream(include_usage=True)
    assert with_usage[-1]["choices"] == [] and "usage" in with_usage[-1]
    script.verify()


def test_invoke_without_streaming(script: MockLLMScript, llm: LitellmLLM) -> None:
    script.conversation("main", PARALLEL_REPLY)

    response = llm.invoke_raw(
        prompt=PROMPT, tools=TOOLS, tool_choice=ToolChoiceOptions.REQUIRED
    )

    message = response.choice.message
    assert message.content == "Searching now."
    assert message.reasoning_content == "Let me think about it."
    assert [(t.id, t.function.name) for t in message.tool_calls or []] == [
        ("call_a", "internal_search"),
        ("call_b", "web_search"),
    ]
    assert response.choice.finish_reason == "tool_calls"
    assert response.usage is not None
    (request,) = script.requests
    assert not request.body.get("stream")
    assert request.tool_choice == "required"


def test_invoke_with_streaming(script: MockLLMScript, llm: LitellmLLM) -> None:
    script.conversation(
        "main", Reply(reasoning="Hmm.", text="Streamed answer."), conditions=TOOL_FREE
    )

    with patch("onyx.llm.multi_llm._env_injection_enabled", return_value=True):
        response = llm.invoke_raw(prompt=PROMPT)

    assert response.choice.message.content == "Streamed answer."
    assert script.requests[0].body["stream"] is True


@pytest.mark.parametrize("streamed", [True, False])
def test_no_match_is_a_plain_400_that_is_not_retried(
    mock_llm_server: str, streamed: bool
) -> None:
    script = MockLLMScript(mock_llm_server, uuid4().hex, Script(default_reply=None))
    try:
        script.conversation(
            "main", Reply(text="never"), conditions=RequestConditions(has_tools=True)
        )
        prompt: list[ChatCompletionMessage] = [UserMessage(content="SECRET-PROMPT")]
        llm = make_llm(script.api_base)

        with pytest.raises(Exception) as exc_info:
            if streamed:
                list(llm.stream_raw(prompt=prompt))
            else:
                llm.invoke_raw(prompt=prompt)

        message = str(exc_info.value)
        assert "no scripted reply matched" in message
        assert "SECRET-PROMPT" not in message
        (request,) = script.requests
        assert request.error == "no reply matched"
        with pytest.raises(AssertionError, match="was not followed"):
            script.verify()
    finally:
        script.close()


def test_unknown_script_is_a_400(mock_llm_server: str) -> None:
    response = httpx.post(
        f"{mock_llm_server}/scripts/missing/v1/chat/completions",
        json={"model": "mock-model", "messages": []},
    )

    assert response.status_code == 400
    assert "unknown script" in response.json()["error"]["message"]


def test_scripts_are_isolated(
    mock_llm_server: str, script: MockLLMScript, llm: LitellmLLM
) -> None:
    other = MockLLMScript(mock_llm_server, uuid4().hex)
    try:
        script.conversation("main", Reply(text="mine"), conditions=TOOL_FREE)
        other.conversation("main", Reply(text="theirs"), conditions=TOOL_FREE)

        other_llm = make_llm(other.api_base)
        assert (
            _collect(list(other_llm.stream_raw(prompt=PROMPT)))["content"] == "theirs"
        )
        assert _collect(list(llm.stream_raw(prompt=PROMPT)))["content"] == "mine"
        assert len(script.requests) == 1 and len(other.requests) == 1
    finally:
        other.close()
