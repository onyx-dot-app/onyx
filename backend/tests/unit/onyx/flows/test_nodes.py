"""Node executors, exercised against fakes rather than the network."""

import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest

from onyx.db.enums import FlowErrorClass, FlowRunStatus
from onyx.flows.engine import RETRYABLE_ERROR_CLASSES
from onyx.flows.expressions import RunContext
from onyx.flows.models import MAX_FAN_OUT_ITEMS, parse_spec
from onyx.flows.nodes import NodeRuntime
from onyx.flows.nodes.ai import execute_ai
from onyx.flows.nodes.base import NodeExecutionError, NodeSuspended
from onyx.flows.nodes.code import MAX_CONTEXT_BYTES, RESULT_MARKER, execute_code
from onyx.flows.nodes.condition import execute_condition
from onyx.flows.nodes.delay import execute_delay
from onyx.flows.nodes.filter import execute_filter
from onyx.flows.nodes.http import execute_http
from onyx.flows.nodes.human import execute_human, resume_human
from onyx.flows.nodes.loop import execute_loop
from onyx.flows.nodes.retry import execute_retry
from onyx.flows.nodes.webhook import (
    SIGNATURE_HEADER,
    TIMESTAMP_HEADER,
    execute_webhook,
    sign_payload,
)
from onyx.tools.tool_implementations.python.code_interpreter_client import (
    ExecuteResponse,
)


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


# ---------------------------------------------------------------------------
# Loop
# ---------------------------------------------------------------------------


def loop_node(**overrides: Any) -> Any:
    node: dict[str, Any] = {"id": "chunk", "kind": "LOOP", "over": "{{ trigger.rows }}"}
    node.update(overrides)
    return only_node(node)


def test_loop_cuts_the_list_into_batches() -> None:
    context = RunContext(trigger={"rows": [1, 2, 3, 4, 5]})

    outcome = execute_loop(loop_node(batch_size=2), context, MagicMock())

    assert outcome.output == {
        "batches": [[1, 2], [3, 4], [5]],
        "batch_count": 3,
        "total": 5,
    }


def test_loop_over_nothing_is_an_empty_run_not_an_error() -> None:
    outcome = execute_loop(loop_node(), RunContext(trigger={"rows": None}), MagicMock())

    assert outcome.output == {"batches": [], "batch_count": 0, "total": 0}


def test_loop_wraps_a_lone_object() -> None:
    context = RunContext(trigger={"rows": {"id": 7}})

    outcome = execute_loop(loop_node(), context, MagicMock())

    assert outcome.output["batches"] == [[{"id": 7}]]


def test_loop_rejects_a_value_that_is_not_a_list() -> None:
    context = RunContext(trigger={"rows": "one, two"})

    with pytest.raises(NodeExecutionError) as caught:
        execute_loop(loop_node(), context, MagicMock())

    assert caught.value.error_class == FlowErrorClass.EXPRESSION_ERROR
    assert "got str" in caught.value.detail


def test_loop_refuses_more_items_than_the_fan_out_limit() -> None:
    context = RunContext(trigger={"rows": list(range(MAX_FAN_OUT_ITEMS + 1))})

    with pytest.raises(NodeExecutionError) as caught:
        execute_loop(loop_node(batch_size=10), context, MagicMock())

    assert caught.value.error_class == FlowErrorClass.INVALID_SPEC


# ---------------------------------------------------------------------------
# Human
# ---------------------------------------------------------------------------


def human_node(**overrides: Any) -> Any:
    node: dict[str, Any] = {
        "id": "gate",
        "kind": "HUMAN",
        "question": "Ship {{ trigger.tag }}?",
    }
    node.update(overrides)
    return only_node(node)


def test_human_parks_the_run_with_the_question_filled_in() -> None:
    context = RunContext(trigger={"tag": "v2.1"})

    with pytest.raises(NodeSuspended) as caught:
        execute_human(human_node(assignee="ada@example.com"), context, MagicMock())

    assert caught.value.node_id == "gate"
    assert caught.value.detail == {
        "question": "Ship v2.1?",
        "assignee": "ada@example.com",
    }


