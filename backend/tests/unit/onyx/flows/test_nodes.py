"""Node executors, exercised against fakes rather than the network."""

import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest

from onyx.db.enums import FlowErrorClass
from onyx.flows.expressions import RunContext
from onyx.flows.models import parse_spec
from onyx.flows.nodes import NodeRuntime
from onyx.flows.nodes.ai import execute_ai
from onyx.flows.nodes.base import NodeExecutionError
from onyx.flows.nodes.condition import execute_condition
from onyx.flows.nodes.http import execute_http


def only_node(raw: dict) -> Any:
    return parse_spec({"start": raw["id"], "nodes": [raw]}).nodes[0]


def runtime_with(handler: Any) -> NodeRuntime:
    return NodeRuntime(
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        llm_provider=MagicMock(),
    )


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------


def test_http_returns_status_headers_and_parsed_body() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/issues"
        return httpx.Response(200, json={"items": [1, 2]})

    node = only_node({"id": "fetch", "kind": "HTTP", "url": "https://api.test/issues"})

    outcome = execute_http(node, RunContext(), runtime_with(handler))

    assert outcome.output["status"] == 200
    assert outcome.output["body"] == {"items": [1, 2]}
    assert outcome.output["headers"]["content-type"].startswith("application/json")


def test_http_interpolates_url_headers_and_body() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        return httpx.Response(201, json={"ok": True})

    node = only_node(
        {
            "id": "create",
            "kind": "HTTP",
            "method": "POST",
            "url": "https://api.test/repos/{{ trigger.repo }}/issues",
            "headers": {"Authorization": "Bearer {{ trigger.token }}"},
            "query": {"draft": "{{ trigger.draft }}"},
            "body": {"title": "{{ trigger.title }}", "labels": ["bug"]},
        }
    )
    context = RunContext(
        trigger={"repo": "onyx", "token": "t0ken", "title": "It broke", "draft": False}
    )

    execute_http(node, context, runtime_with(handler))

    assert seen["url"] == "https://api.test/repos/onyx/issues?draft=false"
    assert seen["auth"] == "Bearer t0ken"
    assert seen["body"] == {"title": "It broke", "labels": ["bug"]}


def test_http_result_path_narrows_the_output() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": {"rows": [{"id": 7}]}})

    node = only_node(
        {
            "id": "fetch",
            "kind": "HTTP",
            "url": "https://api.test/x",
            "result_path": "data.rows",
        }
    )

    outcome = execute_http(node, RunContext(), runtime_with(handler))

    assert outcome.output == [{"id": 7}]


def test_http_raises_on_error_status_by_default() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"message": "no such repo"})

    node = only_node({"id": "fetch", "kind": "HTTP", "url": "https://api.test/x"})

    with pytest.raises(NodeExecutionError) as caught:
        execute_http(node, RunContext(), runtime_with(handler))

    assert caught.value.error_class == FlowErrorClass.HTTP_ERROR
    assert "404" in caught.value.detail
    assert "no such repo" in caught.value.detail


def test_http_can_branch_on_status_instead_of_raising() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="slow down")

    node = only_node(
        {
            "id": "fetch",
            "kind": "HTTP",
            "url": "https://api.test/x",
            "fail_on_error_status": False,
        }
    )

    outcome = execute_http(node, RunContext(), runtime_with(handler))

    assert outcome.output["status"] == 429


def test_http_timeout_is_reported_as_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("too slow", request=request)

    node = only_node({"id": "fetch", "kind": "HTTP", "url": "https://api.test/x"})

    with pytest.raises(NodeExecutionError) as caught:
        execute_http(node, RunContext(), runtime_with(handler))

    assert caught.value.error_class == FlowErrorClass.TIMEOUT


def test_http_drops_set_cookie_from_recorded_headers() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={}, headers={"set-cookie": "session=secret", "etag": "abc"}
        )

    node = only_node({"id": "fetch", "kind": "HTTP", "url": "https://api.test/x"})

    outcome = execute_http(node, RunContext(), runtime_with(handler))

    assert "etag" in outcome.output["headers"]
    assert "set-cookie" not in outcome.output["headers"]


