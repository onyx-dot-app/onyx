from typing import Any

import pytest

from tests.integration.mock_services.mock_llm_server.handle import ScriptHandle
from tests.integration.mock_services.mock_llm_server.models import (
    Lane,
    Matcher,
    Script,
    Step,
    ToolCall,
)
from tests.integration.mock_services.mock_llm_server.registry import (
    ScriptRegistry,
    ServeResult,
)
from tests.integration.mock_services.mock_llm_server.responders import Builtin

SCRIPT_ID = "script-1"


def _body(
    user: str = "hello",
    system: str = "You are Onyx.",
    tools: list[str] | None = None,
    tool_results: list[str] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    if tool_results:
        messages.append(
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": call_id,
                        "type": "function",
                        "function": {"name": "internal_search", "arguments": "{}"},
                    }
                    for call_id in tool_results
                ],
            }
        )
        messages.extend(
            {"role": "tool", "tool_call_id": call_id, "content": f"result {call_id}"}
            for call_id in tool_results
        )
    body: dict[str, Any] = {"model": "mock-model", "messages": messages, "stream": True}
    if tools:
        body["tools"] = [
            {"type": "function", "function": {"name": name, "parameters": {}}}
            for name in tools
        ]
    body.update(extra)
    return body


@pytest.fixture
def handle() -> ScriptHandle:
    return ScriptHandle(ScriptRegistry(), SCRIPT_ID, "http://mock/v1")


def _serve(handle: ScriptHandle, body: dict[str, Any]) -> ServeResult:
    return handle.registry.serve(handle.script_id, body)


def _text(result: ServeResult) -> str | None:
    assert result.step is not None, result.client_error
    return result.step.text


def test_lane_serves_steps_in_order_then_stops_matching(handle: ScriptHandle) -> None:
    handle.lane("main", Step(text="one"), Step(text="two"))

    assert _text(_serve(handle, _body())) == "one"
    assert _text(_serve(handle, _body())) == "two"
    third = _serve(handle, _body())

    assert third.step is None
    assert third.client_error is not None
    assert "no scripted step matched request 2" in third.client_error
    assert [r.step_index for r in handle.requests] == [0, 1, None]


@pytest.mark.parametrize(
    "matcher,body,expected",
    [
        (Matcher(tools_offered=True), _body(tools=["internal_search"]), True),
        (Matcher(tools_offered=True), _body(), False),
        (Matcher(tools_offered=False), _body(), True),
        (Matcher(offered_tools=["a", "b"]), _body(tools=["a", "b", "c"]), True),
        (Matcher(offered_tools=["a", "b"]), _body(tools=["a"]), False),
        (Matcher(not_offered_tools=["research_agent"]), _body(tools=["a"]), True),
        (
            Matcher(not_offered_tools=["research_agent"]),
            _body(tools=["research_agent"]),
            False,
        ),
        (Matcher(tool_results_for=["c1"]), _body(tool_results=["c1", "c2"]), True),
        (Matcher(tool_results_for=["c3"]), _body(tool_results=["c1"]), False),
        (Matcher(tool_choice="required"), _body(tool_choice="required"), True),
        (Matcher(tool_choice="required"), _body(tool_choice="auto"), False),
        (
            Matcher(tool_choice="internal_search"),
            _body(
                tool_choice={
                    "type": "function",
                    "function": {"name": "internal_search"},
                }
            ),
            True,
        ),
        (
            Matcher(response_format="Answer"),
            _body(
                response_format={
                    "type": "json_schema",
                    "json_schema": {"name": "Answer"},
                }
            ),
            True,
        ),
        (
            Matcher(response_format="json_object"),
            _body(response_format={"type": "json_object"}),
            True,
        ),
        (Matcher(text_contains=["topic A"]), _body(user="research topic A"), True),
        (Matcher(text_contains=["topic A"]), _body(system="topic A system"), True),
        # Tool results are not prompt text.
        (Matcher(text_contains=["result c1"]), _body(tool_results=["c1"]), False),
    ],
)
def test_matcher(
    handle: ScriptHandle, matcher: Matcher, body: dict[str, Any], expected: bool
) -> None:
    handle.lane("main", Step(text="ok"), match=matcher)

    result = _serve(handle, body)

    assert (result.step is not None) is expected


