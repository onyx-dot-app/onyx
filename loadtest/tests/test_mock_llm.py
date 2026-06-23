"""Contract tests for the mock LLM server.

Each test replays the exact request shapes Onyx's LLM loops send (per
backend/onyx/chat/llm_loop.py, llm_step.py and deep_research/dr_loop.py) and
asserts the mock responds the way those loops need to make progress.

Run:  uv run pytest tests/ -q
"""

from __future__ import annotations

import json
from typing import Any

from fastapi.testclient import TestClient
from mock_llm.app import app

client = TestClient(app)

INTERNAL_SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "internal_search",
        "description": "Search connected applications for information.",
        "parameters": {
            "type": "object",
            "properties": {
                "queries": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of search queries to execute.",
                }
            },
            "required": ["queries"],
        },
    },
}

RESEARCH_AGENT_TOOL = {
    "type": "function",
    "function": {
        "name": "research_agent",
        "parameters": {
            "type": "object",
            "properties": {"task": {"type": "string"}},
            "required": ["task"],
        },
    },
}

GENERATE_REPORT_TOOL = {
    "type": "function",
    "function": {
        "name": "generate_report",
        "parameters": {"type": "object", "properties": {}},
    },
}

GENERATE_PLAN_TOOL = {
    "type": "function",
    "function": {
        "name": "generate_plan",
        "parameters": {"type": "object", "properties": {}},
    },
}

WEB_SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "web_search",
        "parameters": {
            "type": "object",
            "properties": {"queries": {"type": "array", "items": {"type": "string"}}},
            "required": ["queries"],
        },
    },
}

OPEN_URL_TOOL = {
    "type": "function",
    "function": {
        "name": "open_url",
        "parameters": {
            "type": "object",
            "properties": {"urls": {"type": "array", "items": {"type": "string"}}},
            "required": ["urls"],
        },
    },
}

THINK_TOOL = {
    "type": "function",
    "function": {
        "name": "think_tool",
        "parameters": {
            "type": "object",
            "properties": {"reasoning": {"type": "string"}},
            "required": ["reasoning"],
        },
    },
}


def complete(
    model: str = "mock-ttft0-itl0-len20",
    messages: list[dict[str, Any]] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": model,
        "stream": False,
        "messages": messages or [{"role": "user", "content": "load test question"}],
    }
    body.update(kwargs)
    response = client.post("/v1/chat/completions", json=body)
    assert response.status_code == 200
    return response.json()["choices"][0]


def stream_chunks(
    model: str = "mock-ttft0-itl0-len20",
    messages: list[dict[str, Any]] | None = None,
    **kwargs: Any,
) -> list[dict[str, Any]]:
    body: dict[str, Any] = {
        "model": model,
        "stream": True,
        "messages": messages or [{"role": "user", "content": "load test question"}],
    }
    body.update(kwargs)
    chunks = []
    with client.stream("POST", "/v1/chat/completions", json=body) as response:
        assert response.status_code == 200
        for line in response.iter_lines():
            if line.startswith("data: ") and line != "data: [DONE]":
                chunks.append(json.loads(line[len("data: ") :]))
    return chunks


def assistant_tool_calls_message(name: str, arguments: str = "{}") -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "call_prev_1",
                "type": "function",
                "function": {"name": name, "arguments": arguments},
            }
        ],
    }


def test_plain_chat_no_tools_streams_text_with_stop() -> None:
    chunks = stream_chunks()
    finish = [
        c["choices"][0]["finish_reason"]
        for c in chunks
        if c["choices"][0]["finish_reason"]
    ]
    assert finish == ["stop"]
    text = "".join(c["choices"][0]["delta"].get("content") or "" for c in chunks)
    assert len(text.split()) == 20


def test_tool_choice_none_forces_text_even_with_tools() -> None:
    # Final chat cycle: tools offered but tool_choice="none" must yield text.
    choice = complete(tools=[INTERNAL_SEARCH_TOOL], tool_choice="none")
    assert choice["finish_reason"] == "stop"
    assert choice["message"]["content"]