def test_http_url_is_ssrf_checked() -> None:
    """The guard lives on the transport, so every hop is validated."""
    from onyx.flows.nodes.http import FlowSSRFTransport

    transport = FlowSSRFTransport()
    request = httpx.Request("GET", "http://169.254.169.254/latest/meta-data/")

    with patch("onyx.flows.nodes.http.validate_flow_outbound_url") as guard:
        guard.side_effect = AssertionError("guard ran")
        with pytest.raises(AssertionError, match="guard ran"):
            transport.handle_request(request)


# ---------------------------------------------------------------------------
# Condition
# ---------------------------------------------------------------------------


def condition_node(**overrides: Any) -> Any:
    node = {
        "id": "check",
        "kind": "CONDITION",
        "left": "{{ trigger.value }}",
        "operator": "eq",
        "right": "10",
    }
    node.update(overrides)
    # Branch targets have to exist for the spec to validate, so stub in any
    # the caller named.
    targets = [*node.get("on_true", []), *node.get("on_false", [])]
    spec = parse_spec(
        {
            "start": "check",
            "nodes": [
                node,
                *(
                    {"id": target, "kind": "TRANSFORM", "fields": {"v": "1"}}
                    for target in targets
                ),
            ],
        }
    )
    return spec.nodes[0]


@pytest.mark.parametrize(
    "operator, left, right, expected",
    [
        ("eq", 10, "10", True),
        ("eq", "10", "10", True),
        ("eq", "abc", "abc", True),
        ("eq", True, "true", True),
        ("ne", 10, "11", True),
        ("gt", 11, "10", True),
        ("gt", 9, "10", False),
        ("gte", 10, "10", True),
        ("lt", 9, "10", True),
        ("lte", 10, "10", True),
        ("gt", "b", "a", True),
        ("contains", ["a", "b"], "b", True),
        ("contains", "hello world", "world", True),
        ("contains", {"key": 1}, "key", True),
        ("not_contains", ["a"], "b", True),
    ],
)
def test_condition_operators(
    operator: str, left: Any, right: Any, expected: bool
) -> None:
    node = condition_node(operator=operator, right=right)
    context = RunContext(trigger={"value": left})

    outcome = execute_condition(node, context, MagicMock())

    assert outcome.output["matched"] is expected


@pytest.mark.parametrize(
    "value, expected",
    [
        (None, True),
        ("", True),
        ([], True),
        ({}, True),
        ("x", False),
        ([1], False),
        (0, False),
    ],
)
def test_is_empty(value: Any, expected: bool) -> None:
    node = condition_node(operator="is_empty", right=None)
    outcome = execute_condition(node, RunContext(trigger={"value": value}), MagicMock())
    assert outcome.output["matched"] is expected


def test_condition_hands_control_to_the_chosen_branch() -> None:
    node = condition_node(on_true=["yes"], on_false=["no"], right="10")
    outcome = execute_condition(node, RunContext(trigger={"value": 10}), MagicMock())
    assert outcome.next_ids == ["yes"]

    outcome = execute_condition(node, RunContext(trigger={"value": 1}), MagicMock())
    assert outcome.next_ids == ["no"]


def test_condition_records_both_operands() -> None:
    """So nobody has to guess why the run went the way it did."""
    node = condition_node(right="10")
    outcome = execute_condition(node, RunContext(trigger={"value": 3}), MagicMock())
    assert outcome.output == {"matched": False, "left": 3, "right": "10"}


def test_ordering_an_object_is_an_error() -> None:
    node = condition_node(operator="gt", right="10")
    with pytest.raises(NodeExecutionError, match="order-compare"):
        execute_condition(node, RunContext(trigger={"value": {"a": 1}}), MagicMock())


# ---------------------------------------------------------------------------
# AI
# ---------------------------------------------------------------------------


def stub_llm(*replies: str) -> MagicMock:
    llm = MagicMock()
    llm.invoke.side_effect = [
        SimpleNamespace(choice=SimpleNamespace(message=SimpleNamespace(content=reply)))
        for reply in replies
    ]
    return llm