def test_step_matcher_gates_the_next_step(handle: ScriptHandle) -> None:
    handle.lane(
        "main",
        Step(tool_calls=[ToolCall(id="c1", name="internal_search")]),
        Step(text="answer", match=Matcher(tool_results_for=["c1"])),
    )

    assert _serve(handle, _body()).step is not None
    assert _serve(handle, _body()).step is None
    assert _text(_serve(handle, _body(tool_results=["c1"]))) == "answer"


def test_lanes_route_parallel_requests_by_shape(handle: ScriptHandle) -> None:
    handle.lane("orchestrator", Step(text="orch"), match=Matcher(offered_tools=["r"]))
    handle.lane(
        "agent_a",
        Step(text="a"),
        match=Matcher(not_offered_tools=["r"], text_contains=["task A"]),
    )
    handle.lane(
        "agent_b",
        Step(text="b"),
        match=Matcher(not_offered_tools=["r"], text_contains=["task B"]),
    )

    assert _text(_serve(handle, _body(user="task B", tools=["s"]))) == "b"
    assert _text(_serve(handle, _body(user="task A", tools=["s"]))) == "a"
    assert _text(_serve(handle, _body(tools=["r"]))) == "orch"
    assert [r.lane for r in handle.requests] == ["agent_b", "agent_a", "orchestrator"]


def test_two_different_pending_steps_are_ambiguous(handle: ScriptHandle) -> None:
    handle.lane("first", Step(text="one"))
    handle.lane("second", Step(text="two"))

    result = _serve(handle, _body())

    assert result.step is None
    assert result.client_error is not None
    assert "matched more than one scripted step" in result.client_error
    (request,) = handle.requests
    assert request.error is not None and "'first'" in request.error
    assert handle.pending_required_steps() == [
        "lane 'first' step 0",
        "lane 'second' step 0",
    ]


def test_identical_pending_steps_are_not_ambiguous(handle: ScriptHandle) -> None:
    handle.lane("first", Step(text="same"))
    handle.lane("second", Step(text="same", required=False))

    assert _text(_serve(handle, _body())) == "same"
    assert _text(_serve(handle, _body())) == "same"
    assert [r.lane for r in handle.requests] == ["first", "second"]


def test_client_errors_never_quote_the_prompt(handle: ScriptHandle) -> None:
    handle.lane("reasoning_effort_temperature", Step(text="one"))
    handle.lane("thinking", Step(text="two"))

    ambiguous = _serve(handle, _body(user="SECRET"))
    handle.registry.remove(SCRIPT_ID)
    handle.registry.register(SCRIPT_ID)
    unmatched = _serve(handle, _body(user="SECRET"))

    for result in (ambiguous, unmatched):
        message = (result.client_error or "").lower()
        assert message
        for word in ("secret", "reasoning", "effort", "temperature", "thinking"):
            assert word not in message


def test_builtin_answers_without_consuming_steps(handle: ScriptHandle) -> None:
    handle.lane("main", Step(text="scripted"))

    builtin = _serve(
        handle,
        _body(
            system="You scope an internal search to a time filter, from the user's",
            user="",
        ),
    )

    assert _text(builtin) == "updated (None, None)"
    assert handle.requests[0].builtin == Builtin.TIME_FILTER
    assert handle.pending_required_steps() == ["lane 'main' step 0"]
    assert _text(_serve(handle, _body())) == "scripted"


def test_builtins_ignore_requests_that_offer_tools(handle: ScriptHandle) -> None:
    handle.lane("main", Step(text="scripted"))

    result = _serve(
        handle,
        _body(system="You are a summarization system.", tools=["internal_search"]),
    )

    assert _text(result) == "scripted"
    assert handle.requests[0].builtin is None