def test_human_reports_an_unresolvable_question_rather_than_parking() -> None:
    with pytest.raises(NodeExecutionError) as caught:
        execute_human(human_node(), RunContext(trigger={}), MagicMock())

    assert caught.value.error_class == FlowErrorClass.EXPRESSION_ERROR


def branching_human(**overrides: Any) -> Any:
    """An approval wired to two real nodes, since a branch needs somewhere to go."""
    gate: dict[str, Any] = {"id": "gate", "kind": "HUMAN", "question": "ok?"}
    gate.update(overrides)
    return parse_spec(
        {
            "start": "gate",
            "nodes": [
                gate,
                {"id": "ship", "kind": "TRANSFORM", "fields": {"a": "ship"}},
                {"id": "tell", "kind": "TRANSFORM", "fields": {"a": "tell"}},
            ],
        }
    ).nodes[0]


def test_approval_resumes_down_the_approve_branch() -> None:
    node = branching_human(on_approve=["ship"], on_reject=["tell"])

    outcome = resume_human(node, {"decision": "approve", "comment": None})

    assert outcome.next_ids == ["ship"]
    assert outcome.output["decision"] == "approve"


def test_rejection_takes_the_reject_branch_when_there_is_one() -> None:
    node = branching_human(on_approve=["ship"], on_reject=["tell"])

    outcome = resume_human(node, {"decision": "reject", "comment": "too risky"})

    assert outcome.next_ids == ["tell"]


def test_rejecting_a_bare_gate_fails_the_run_with_the_comment() -> None:
    """Nothing wired to a rejection means the rejection is the outcome."""
    with pytest.raises(NodeExecutionError) as caught:
        resume_human(human_node(), {"decision": "reject", "comment": "not yet"})

    assert caught.value.error_class == FlowErrorClass.DECISION_REJECTED
    assert caught.value.detail == "rejected: not yet"


def test_an_unreadable_decision_is_an_error_not_a_branch() -> None:
    with pytest.raises(NodeExecutionError) as caught:
        resume_human(human_node(), {"decision": "maybe"})

    assert caught.value.error_class == FlowErrorClass.NODE_EXCEPTION


# ---------------------------------------------------------------------------
# Code
# ---------------------------------------------------------------------------


class LocalSandbox:
    """Stands in for the code interpreter by running the program locally.

    Not isolation — isolation is the real service's job — but it does run the
    exact program the node builds, so the wrapper, the stdin handover and the
    marked result line are all under test rather than assumed.
    """

    def __init__(self) -> None:
        self.last_stdin: str | None = None
        self.last_files: Any = None
        self.closed = False

    def execute(
        self,
        code: str,
        stdin: str | None = None,
        timeout_ms: int = 30000,
        files: Any = None,
    ) -> ExecuteResponse:
        self.last_stdin = stdin
        self.last_files = files
        started = time.monotonic()
        try:
            finished = subprocess.run(
                [sys.executable, "-c", code],
                input=stdin or "",
                capture_output=True,
                text=True,
                timeout=timeout_ms / 1000,
            )
        except subprocess.TimeoutExpired:
            return ExecuteResponse(
                stdout="",
                stderr="",
                exit_code=None,
                timed_out=True,
                duration_ms=timeout_ms,
                files=[],
            )
        return ExecuteResponse(
            stdout=finished.stdout,
            stderr=finished.stderr,
            exit_code=finished.returncode,
            timed_out=False,
            duration_ms=int((time.monotonic() - started) * 1000),
            files=[],
        )

    def close(self) -> None:
        self.closed = True


def code_node(code: str, **overrides: Any) -> Any:
    node: dict[str, Any] = {"id": "calc", "kind": "CODE", "code": code}
    node.update(overrides)
    return only_node(node)


def sandbox_runtime(sandbox: Any) -> NodeRuntime:
    return NodeRuntime(
        http_client=MagicMock(),
        llm_provider=MagicMock(),
        code_runner_provider=lambda: sandbox,
    )