def ai_runtime(llm: MagicMock) -> NodeRuntime:
    return NodeRuntime(http_client=MagicMock(), llm_provider=lambda: llm)


def ai_node(**overrides: Any) -> Any:
    node = {
        "id": "decide",
        "kind": "AI",
        "prompt": "Who owns this?",
        "output_fields": [
            {"name": "team", "type": "text"},
            {"name": "confidence", "type": "number"},
            {"name": "urgent", "type": "boolean"},
        ],
    }
    node.update(overrides)
    return only_node(node)


def test_ai_returns_declared_fields_at_declared_types() -> None:
    llm = stub_llm('{"team": "payments", "confidence": 0.82, "urgent": false}')

    outcome = execute_ai(ai_node(), RunContext(), ai_runtime(llm))

    assert outcome.output == {
        "team": "payments",
        "confidence": 0.82,
        "urgent": False,
    }


def test_ai_prompt_is_interpolated() -> None:
    llm = stub_llm('{"team": "x", "confidence": 1, "urgent": true}')
    node = ai_node(prompt="Who owns {{ trigger.bug }}?")

    execute_ai(node, RunContext(trigger={"bug": "checkout 500s"}), ai_runtime(llm))

    sent = llm.invoke.call_args.kwargs["prompt"].content
    assert "Who owns checkout 500s?" in sent


def test_ai_coerces_stringly_typed_answers() -> None:
    """Models reply "0.8" and "yes" constantly; that is not worth failing a run."""
    llm = stub_llm('{"team": "ops", "confidence": "0.8", "urgent": "yes"}')

    outcome = execute_ai(ai_node(), RunContext(), ai_runtime(llm))

    assert outcome.output == {"team": "ops", "confidence": 0.8, "urgent": True}


def test_ai_drops_fields_nobody_asked_for() -> None:
    llm = stub_llm(
        '{"team": "ops", "confidence": 1, "urgent": false, "reasoning": "because"}'
    )

    outcome = execute_ai(ai_node(), RunContext(), ai_runtime(llm))

    assert "reasoning" not in outcome.output


def test_ai_reads_through_a_code_fence() -> None:
    llm = stub_llm(
        'Sure!\n```json\n{"team": "ops", "confidence": 1, "urgent": false}\n```'
    )

    outcome = execute_ai(ai_node(), RunContext(), ai_runtime(llm))

    assert outcome.output["team"] == "ops"


def test_ai_retries_once_when_a_field_is_missing() -> None:
    llm = stub_llm(
        '{"team": "ops"}',
        '{"team": "ops", "confidence": 0.5, "urgent": false}',
    )

    outcome = execute_ai(ai_node(), RunContext(), ai_runtime(llm))

    assert llm.invoke.call_count == 2
    assert outcome.output["confidence"] == 0.5
    retry_prompt = llm.invoke.call_args_list[1].kwargs["prompt"].content
    assert "'confidence' was missing" in retry_prompt


def test_ai_gives_up_after_the_retry() -> None:
    llm = stub_llm("not json at all", "still not json")

    with pytest.raises(NodeExecutionError) as caught:
        execute_ai(ai_node(), RunContext(), ai_runtime(llm))

    assert caught.value.error_class == FlowErrorClass.OUTPUT_MISMATCH
    assert llm.invoke.call_count == 2


def test_ai_without_declared_fields_returns_text() -> None:
    llm = stub_llm("a plain sentence")

    outcome = execute_ai(ai_node(output_fields=[]), RunContext(), ai_runtime(llm))

    assert outcome.output == {"text": "a plain sentence"}
    assert llm.invoke.call_count == 1


def test_ai_model_failure_is_reported_as_llm_error() -> None:
    llm = MagicMock()
    llm.invoke.side_effect = RuntimeError("provider down")

    with pytest.raises(NodeExecutionError) as caught:
        execute_ai(ai_node(), RunContext(), ai_runtime(llm))

    assert caught.value.error_class == FlowErrorClass.LLM_ERROR
    assert "provider down" in caught.value.detail