def test_query_rephrase_flow_echoes_user_text() -> None:
    # Query rephrase/expansion output feeds back into retrieval as the search
    # query — detected by the prompt marker (Onyx's invoke() still streams at
    # the wire level, so the stream flag can't discriminate). The mock must
    # echo the question's terms, not return filler.
    question = "what is the onboarding process for new connectors?"
    messages = [
        {
            "role": "system",
            "content": "You are an assistant that reformulates the last user "
            "message into a standalone, self-contained query.",
        },
        {
            "role": "user",
            "content": f"Chat history above. Final user query:\n{question}",
        },
    ]
    chunks = stream_chunks(messages=messages)
    text = "".join(c["choices"][0]["delta"].get("content") or "" for c in chunks)
    assert question.split()[-3] in text  # echo contains the question's terms
    assert "deterministic mock answer" not in text

    choice = complete(messages=messages)  # non-streaming variant too
    assert "onboarding" in choice["message"]["content"]


def test_normal_answer_is_filler_not_echo() -> None:
    chunks = stream_chunks(
        messages=[{"role": "user", "content": "what is the onboarding process?"}]
    )
    text = "".join(c["choices"][0]["delta"].get("content") or "" for c in chunks)
    assert "deterministic mock answer" in text


def test_chat_auto_with_tools_knob_emits_internal_search_with_queries_array() -> None:
    chunks = stream_chunks(
        model="mock-tools1-ttft0-itl0",
        tools=[INTERNAL_SEARCH_TOOL],
        tool_choice="auto",
    )
    assert chunks[-1]["choices"][0]["finish_reason"] == "tool_calls"
    header = chunks[0]["choices"][0]["delta"]["tool_calls"][0]
    assert header["function"]["name"] == "internal_search"
    arguments = "".join(
        tc["function"].get("arguments", "")
        for c in chunks
        for tc in (c["choices"][0]["delta"].get("tool_calls") or [])
    )
    parsed = json.loads(arguments)
    assert isinstance(parsed["queries"], list) and parsed["queries"]


def test_multi_tool_knob_emits_parallel_retrieval_calls() -> None:
    # mock-tools3 + three retrieval tools offered → all three called in
    # parallel in one assistant message (multi-tool chat turn).
    choice = complete(
        model="mock-tools3-ttft0-itl0",
        tools=[INTERNAL_SEARCH_TOOL, WEB_SEARCH_TOOL, OPEN_URL_TOOL],
        tool_choice="auto",
    )
    assert choice["finish_reason"] == "tool_calls"
    names = [c["function"]["name"] for c in choice["message"]["tool_calls"]]
    assert names == ["internal_search", "web_search", "open_url"]


def test_multi_tool_knob_caps_at_offered_retrieval_tools() -> None:
    # mock-tools3 but only one retrieval tool offered → degrades to a single
    # call rather than inventing tools.
    choice = complete(
        model="mock-tools3-ttft0-itl0",
        tools=[INTERNAL_SEARCH_TOOL],
        tool_choice="auto",
    )
    calls = choice["message"]["tool_calls"]
    assert len(calls) == 1
    assert calls[0]["function"]["name"] == "internal_search"


def test_tools_knob_count_is_honored() -> None:
    # mock-tools2 picks exactly two of three offered retrieval tools.
    choice = complete(
        model="mock-tools2-ttft0-itl0",
        tools=[INTERNAL_SEARCH_TOOL, WEB_SEARCH_TOOL, OPEN_URL_TOOL],
        tool_choice="auto",
    )
    names = [c["function"]["name"] for c in choice["message"]["tool_calls"]]
    assert names == ["internal_search", "web_search"]


def test_chat_auto_after_tool_result_streams_final_answer() -> None:
    messages = [
        {"role": "user", "content": "find the docs"},
        assistant_tool_calls_message("internal_search", '{"queries": ["docs"]}'),
        {"role": "tool", "content": "doc snippets...", "tool_call_id": "call_prev_1"},
    ]
    choice = complete(
        model="mock-tools1-ttft0-itl0-len20",
        messages=messages,
        tools=[INTERNAL_SEARCH_TOOL],
        tool_choice="auto",
    )
    assert choice["finish_reason"] == "stop"
    assert choice["message"]["content"]


def test_chat_auto_without_knob_answers_directly() -> None:
    choice = complete(tools=[INTERNAL_SEARCH_TOOL], tool_choice="auto")
    assert choice["finish_reason"] == "stop"


def test_dr_clarification_always_calls_generate_plan() -> None:
    choice = complete(tools=[GENERATE_PLAN_TOOL], tool_choice="auto")
    assert choice["finish_reason"] == "tool_calls"
    assert choice["message"]["tool_calls"][0]["function"]["name"] == "generate_plan"


