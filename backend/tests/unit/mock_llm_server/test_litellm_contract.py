"""Drives the mock LLM server with a real openai_compatible LitellmLLM, the way
the api_server calls it in integration tests."""

import json
from typing import Any
from unittest.mock import patch

import httpx
import pytest

from onyx.chat import llm_step
from onyx.llm.interfaces import LLM
from onyx.llm.model_response import ModelResponseStream
from onyx.llm.models import (
    ChatCompletionMessage,
    SystemMessage,
    ToolChoiceOptions,
    UserMessage,
)
from onyx.llm.multi_llm import LitellmLLM
from onyx.server.query_and_chat.placement import Placement
from tests.integration.mock_services.mock_llm_server.handle import ScriptHandle
from tests.integration.mock_services.mock_llm_server.models import (
    Matcher,
    Step,
    ToolCall,
)
from tests.integration.mock_services.mock_llm_server.server import MockLLMServerThread
from tests.unit.mock_llm_server.conftest import make_llm

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

PARALLEL_STEP = Step(
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
    script: ScriptHandle, llm: LitellmLLM
) -> None:
    script.lane("main", PARALLEL_STEP)

    result = _collect(list(llm.stream(prompt=PROMPT, tools=TOOLS)))

    assert result["reasoning"] == "Let me think about it."
    assert result["content"] == "Searching now."
    assert [(c["id"], c["name"], json.loads(c["args"])) for c in result["calls"]] == [
        ("call_a", "internal_search", {"queries": ["alpha"]}),
        ("call_b", "web_search", {"queries": ["beta", "gamma"]}),
    ]
    assert result["finish_reasons"] == ["tool_calls"]

    (request,) = script.requests
    assert request.stream is True
    assert request.model == "mock-model"
    assert request.tools == ["internal_search", "web_search"]
    assert [m.role for m in request.messages] == ["system", "user"]
    assert request.lane == "main" and request.step_index == 0
    script.verify()


def test_llm_step_turns_stream_into_tool_call_kickoffs(
    script: ScriptHandle, llm: LitellmLLM
) -> None:
    script.lane("main", PARALLEL_STEP)

    with patch.object(llm_step, "translate_history_to_llm_format", return_value=PROMPT):
        generator = llm_step.run_llm_step_pkt_generator(
            history=[],
            tool_definitions=TOOLS,
            tool_choice=ToolChoiceOptions.AUTO,
            llm=llm,
            placement=Placement(turn_index=0),
            state_container=None,
            citation_processor=None,
        )
        while True:
            try:
                next(generator)
            except StopIteration as stop:
                result, has_reasoned = stop.value
                break

    assert has_reasoned
    assert result.reasoning == "Let me think about it."
    assert [
        (tc.tool_call_id, tc.tool_name, tc.tool_args) for tc in result.tool_calls
    ] == [
        ("call_a", "internal_search", {"queries": ["alpha"]}),
        ("call_b", "web_search", {"queries": ["beta", "gamma"]}),
    ]
    assert script.requests[0].tool_choice == "auto"


@pytest.mark.parametrize(
    "step,expected",
    [
        (Step(text="All done."), "stop"),
        (Step(text="Cut off", finish_reason="length"), "length"),
    ],
)
def test_finish_reasons(
    script: ScriptHandle, llm: LitellmLLM, step: Step, expected: str
) -> None:
    script.lane("main", step)

    result = _collect(list(llm.stream(prompt=PROMPT)))

    assert result["finish_reasons"] == [expected]


def test_stream_usage_follows_include_usage(
    script: ScriptHandle, llm: LitellmLLM
) -> None:
    script.lane("main", Step(text="one"), Step(text="two"), Step(text="three"))

    onyx_result = _collect(list(llm.stream(prompt=PROMPT)))
    assert script.requests[0].include_usage is True
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


def test_invoke_without_streaming(script: ScriptHandle, llm: LitellmLLM) -> None:
    script.lane("main", PARALLEL_STEP)

    response = llm.invoke(
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
    assert request.stream is False
    assert request.tool_choice == "required"


def test_invoke_with_streaming(script: ScriptHandle, llm: LitellmLLM) -> None:
    script.lane("main", Step(reasoning="Hmm.", text="Streamed answer."))

    with patch("onyx.llm.multi_llm._env_injection_enabled", return_value=True):
        response = llm.invoke(prompt=PROMPT)

    assert response.choice.message.content == "Streamed answer."
    assert script.requests[0].stream is True


@pytest.mark.parametrize("streamed", [True, False])
def test_no_match_is_a_plain_400_that_is_not_retried(
    script: ScriptHandle, llm: LitellmLLM, streamed: bool
) -> None:
    script.lane("main", Step(text="never"), match=Matcher(offered_tools=["web_search"]))
    prompt: list[ChatCompletionMessage] = [UserMessage(content="SECRET-PROMPT-TEXT")]

    with pytest.raises(Exception) as exc_info:
        if streamed:
            list(llm.stream(prompt=prompt))
        else:
            llm.invoke(prompt=prompt)

    message = str(exc_info.value)
    assert "no scripted step matched" in message
    assert "SECRET-PROMPT-TEXT" not in message
    (request,) = script.requests
    assert request.error == "no pending step matched"
    with pytest.raises(AssertionError, match="was not followed"):
        script.verify()


def test_disconnect_before_first_chunk_is_retried(
    script: ScriptHandle, llm: LitellmLLM
) -> None:
    script.lane("main", Step(disconnect=True), Step(text="Recovered."))

    result = _collect(list(llm.stream(prompt=PROMPT)))

    assert result["content"] == "Recovered."
    assert [r.step_index for r in script.requests] == [0, 1]
    script.verify()


def test_scripts_are_isolated(
    mock_llm_server: MockLLMServerThread, script: ScriptHandle, llm: LLM
) -> None:
    other = ScriptHandle(
        mock_llm_server.registry,
        "other-script",
        mock_llm_server.api_base("other-script"),
    )
    try:
        script.lane("main", Step(text="mine"))
        other.lane("main", Step(text="theirs"))

        other_llm = make_llm(other.api_base)
        assert _collect(list(other_llm.stream(prompt=PROMPT)))["content"] == "theirs"
        assert _collect(list(llm.stream(prompt=PROMPT)))["content"] == "mine"
        assert len(script.requests) == 1 and len(other.requests) == 1
    finally:
        other.close()