def test_code_reads_the_run_and_returns_its_result() -> None:
    node = code_node(
        "rows = steps['fetch']['rows']\n"
        "result = {'total': sum(rows), 'tag': trigger['tag']}"
    )
    context = RunContext(trigger={"tag": "v9"}, steps={"fetch": {"rows": [1, 2, 3]}})

    outcome = execute_code(node, context, sandbox_runtime(LocalSandbox()))

    assert outcome.output == {"result": {"total": 6, "tag": "v9"}, "logs": ""}


def test_code_keeps_printed_output_as_logs() -> None:
    node = code_node("print('halfway')\nprint('done')\nresult = 1")

    outcome = execute_code(node, RunContext(), sandbox_runtime(LocalSandbox()))

    assert outcome.output == {"result": 1, "logs": "halfway\ndone"}


def test_code_sees_the_fan_out_item() -> None:
    node = code_node("result = f'{index}:{item}'")
    context = RunContext().for_item("beta", 1)

    outcome = execute_code(node, context, sandbox_runtime(LocalSandbox()))

    assert outcome.output["result"] == "1:beta"


def test_a_snippet_printing_the_marker_cannot_displace_the_real_result() -> None:
    node = code_node(f"print('{RESULT_MARKER} 99')\nresult = 'real'")

    outcome = execute_code(node, RunContext(), sandbox_runtime(LocalSandbox()))

    assert outcome.output["result"] == "real"


def test_code_failure_reports_the_authors_own_line_number() -> None:
    node = code_node("rows = [1, 2]\ntotal = rows['nope']")

    with pytest.raises(NodeExecutionError) as caught:
        execute_code(node, RunContext(), sandbox_runtime(LocalSandbox()))

    assert caught.value.error_class == FlowErrorClass.CODE_ERROR
    assert 'File "<flow code step>", line 2' in caught.value.detail
    assert "exec(compile(" not in caught.value.detail, "wrapper frame leaked"


def test_code_that_runs_long_is_reported_as_a_timeout() -> None:
    node = code_node("import time\ntime.sleep(5)", timeout_seconds=0.3)

    with pytest.raises(NodeExecutionError) as caught:
        execute_code(node, RunContext(), sandbox_runtime(LocalSandbox()))

    assert caught.value.error_class == FlowErrorClass.TIMEOUT


def test_an_unreachable_sandbox_is_retryable() -> None:
    sandbox = MagicMock()
    sandbox.execute.side_effect = ConnectionError("connection refused")

    with pytest.raises(NodeExecutionError) as caught:
        execute_code(code_node("result = 1"), RunContext(), sandbox_runtime(sandbox))

    assert caught.value.error_class in RETRYABLE_ERROR_CLASSES


def test_an_unconfigured_sandbox_says_so_plainly() -> None:
    def refuse() -> Any:
        raise ValueError("CODE_INTERPRETER_BASE_URL not configured")

    runtime = NodeRuntime(
        http_client=MagicMock(),
        llm_provider=MagicMock(),
        code_runner_provider=refuse,
    )

    with pytest.raises(NodeExecutionError) as caught:
        execute_code(code_node("result = 1"), RunContext(), runtime)

    assert caught.value.error_class == FlowErrorClass.CODE_ERROR
    assert "CODE_INTERPRETER_BASE_URL" in caught.value.detail


def test_code_refuses_a_run_too_large_to_hand_over() -> None:
    node = code_node("result = 1")
    context = RunContext(steps={"fetch": {"blob": "x" * (MAX_CONTEXT_BYTES + 1)}})

    with pytest.raises(NodeExecutionError) as caught:
        execute_code(node, context, sandbox_runtime(LocalSandbox()))

    assert caught.value.error_class == FlowErrorClass.CODE_ERROR
    assert "narrow the earlier steps" in caught.value.detail


def test_the_runtime_closes_the_sandbox_it_opened() -> None:
    sandbox = LocalSandbox()
    runtime = sandbox_runtime(sandbox)
    runtime.code_runner()

    runtime.close()

    assert sandbox.closed is True