def test_dr_plan_call_is_plain_text() -> None:
    choice = complete(tools=[], tool_choice="none")
    assert choice["finish_reason"] == "stop"
    assert choice["message"]["content"]


def test_dr_orchestrator_first_cycle_spawns_research_agents() -> None:
    choice = complete(
        model="mock-agents2-ttft0-itl0",
        tools=[RESEARCH_AGENT_TOOL, GENERATE_REPORT_TOOL, THINK_TOOL],
        tool_choice="required",
    )
    assert choice["finish_reason"] == "tool_calls"
    calls = choice["message"]["tool_calls"]
    assert len(calls) == 2
    assert all(c["function"]["name"] == "research_agent" for c in calls)
    for c in calls:
        assert json.loads(c["function"]["arguments"])["task"]


def test_dr_orchestrator_second_cycle_generates_report() -> None:
    messages = [
        {"role": "user", "content": "research this"},
        assistant_tool_calls_message("research_agent", '{"task": "aspect 1"}'),
        {
            "role": "tool",
            "content": "intermediate report",
            "tool_call_id": "call_prev_1",
        },
    ]
    choice = complete(
        messages=messages,
        tools=[RESEARCH_AGENT_TOOL, GENERATE_REPORT_TOOL, THINK_TOOL],
        tool_choice="required",
    )
    assert choice["finish_reason"] == "tool_calls"
    assert choice["message"]["tool_calls"][0]["function"]["name"] == "generate_report"


def test_dr_research_agent_searches_then_reports() -> None:
    agent_tools = [INTERNAL_SEARCH_TOOL, GENERATE_REPORT_TOOL, THINK_TOOL]
    first = complete(tools=agent_tools, tool_choice="required")
    assert first["message"]["tool_calls"][0]["function"]["name"] == "internal_search"

    messages = [
        {"role": "user", "content": "research task"},
        assistant_tool_calls_message("internal_search", '{"queries": ["q"]}'),
        {"role": "tool", "content": "results", "tool_call_id": "call_prev_1"},
    ]
    second = complete(messages=messages, tools=agent_tools, tool_choice="required")
    assert second["message"]["tool_calls"][0]["function"]["name"] == "generate_report"


def test_forced_unknown_tool_returns_400() -> None:
    # Mirror OpenAI: forcing a function that isn't offered is a 400, not a
    # silent fallback — fallback would mask real contract violations.
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "mock-ttft0-itl0",
            "stream": False,
            "messages": [{"role": "user", "content": "q"}],
            "tools": [INTERNAL_SEARCH_TOOL],
            "tool_choice": {"type": "function", "function": {"name": "nonexistent"}},
        },
    )
    assert response.status_code == 400
    assert "nonexistent" in response.text


def test_forced_specific_tool_is_honored() -> None:
    choice = complete(
        tools=[INTERNAL_SEARCH_TOOL, GENERATE_REPORT_TOOL],
        tool_choice={"type": "function", "function": {"name": "generate_report"}},
    )
    assert choice["finish_reason"] == "tool_calls"
    assert choice["message"]["tool_calls"][0]["function"]["name"] == "generate_report"


def test_max_tokens_caps_answer_length() -> None:
    chunks = stream_chunks(model="mock-ttft0-itl0-len500", max_tokens=10)
    text = "".join(c["choices"][0]["delta"].get("content") or "" for c in chunks)
    assert len(text.split()) == 10


def test_maxctx_rejects_oversized_prompt_with_context_error() -> None:
    # Prompt over the maxctx limit → 400 context-window error (litellm maps
    # this to ContextWindowExceededError, mimicking a real provider).
    big = "word " * 5000  # ~25k chars ≈ ~6k tokens, over maxctx1000
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "mock-maxctx1000-ttft0-itl0",
            "stream": False,
            "messages": [{"role": "user", "content": big}],
        },
    )
    assert response.status_code == 400
    err = response.json()["error"]
    assert err["code"] == "context_length_exceeded"
    assert "maximum context length" in err["message"]


def test_maxctx_allows_small_prompt() -> None:
    choice = complete(model="mock-maxctx1000-ttft0-itl0-len10")
    assert choice["finish_reason"] == "stop"
