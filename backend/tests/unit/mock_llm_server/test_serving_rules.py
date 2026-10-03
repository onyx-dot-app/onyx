import subprocess
import sys
from collections.abc import Generator
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest

from tests.integration.common_utils.managers.mock_llm import MockLLMScript
from tests.integration.mock_services.mock_llm_server.models import (
    Reply,
    RequestConditions,
    Script,
    ToolCall,
)

DEFAULT_REPLY = "This is a mock LLM response."
TOOL_FREE = RequestConditions(has_tools=False)


def _body(
    user: str = "hello",
    tools: list[str] | None = None,
    tool_results: list[str] | None = None,
) -> dict[str, Any]:
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": "You are Onyx."},
        {"role": "user", "content": user},
    ]
    if tool_results:
        calls = [
            {
                "id": call_id,
                "type": "function",
                "function": {"name": "internal_search", "arguments": '{"q": 1}'},
            }
            for call_id in tool_results
        ]
        messages.append({"role": "assistant", "content": None, "tool_calls": calls})
        messages.extend(
            {"role": "tool", "tool_call_id": call_id, "content": f"result {call_id}"}
            for call_id in tool_results
        )
    body: dict[str, Any] = {"model": "mock-model", "messages": messages}
    if tools:
        body["tools"] = [{"type": "function", "function": {"name": n}} for n in tools]
        body["tool_choice"] = "auto"
    return body


def _send(script: MockLLMScript, body: dict[str, Any]) -> httpx.Response:
    return httpx.post(f"{script.api_base}/chat/completions", json=body)


def _text(script: MockLLMScript, body: dict[str, Any]) -> str | None:
    response = _send(script, body)
    assert response.status_code == 200, response.text
    return response.json()["choices"][0]["message"]["content"]


@pytest.fixture
def strict(mock_llm_server: str) -> Generator[MockLLMScript, None, None]:
    handle = MockLLMScript(mock_llm_server, uuid4().hex, Script(default_reply=None))
    try:
        yield handle
    finally:
        handle.close()


def test_conversation_serves_replies_in_order(strict: MockLLMScript) -> None:
    strict.conversation(
        "main", Reply(text="one"), Reply(text="two"), conditions=TOOL_FREE
    )

    assert _text(strict, _body()) == "one"
    assert _text(strict, _body()) == "two"
    assert _send(strict, _body()).status_code == 400
    assert [r.reply_index for r in strict.requests] == [0, 1, None]


def test_optional_reply_is_not_skipped_but_may_stay_unused(
    strict: MockLLMScript,
) -> None:
    strict.conversation(
        "clarify", Reply(text="clarify?", required=False), conditions=TOOL_FREE
    )
    strict.conversation(
        "main", Reply(text="answer"), conditions=RequestConditions(has_tools=True)
    )

    assert _text(strict, _body(tools=["internal_search"])) == "answer"
    strict.verify()


def test_tool_free_request_gets_the_default_reply_unless_the_reply_allows_it(
    script: MockLLMScript,
) -> None:
    script.conversation("any", Reply(text="scripted"))

    assert _text(script, _body()) == DEFAULT_REPLY
    assert _text(script, _body(tools=["internal_search"])) == "scripted"
    script.conversation(
        "tool-free", Reply(text="tool-free answer", conditions=TOOL_FREE)
    )
    assert _text(script, _body()) == "tool-free answer"

    default, scripted, tool_free = script.requests
    assert default.used_default_reply and default.is_tool_free
    assert default.conversation is None
    assert scripted.conversation == "any" and not scripted.used_default_reply
    assert tool_free.conversation == "tool-free"
    script.verify()


def test_unmatched_request_with_tools_gets_the_default_reply(
    script: MockLLMScript,
) -> None:
    script.conversation(
        "web", Reply(text="never"), conditions=RequestConditions(offers=["web"])
    )

    assert _text(script, _body(tools=["internal_search"])) == DEFAULT_REPLY
    with pytest.raises(AssertionError, match="unused conversation 'web' reply 0"):
        script.verify()


def test_different_responses_from_two_conversations_are_ambiguous(
    script: MockLLMScript,
) -> None:
    script.conversation(
        "a", Reply(text="from a"), conditions=RequestConditions(has_tools=True)
    )
    script.conversation(
        "b", Reply(text="from b"), conditions=RequestConditions(offers=["x"])
    )

    response = _send(script, _body(tools=["x"]))

    assert response.status_code == 400
    assert "more than one" in response.json()["error"]["message"]
    (request,) = script.requests
    assert request.error == "ambiguous: 'a' reply 0, 'b' reply 0"
    with pytest.raises(AssertionError, match="ambiguous"):
        script.verify()


def test_identical_responses_from_two_conversations_go_to_the_first(
    script: MockLLMScript,
) -> None:
    script.conversation(
        "a", Reply(text="same"), conditions=RequestConditions(has_tools=True)
    )
    script.conversation(
        "b", Reply(text="same"), conditions=RequestConditions(offers=["x"])
    )

    assert _text(script, _body(tools=["x"])) == "same"
    assert script.requests[0].conversation == "a"


def test_reply_when_and_prompt_contains(strict: MockLLMScript) -> None:
    strict.conversation(
        "main",
        Reply(text="first", conditions=RequestConditions(prompt_contains=["task X"])),
        Reply(text="second", conditions=RequestConditions(has_results_for=["c1"])),
        conditions=RequestConditions(offers=["internal_search"]),
    )

    assert _send(strict, _body(tools=["internal_search"])).status_code == 400
    assert _text(strict, _body("do task X", tools=["internal_search"])) == "first"
    assert (
        _text(strict, _body(tools=["internal_search"], tool_results=["c1"])) == "second"
    )
    with pytest.raises(AssertionError, match="no reply matched"):
        strict.verify()


def test_requests_are_recorded(script: MockLLMScript) -> None:
    call = ToolCall(id="c2", name="internal_search", arguments={"q": ["a"]})
    script.conversation(
        "main", Reply(tool_calls=[call]), conditions=RequestConditions(has_tools=True)
    )

    response = _send(script, _body(tools=["internal_search"], tool_results=["c1"]))

    message = response.json()["choices"][0]
    assert message["finish_reason"] == "tool_calls"
    assert message["message"]["tool_calls"][0]["function"]["arguments"] == (
        '{"q": ["a"]}'
    )
    (request,) = script.requests
    assert request.tools == ["internal_search"]
    assert request.tool_choice == "auto"
    assert request.tool_result("c1") == "result c1"
    assert request.tool_result_ids() == ["c1"]
    assert request.messages[2].tool_calls == [
        ToolCall(id="c1", name="internal_search", arguments={"q": 1})
    ]
    assert request.prompt_text == "You are Onyx.\nhello"
    assert request.body["model"] == "mock-model"
    assert script.requests_in("main") == [request]


def test_server_imports_no_onyx_modules() -> None:
    backend_dir = Path(__file__).resolve().parents[3]
    code = (
        "import sys\n"
        "import tests.integration.mock_services.mock_llm_server.server\n"
        "bad = [m for m in sys.modules if m.split('.')[0] in ('onyx', 'ee')]\n"
        "assert not bad, bad\n"
    )
    subprocess.run([sys.executable, "-c", code], cwd=backend_dir, check=True)