def test_builtin_override_and_disable(handle: ScriptHandle) -> None:
    summary_body = _body(system="You are a summarization system.")
    naming_body = _body(
        system="Given the history, provide a SHORT name for the conversation."
    )
    handle.set_builtin(Builtin.CHAT_HISTORY_SUMMARY, "custom summary")
    handle.disable_builtin(Builtin.CHAT_SESSION_NAMING)
    handle.lane(
        "naming", Step(text="Scripted Name"), match=Matcher(tools_offered=False)
    )

    assert _text(_serve(handle, summary_body)) == "custom summary"
    assert _text(_serve(handle, naming_body)) == "Scripted Name"
    assert handle.builtin_requests() == handle.requests[:1]
    assert handle.lane_requests("naming") == handle.requests[1:]


def test_unknown_builtin_names_are_rejected(handle: ScriptHandle) -> None:
    with pytest.raises(ValueError):
        handle.set_builtin("not_a_builtin", "x")
    with pytest.raises(ValueError):
        ScriptRegistry().register("s", Script(disabled_builtins={"nope"}))


def test_recording(handle: ScriptHandle) -> None:
    handle.lane("main", Step(text="ok"))
    body = _body(tools=["internal_search"], tool_results=["c1"], tool_choice="auto")
    body["messages"][1]["content"] = [
        {"type": "text", "text": "look at"},
        {"type": "image_url", "image_url": {"url": "data:"}},
        {"type": "text", "text": "this"},
    ]
    body["stream_options"] = {"include_usage": True}
    body["max_tokens"] = 1024

    _serve(handle, body)

    (request,) = handle.requests
    assert request.script_id == SCRIPT_ID
    assert request.stream and request.include_usage
    assert request.tools == ["internal_search"]
    assert request.tool_choice == "auto"
    assert request.max_tokens == 1024
    assert request.messages[1].content == "look at\nthis"
    assert request.messages[2].tool_calls[0].id == "c1"
    assert request.tool_result("c1") == "result c1"
    assert request.tool_result_ids() == ["c1"]
    assert request.raw_body == body
    assert (request.lane, request.step_index, request.builtin) == ("main", 0, None)


def test_verify_reports_unmatched_requests_and_pending_steps(
    handle: ScriptHandle,
) -> None:
    handle.lane(
        "main",
        Step(text="needed"),
        Step(text="optional", required=False),
        match=Matcher(tools_offered=False),
    )
    handle.lane("other", Step(text="x"), match=Matcher(offered_tools=["t"]))

    _serve(handle, _body())
    _serve(handle, _body(user="stray", tools=["u"]))

    with pytest.raises(AssertionError) as exc_info:
        handle.verify()
    assert "request 1" in str(exc_info.value)
    assert "unconsumed lane 'other' step 0" in str(exc_info.value)
    assert "optional" not in str(exc_info.value)


def test_scripts_are_isolated() -> None:
    registry = ScriptRegistry()
    first = ScriptHandle(registry, "a", "http://mock/a")
    second = ScriptHandle(registry, "b", "http://mock/b")
    first.lane("main", Step(text="from a"))

    assert _text(registry.serve("a", _body())) == "from a"
    assert registry.serve("b", _body()).step is None
    assert len(first.requests) == 1 and len(second.requests) == 1

    first.close()
    gone = registry.serve("a", _body())
    assert gone.request is None and gone.client_error is not None


def test_lane_names_must_be_unique(handle: ScriptHandle) -> None:
    handle.lane("main", Step(text="x"))
    with pytest.raises(ValueError):
        handle.add_lane(Lane(name="main", steps=[]))
    with pytest.raises(ValueError):
        handle.registry.register(SCRIPT_ID)


def test_extend_lane_appends_steps(handle: ScriptHandle) -> None:
    handle.lane("main", Step(text="one"))
    handle.extend_lane("main", Step(text="two"))

    assert _text(_serve(handle, _body())) == "one"
    assert _text(_serve(handle, _body())) == "two"
