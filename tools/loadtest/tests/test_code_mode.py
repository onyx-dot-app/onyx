"""Code mode contracts: the mock's execute_code plans and the parser's code
mode packets (backend code_mode/renderer.py and streaming_models.py)."""

from __future__ import annotations

import ast
import json
from typing import Any

import pytest
from fastapi.testclient import TestClient
from mock_llm.app import app
from mock_llm.code_mode import citation_ids, search_program
from mock_llm.models import ChatCompletionRequest
from mock_llm.profiles import turn_profile
from mock_llm.response_plan import Knobs, prepare_response
from onyx_client.stream_parser import ChatStreamAnalyzer

from .fixtures import EXECUTE_CODE_TOOL, INTERNAL_SEARCH_TOOL, WAIT_CODE_TOOL

client = TestClient(app)
MODEL = "mock-profile-search-v1-ttft0-itl0"
BATCHED = "mock-profile-search-v1-codebatched-ttft0-itl0"
CODE_TOOLS = [EXECUTE_CODE_TOOL, WAIT_CODE_TOOL]


def question_for(rounds: int, seed: int = 0) -> str:
    return next(
        f"Question {i}"
        for i in range(10000)
        if turn_profile("search", f"Question {i}", seed).search_rounds == rounds
    )


def observation(cell: int, documents: list[int], status: str = "completed") -> str:
    """The text format_content (code_mode/prompt.py) returns for one observation."""
    lines = "\n".join(f"[{n}] Title of document {n}" for n in documents)
    return (
        f"Execution {status} in cell {cell} in 0.4s with 1 tool call.\n\n"
        f"Output:\n{lines}"
    )