# ---------------------------------------------------------------------------
# Retry
# ---------------------------------------------------------------------------


def retry_node(**overrides: Any) -> Any:
    node: dict[str, Any] = {
        "id": "poll",
        "kind": "RETRY",
        "url": "https://api.test/jobs/1",
        "until_path": "state",
        "operator": "eq",
        "value": "done",
        "interval_seconds": 0,
    }
    node.update(overrides)
    return only_node(node)


def responder(states: list[Any]) -> Any:
    """Answers each call with the next state, repeating the last one."""
    calls = {"count": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        index = min(calls["count"], len(states) - 1)
        calls["count"] += 1
        return httpx.Response(200, json={"state": states[index]})

    handler.calls = calls  # ty: ignore[unresolved-attribute]
    return handler


def test_retry_stops_as_soon_as_the_check_passes() -> None:
    handler = responder(["queued", "running", "done", "done"])

    outcome = execute_retry(retry_node(), RunContext(), runtime_with(handler))

    assert outcome.output["satisfied"] is True
    assert outcome.output["checks"] == 3
    assert outcome.output["result"]["body"] == {"state": "done"}
    assert handler.calls["count"] == 3, "kept polling after the answer arrived"


def test_retry_gives_up_and_fails_by_default() -> None:
    handler = responder(["running"])

    with pytest.raises(NodeExecutionError) as caught:
        execute_retry(retry_node(max_checks=3), RunContext(), runtime_with(handler))

    assert caught.value.error_class == FlowErrorClass.RETRY_EXHAUSTED
    assert handler.calls["count"] == 3


def test_retry_can_carry_on_after_giving_up() -> None:
    """Turning the failure off is what lets a flow branch on the outcome."""
    handler = responder(["running"])

    outcome = execute_retry(
        retry_node(max_checks=2, fail_when_exhausted=False),
        RunContext(),
        runtime_with(handler),
    )

    assert outcome.output["satisfied"] is False
    assert outcome.output["checks"] == 2
    assert outcome.output["result"]["body"] == {"state": "running"}


def test_a_path_that_is_not_there_yet_counts_as_not_yet() -> None:
    """An endpoint that omits the field until the job starts is answering."""
    handler = responder([{}, {}, "done"])

    def shaped(request: httpx.Request) -> httpx.Response:
        response = handler(request)
        body = response.json()["state"]
        return httpx.Response(200, json={} if body == {} else {"state": body})

    outcome = execute_retry(retry_node(), RunContext(), runtime_with(shaped))

    assert outcome.output["satisfied"] is True
    assert outcome.output["checks"] == 3


def test_retry_compares_against_a_resolved_expression() -> None:
    handler = responder(["v9"])
    context = RunContext(trigger={"tag": "v9"})

    outcome = execute_retry(
        retry_node(value="{{ trigger.tag }}"), context, runtime_with(handler)
    )

    assert outcome.output["satisfied"] is True
    assert handler.calls["count"] == 1


# ---------------------------------------------------------------------------
# Webhook
# ---------------------------------------------------------------------------


def webhook_node(**overrides: Any) -> Any:
    node: dict[str, Any] = {
        "id": "notify",
        "kind": "WEBHOOK",
        "url": "https://hooks.test/incoming",
        "payload": {"tag": "{{ trigger.tag }}", "count": "{{ trigger.count }}"},
    }
    node.update(overrides)
    return only_node(node)


def webhook_context() -> RunContext:
    """Whatever the default payload's expressions need."""
    return RunContext(trigger={"tag": "v2", "count": 7})


def capturing_runtime(
    status: int = 200, secret: str | None = "s3cret"
) -> tuple[NodeRuntime, dict[str, Any]]:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["url"] = str(request.url)
        seen["headers"] = dict(request.headers)
        seen["body"] = request.content.decode()
        return httpx.Response(status, text="thanks")

    runtime = NodeRuntime(
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        llm_provider=MagicMock(),
        webhook_signing_secret=secret,
    )
    return runtime, seen


def test_webhook_posts_the_resolved_payload_as_json() -> None:
    runtime, seen = capturing_runtime()

    outcome = execute_webhook(webhook_node(), webhook_context(), runtime)

    assert seen["method"] == "POST"
    assert json.loads(seen["body"]) == {"tag": "v2", "count": 7}
    assert seen["headers"]["content-type"] == "application/json"
    assert outcome.output["delivered"] is True
    assert outcome.output["response"] == "thanks"


def test_a_receiver_can_verify_what_was_sent() -> None:
    """The signature is over the timestamp and the exact bytes delivered."""
    runtime, seen = capturing_runtime(secret="top-secret")

    outcome = execute_webhook(webhook_node(), webhook_context(), runtime)

    timestamp = int(seen["headers"][TIMESTAMP_HEADER.lower()])
    expected = sign_payload("top-secret", timestamp, seen["body"])
    assert seen["headers"][SIGNATURE_HEADER.lower()] == expected
    assert outcome.output["signed"] is True


def test_a_tampered_body_does_not_verify() -> None:
    runtime, seen = capturing_runtime(secret="top-secret")

    execute_webhook(webhook_node(), webhook_context(), runtime)

    timestamp = int(seen["headers"][TIMESTAMP_HEADER.lower()])
    tampered = sign_payload("top-secret", timestamp, seen["body"] + " ")
    assert seen["headers"][SIGNATURE_HEADER.lower()] != tampered


def test_a_replayed_delivery_does_not_verify_under_a_new_timestamp() -> None:
    """Signing the timestamp is what makes a captured delivery worthless."""
    runtime, seen = capturing_runtime(secret="top-secret")

    execute_webhook(webhook_node(), webhook_context(), runtime)

    timestamp = int(seen["headers"][TIMESTAMP_HEADER.lower()])
    assert (
        sign_payload("top-secret", timestamp + 1, seen["body"])
        != (seen["headers"][SIGNATURE_HEADER.lower()])
    )


def test_a_flow_with_no_secret_still_delivers_unsigned() -> None:
    runtime, seen = capturing_runtime(secret=None)

    outcome = execute_webhook(webhook_node(), webhook_context(), runtime)

    assert SIGNATURE_HEADER.lower() not in seen["headers"]
    assert outcome.output["signed"] is False
    assert outcome.output["delivered"] is True


def test_a_receiver_being_down_does_not_stop_the_run() -> None:
    runtime, _ = capturing_runtime(status=503)

    outcome = execute_webhook(webhook_node(), webhook_context(), runtime)

    assert outcome.output["delivered"] is False
    assert outcome.output["status"] == 503


def test_a_receiver_being_down_can_be_made_to_stop_the_run() -> None:
    runtime, _ = capturing_runtime(status=503)

    with pytest.raises(NodeExecutionError) as caught:
        execute_webhook(
            webhook_node(fail_on_error_status=True), webhook_context(), runtime
        )

    assert caught.value.error_class == FlowErrorClass.HTTP_ERROR
    assert "503" in caught.value.detail


# ---------------------------------------------------------------------------
# Delay
# ---------------------------------------------------------------------------


def delay_node(seconds: float, **overrides: Any) -> Any:
    node: dict[str, Any] = {"id": "wait", "kind": "DELAY", "seconds": seconds}
    node.update(overrides)
    return only_node(node)


def test_a_short_delay_waits_where_it_stands() -> None:
    with patch("onyx.flows.nodes.delay.time.sleep") as slept:
        outcome = execute_delay(delay_node(30), RunContext(), MagicMock())

    slept.assert_called_once_with(30.0)
    assert outcome.output == {"waited_seconds": 30.0, "parked": False}


def test_a_zero_delay_does_not_bother_sleeping() -> None:
    with patch("onyx.flows.nodes.delay.time.sleep") as slept:
        execute_delay(delay_node(0), RunContext(), MagicMock())

    slept.assert_not_called()


def test_a_long_delay_parks_the_run_instead_of_holding_a_worker() -> None:
    """A wait measured in hours cannot sit in a thread, so it must not."""
    before = datetime.now(tz=timezone.utc)

    with patch("onyx.flows.nodes.delay.time.sleep") as slept:
        with pytest.raises(NodeSuspended) as caught:
            execute_delay(delay_node(3600), RunContext(), MagicMock())

    slept.assert_not_called()
    assert caught.value.status == FlowRunStatus.AWAITING_DELAY
    assert caught.value.resume_at is not None
    waited = (caught.value.resume_at - before).total_seconds()
    assert 3595 <= waited <= 3605
    assert caught.value.detail["seconds"] == 3600.0


def test_the_line_between_sleeping_and_parking_is_a_minute() -> None:
    assert delay_node(60).parks_the_run() is False
    assert delay_node(61).parks_the_run() is True


# ---------------------------------------------------------------------------
# Filter
# ---------------------------------------------------------------------------


def filter_node(**overrides: Any) -> Any:
    node: dict[str, Any] = {
        "id": "keep",
        "kind": "FILTER",
        "over": "{{ trigger.rows }}",
        "left": "{{ item.state }}",
        "operator": "eq",
        "right": "open",
    }
    node.update(overrides)
    return only_node(node)


def test_filter_keeps_what_matches_and_counts_what_it_dropped() -> None:
    context = RunContext(
        trigger={
            "rows": [
                {"id": 1, "state": "open"},
                {"id": 2, "state": "closed"},
                {"id": 3, "state": "open"},
            ]
        }
    )

    outcome = execute_filter(filter_node(), context, MagicMock())

    assert [row["id"] for row in outcome.output["items"]] == [1, 3]
    assert outcome.output == {
        "items": [{"id": 1, "state": "open"}, {"id": 3, "state": "open"}],
        "kept": 2,
        "dropped": 1,
        "total": 3,
    }


def test_filter_can_compare_against_something_an_earlier_step_produced() -> None:
    """The point of an expression rather than a constant."""
    node = filter_node(right="{{ steps.pick.state }}")
    context = RunContext(
        trigger={"rows": [{"state": "merged"}, {"state": "open"}]},
        steps={"pick": {"state": "merged"}},
    )

    outcome = execute_filter(node, context, MagicMock())

    assert outcome.output["items"] == [{"state": "merged"}]


def test_filter_can_use_the_item_index() -> None:
    node = filter_node(left="{{ index }}", operator="lt", right="2")
    context = RunContext(trigger={"rows": ["a", "b", "c", "d"]})

    outcome = execute_filter(node, context, MagicMock())

    assert outcome.output["items"] == ["a", "b"]


def test_filter_supports_an_operator_that_compares_against_nothing() -> None:
    node = filter_node(left="{{ item.note }}", operator="is_not_empty", right=None)
    context = RunContext(
        trigger={"rows": [{"note": "look"}, {"note": ""}, {"note": "here"}]}
    )

    outcome = execute_filter(node, context, MagicMock())

    assert outcome.output["kept"] == 2


def test_filtering_everything_out_says_so_rather_than_looking_like_nothing() -> None:
    context = RunContext(trigger={"rows": [{"state": "closed"}]})

    outcome = execute_filter(filter_node(), context, MagicMock())

    assert outcome.output["items"] == []
    assert outcome.output["dropped"] == 1


def test_filter_over_nothing_is_an_empty_result_not_an_error() -> None:
    outcome = execute_filter(
        filter_node(), RunContext(trigger={"rows": None}), MagicMock()
    )

    assert outcome.output == {"items": [], "kept": 0, "dropped": 0, "total": 0}


def test_filter_rejects_a_value_that_is_not_a_list() -> None:
    with pytest.raises(NodeExecutionError) as caught:
        execute_filter(
            filter_node(), RunContext(trigger={"rows": "one, two"}), MagicMock()
        )

    assert caught.value.error_class == FlowErrorClass.EXPRESSION_ERROR