def searches(code: str) -> list[list[str]]:
    """Queries of each internal_search call; also checks the program parses."""
    tree = compile(
        code,
        "<program>",
        "exec",
        flags=ast.PyCF_ONLY_AST | ast.PyCF_ALLOW_TOP_LEVEL_AWAIT,
    )
    return [
        ast.literal_eval(node.keywords[0].value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "internal_search"
    ]


def run_turn(
    model: str, tools: list[dict[str, Any]], question: str
) -> tuple[list[list[dict[str, Any]]], str]:
    """Drive one turn to its answer: the tool calls of each step, and the answer."""
    messages: list[dict[str, Any]] = [{"role": "user", "content": question}]
    steps: list[list[dict[str, Any]]] = []
    for step in range(10):
        plan = prepare_response(
            ChatCompletionRequest.model_validate(
                {"model": model, "messages": messages, "tools": tools}
            ),
            Knobs(model),
        )
        if not plan.calls:
            return steps, plan.answer
        calls = [call.model_dump() for call in plan.calls]
        steps.append(calls)
        messages.append({"role": "assistant", "content": None, "tool_calls": calls})
        for call in calls:
            content = (
                observation(step + 1, [step * 100 + 1, step * 100 + 2])
                if call["function"]["name"] == "execute_code"
                else json.dumps({"results": [{"document": step * 100 + 1}]})
            )
            messages.append(
                {"role": "tool", "tool_call_id": call["id"], "content": content}
            )
    raise AssertionError("turn did not reach an answer")


def direct_queries(question: str) -> list[list[str]]:
    steps, _ = run_turn(MODEL, [INTERNAL_SEARCH_TOOL], question)
    return [json.loads(calls[0]["function"]["arguments"])["queries"] for calls in steps]


@pytest.mark.parametrize("rounds", [1, 2, 3, 4])
def test_per_round_programs_follow_the_direct_plan(rounds: int) -> None:
    question = question_for(rounds)
    steps, answer = run_turn(MODEL, CODE_TOOLS, question)
    assert len(steps) == rounds
    assert all(
        len(calls) == 1 and calls[0]["function"]["name"] == "execute_code"
        for calls in steps
    )
    programs = [
        json.loads(calls[0]["function"]["arguments"])["code"] for calls in steps
    ]
    assert [searches(code) for code in programs] == [
        [queries] for queries in direct_queries(question)
    ]
    documents = sorted(
        n for step in range(rounds) for n in (100 * step + 1, 100 * step + 2)
    )
    assert answer.endswith(" " + " ".join(f"[{n}]" for n in documents[:3]))


@pytest.mark.parametrize("rounds", [1, 2, 3, 4])
def test_batched_program_runs_every_round_then_answers(rounds: int) -> None:
    question = question_for(rounds)
    steps, answer = run_turn(BATCHED, CODE_TOOLS, question)
    assert len(steps) == 1 and len(steps[0]) == 1
    code = json.loads(steps[0][0]["function"]["arguments"])["code"]
    assert searches(code) == direct_queries(question)
    assert ("asyncio.gather" in code) == (rounds > 1)
    assert answer.endswith(" [1] [2]")


def test_direct_mode_ignores_the_batched_suffix() -> None:
    question = question_for(3)
    assert direct_queries(question) == [
        json.loads(calls[0]["function"]["arguments"])["queries"]
        for calls in run_turn(BATCHED, [INTERNAL_SEARCH_TOOL], question)[0]
    ]


@pytest.mark.parametrize("model", [MODEL, BATCHED])
def test_code_plans_are_seeded(model: str, monkeypatch: pytest.MonkeyPatch) -> None:
    def programs(seed: int) -> list[str]:
        monkeypatch.setenv("MOCK_WORKLOAD_SEED", str(seed))
        return [
            json.loads(call["function"]["arguments"])["code"]
            for calls in run_turn(model, CODE_TOOLS, question_for(2, seed))[0]
            for call in calls
        ]

    assert programs(0) == programs(0)
    assert programs(7) == programs(7)
    monkeypatch.setenv("MOCK_WORKLOAD_SEED", "7")
    assert len(run_turn(model, CODE_TOOLS, question_for(2, 7))[0]) == (
        1 if model == BATCHED else 2
    )


def test_running_cell_gets_wait_code_then_the_plan_continues() -> None:
    question = question_for(2)
    messages: list[dict[str, Any]] = [{"role": "user", "content": question}]

    def next_calls() -> list[dict[str, Any]]:
        plan = prepare_response(
            ChatCompletionRequest.model_validate(
                {"model": MODEL, "messages": messages, "tools": CODE_TOOLS}
            ),
            Knobs(MODEL),
        )
        return [call.model_dump() for call in plan.calls]

    def reply(calls: list[dict[str, Any]], content: str) -> None:
        messages.append({"role": "assistant", "content": None, "tool_calls": calls})
        messages.append(
            {"role": "tool", "tool_call_id": calls[0]["id"], "content": content}
        )

    first = next_calls()
    reply(
        first,
        "Execution running in cell 3 after 30.0s with 1 tool call so far.\n\n"
        "Cell 3 continues. Call wait_code(cell_id=3) for more output, or "
        "wait_code(cell_id=3, terminate=true) to stop it.",
    )
    wait = next_calls()
    assert wait[0]["function"]["name"] == "wait_code"
    assert json.loads(wait[0]["function"]["arguments"]) == {"cell_id": 3}
    reply(wait, observation(3, [4]))
    second = next_calls()
    assert second[0]["function"]["name"] == "execute_code"
    assert searches(json.loads(second[0]["function"]["arguments"])["code"]) == [
        [question + " implementation"]
    ]


def test_code_mode_multi_tool_runs_retrieval_functions_in_one_program() -> None:
    steps, _ = run_turn("mock-tools3-ttft0-itl0-len5", CODE_TOOLS, "Find the policy")
    assert len(steps) == 1
    code = json.loads(steps[0][0]["function"]["arguments"])["code"]
    assert "internal_search(queries=" in code and "web_search(queries=" in code


def test_streamed_program_arguments_reassemble() -> None:
    body = {
        "model": BATCHED,
        "stream": True,
        "messages": [{"role": "user", "content": question_for(4)}],
        "tools": CODE_TOOLS,
    }
    with client.stream("POST", "/v1/chat/completions", json=body) as response:
        chunks = [
            json.loads(line[6:])
            for line in response.iter_lines()
            if line.startswith("data: ") and line != "data: [DONE]"
        ]
    arguments = "".join(
        call["function"].get("arguments", "")
        for chunk in chunks
        for choice in chunk["choices"]
        for call in choice["delta"].get("tool_calls", [])
    )
    assert len(searches(json.loads(arguments)["code"])) == 4
    assert chunks[-1]["choices"][0]["finish_reason"] == "tool_calls"


def test_citations_read_only_program_output_lines() -> None:
    text = (
        "Warning: truncated output (original token count: 900)\n"
        "Total output lines: 40\n\n"
        "Execution completed in cell 1 in 0.4s with 2 tool calls.\n\n"
        "Output:\n[5] Title cites [999] in prose\n[105] Another\nnot [7] a line\n\n"
        "Error:\n[8] not output"
    )
    assert citation_ids(text) == {5, 105}
    assert citation_ids("[5] Title without an execution header") == set()
    # Prose-only JSON results stay ignored in direct mode.
    assert citation_ids('{"results": [{"content": "[3] x"}]}') == set()


def test_search_program_quotes_queries_as_python_literals() -> None:
    queries = ['it\'s "quoted"', "back\\slash\nnewline"]
    assert searches(search_program([("internal_search", queries)])) == [queries]


def packet(obj: dict[str, Any], sub_turn: int | None = None) -> str:
    placement = {"turn_index": 1, "tab_index": 0, "sub_turn_index": sub_turn}
    return json.dumps({"placement": placement, "obj": obj})


def code_delta(status: str | None, **fields: Any) -> dict[str, Any]:
    final = status is not None
    return {
        "type": "code_mode_delta",
        "stdout": fields.pop("stdout", ""),
        "replace_stdout": False,
        "result": None,
        "error": fields.pop("error", None),
        "status": status,
        "duration_seconds": 0.4 if final else None,
        "tool_call_count": fields.pop("tool_call_count", 1 if final else None),
        "stored_keys": None,
        "cell_id": 1 if final else None,
        "observation": fields.pop("observation", 0 if final else None),
        "response_ended": fields.pop("response_ended", False),
    }


def program_packets(*final: dict[str, Any], searches_made: int = 1) -> list[str]:
    lines = [
        packet(
            {
                "type": "code_mode_start",
                "code": "results = ...",
                "cell_id": None,
                "observation": 0,
            }
        )
    ]
    for index in range(searches_made):
        lines += [
            packet({"type": "search_tool_start", "is_internet_search": False}, index),
            packet({"type": "search_tool_queries_delta", "queries": ["policy"]}, index),
            packet(
                {
                    "type": "search_tool_documents_delta",
                    "documents": [{"document_id": "a"}, {"document_id": "b"}],
                },
                index,
            ),
            packet({"type": "section_end"}, index),
        ]
    lines += [packet(code_delta(None, stdout="[1] Policy\n"))]
    lines += [packet(obj) for obj in final]
    return lines


def answer_packets() -> list[str]:
    return [
        packet({"type": "message_start", "final_documents": None}),
        packet({"type": "message_delta", "content": "Answer [1]"}),
        packet({"type": "stop", "stop_reason": "finished"}),
    ]


def analyze(lines: list[str]) -> ChatStreamAnalyzer:
    analyzer = ChatStreamAnalyzer()
    for line in [json.dumps({"reserved_assistant_message_id": 9}), *lines]:
        analyzer.feed(line)
    return analyzer


def test_completed_programs_count_programs_and_nested_searches() -> None:
    analyzer = analyze(
        program_packets(code_delta("completed", tool_call_count=3), searches_made=3)
        + answer_packets()
    )
    summary = analyzer.summary
    assert analyzer.completed_ok()
    assert (summary.code_programs, summary.code_waits) == (1, 0)
    assert summary.search_calls == summary.nested_search_calls == 3
    assert summary.search_doc_count == 6
    assert summary.code_failures == 0


def test_running_program_finished_by_wait_code_succeeds() -> None:
    wait = [
        packet({"type": "code_mode_start", "code": "", "cell_id": 1, "observation": 1}),
        packet(code_delta("completed", observation=1)),
    ]
    analyzer = analyze(program_packets(code_delta("running")) + wait + answer_packets())
    assert analyzer.completed_ok()
    assert (analyzer.summary.code_programs, analyzer.summary.code_waits) == (1, 1)


@pytest.mark.parametrize(
    ("final", "reason"),
    [
        (
            code_delta(
                "failed",
                error="The code sandbox is busy. Try again, or answer without code.",
                tool_call_count=0,
            ),
            "code sandbox busy",
        ),
        (code_delta("timed_out", error="Time limit"), "code program timed_out"),
        (code_delta("failed", error="NameError: x"), "code program failed"),
        (
            code_delta("terminated", response_ended=True),
            "code program terminated",
        ),
    ],
)
def test_unfinished_programs_fail_the_turn(final: dict[str, Any], reason: str) -> None:
    analyzer = analyze(program_packets(final) + answer_packets())
    assert not analyzer.completed_ok()
    assert analyzer.failure_reason().startswith(reason)
    assert analyzer.summary.code_failures == 1


def test_direct_search_is_not_nested() -> None:
    analyzer = analyze(
        [
            packet({"type": "search_tool_start", "is_internet_search": False}),
            *answer_packets(),
        ]
    )
    assert analyzer.completed_ok()
    assert (analyzer.summary.search_calls, analyzer.summary.nested_search_calls) == (
        1,
        0,
    )
    assert analyzer.summary.code_programs == 0
