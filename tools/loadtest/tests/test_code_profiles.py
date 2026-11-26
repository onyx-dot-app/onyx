"""Code profiles: plans sampled from the recorded calibration, the programs
that the mock writes for them in each tool family's shape, and the load
client's workload counts for them."""

from __future__ import annotations

import ast
import json
import sys
from typing import Any

import pytest
from fastapi.testclient import TestClient
from mock_llm.app import app
from mock_llm.code_mode import PLANNED_FAILURE, profile_program
from mock_llm.code_workload import (
    CodePool,
    code_calibration,
    observed_programs,
    tail_programs,
)
from mock_llm.models import ChatCompletionRequest
from mock_llm.profiles import turn_profile
from mock_llm.response_plan import Knobs, ResponsePlan, prepare_response
from onyx_client.stream_parser import ChatStreamAnalyzer
from onyx_client.workload_metrics import turn_range
from workload_manifest import main as manifest_main

from .fixtures import (
    EXEC_TOOL,
    INTERNAL_SEARCH_TOOL,
    POLL_TOOL,
    REPL_TOOL,
    WAIT_TOOL,
)

OPENAI_MODEL = "mock-profile-code-v1-ttft0-itl0"
CLAUDE_MODEL = "mock-profile-code-v1-claude-ttft0-itl0"
SHAPES = [
    (OPENAI_MODEL, [EXEC_TOOL, WAIT_TOOL], "exec", "wait"),
    (CLAUDE_MODEL, [REPL_TOOL, POLL_TOOL], "repl", "poll"),
]
RUN_SHAPES = [(model, tools, run) for model, tools, run, _ in SHAPES]
QUESTIONS = [f"Question {index}" for index in range(4000)]


def question_with(predicate: Any, **profile: Any) -> str:
    return next(
        q for q in QUESTIONS if predicate(turn_profile("code", q, **profile).programs)
    )


def program_calls(code: str) -> list[ast.Call]:
    tree = compile(
        code,
        "<program>",
        "exec",
        flags=ast.PyCF_ONLY_AST | ast.PyCF_ALLOW_TOP_LEVEL_AWAIT,
    )
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "tools"
    ]


def observation(cell: int, status: str = "completed") -> str:
    return (
        f"Execution {status} in cell {cell} in 0.4s with 1 tool call.\n\n"
        f"Output:\n[{cell}] Title of document {cell}\n  content"
    )


def next_plan(
    model: str, tools: list[dict[str, Any]], messages: list[dict[str, Any]]
) -> ResponsePlan:
    return prepare_response(
        ChatCompletionRequest.model_validate(
            {"model": model, "messages": messages, "tools": tools}
        ),
        Knobs(model),
    )


def run_turn(
    model: str, tools: list[dict[str, Any]], question: str, *, compact: bool = False
) -> tuple[list[dict[str, Any]], str]:
    """Drive a turn to its answer; each program's result is a completed cell.

    With `compact`, every step compacts the history as Onyx does
    (agents/compaction.py): a summary and the question replace all but the
    latest tool exchange."""
    question_message = {"role": "user", "content": question}
    messages: list[dict[str, Any]] = [question_message]
    calls: list[dict[str, Any]] = []
    for step in range(100):
        plan = next_plan(model, tools, messages)
        if not plan.calls:
            return calls, plan.answer
        [call] = [c.model_dump() for c in plan.calls]
        calls.append(call)
        messages.append({"role": "assistant", "content": None, "tool_calls": [call]})
        messages.append(
            {
                "role": "tool",
                "tool_call_id": call["id"],
                "content": observation(step + 1),
            }
        )
        if compact:
            summary = {"role": "system", "content": "Conversation summary:\nDone."}
            messages = [summary, question_message, *messages[-2:]]
    raise AssertionError("turn did not reach an answer")


def test_calibration_templates_reproduce_their_summary() -> None:
    calibration, _ = code_calibration()
    for pool in calibration["pools"].values():
        summary = pool["summary"]
        turns = [(turn["programs"], turn["weight"]) for turn in pool["turns"]]
        total = sum(weight for _, weight in turns)
        programs = sum(len(shape) * weight for shape, weight in turns)
        assert total == summary["turns"]
        assert programs == summary["programs"]
        assert round(programs / total, 2) == summary["programs_per_turn_mean"]
        failed = sum(p[2] * weight for shape, weight in turns for p in shape)
        assert round(failed / programs, 4) == summary["failed_program_share"]
    tail = calibration["tail"]
    assert min(count for count, _ in tail["program_counts"]) >= 20
    assert min(chars for chars, _ in tail["near_cap_output_chars"]) >= 36_000


@pytest.mark.parametrize("pool", ["openai", "claude"])
def test_observed_plans_follow_the_pool_distribution(pool: CodePool) -> None:
    calibration, _ = code_calibration()
    summary = calibration["pools"][pool]["summary"]
    templates = {
        tuple(tuple(p) for p in turn["programs"])
        for turn in calibration["pools"][pool]["turns"]
    }
    plans = [observed_programs(q, pool) for q in QUESTIONS]
    for plan in plans:
        assert tuple((p.output_chars, p.searches, int(p.failed)) for p in plan) in (
            templates
        )
    mean = sum(len(plan) for plan in plans) / len(plans)
    assert mean == pytest.approx(summary["programs_per_turn_mean"], rel=0.15)
    tail_share = sum(len(plan) >= 20 for plan in plans) / len(plans)
    assert tail_share == pytest.approx(summary["tail_turn_share"], abs=0.02)
    outputs = [p.output_chars for plan in plans for p in plan]
    assert sum(outputs) / len(outputs) == pytest.approx(
        summary["output_chars_mean"], rel=0.15
    )


def test_tail_plans_stay_within_the_observed_tail() -> None:
    calibration, _ = code_calibration()
    counts = [count for count, _ in calibration["tail"]["program_counts"]]
    for question in QUESTIONS[:200]:
        plan = tail_programs(question)
        assert min(counts) <= len(plan) <= max(counts)
        assert all(36_000 <= p.output_chars and not p.failed for p in plan)


@pytest.mark.parametrize("percent", [0, 10, 100])
def test_tail_knob_sets_the_share_of_long_tail_turns(percent: int) -> None:
    profiles = [turn_profile("code", q, tail_percent=percent) for q in QUESTIONS]
    share = sum(p.size == "longtail" for p in profiles) / len(profiles)
    assert share == pytest.approx(percent / 100, abs=0.02)
    for profile in profiles:
        if profile.size == "longtail":
            assert len(profile.programs) >= 20


def test_plans_are_seeded_and_take_the_pool_step_duration() -> None:
    calibration, _ = code_calibration()
    pools: list[CodePool] = ["openai", "claude"]
    for pool in pools:
        profile = turn_profile("code", "Question 1", code_pool=pool)
        assert profile == turn_profile("code", "Question 1", code_pool=pool)
        assert (
            profile.tool_step_s == calibration["pools"][pool]["model_seconds_per_call"]
        )
    plans = {
        tuple(turn_profile("code", "Question 1", seed).programs) for seed in range(8)
    }
    assert len(plans) > 1


def test_knobs_read_family_and_tail() -> None:
    assert Knobs("mock-profile-code-v1").code_pool == "openai"
    knobs = Knobs("mock-profile-code-v1-claude-tail25")
    assert (knobs.code_pool, knobs.tail_percent) == ("claude", 25)
    with pytest.raises(ValueError):
        Knobs("mock-profile-code-v1-tail101")


@pytest.mark.parametrize(("model", "tools", "run"), RUN_SHAPES)
def test_each_family_runs_the_planned_programs_in_its_shape(
    model: str, tools: list[dict[str, Any]], run: str
) -> None:
    pool = Knobs(model).code_pool
    question = question_with(
        lambda programs: len(programs) >= 3 and any(p.failed for p in programs),
        code_pool=pool,
    )
    planned = turn_profile("code", question, code_pool=pool).programs
    calls, answer = run_turn(model, tools, question)
    assert [call["function"]["name"] for call in calls] == [run] * len(planned)
    assert answer
    queries: list[str] = []
    for call, program in zip(calls, planned, strict=True):
        arguments = json.loads(call["function"]["arguments"])
        assert list(arguments) == ["code"]
        code = arguments["code"]
        searches = program_calls(code)
        assert len(searches) == program.searches
        for search in searches:
            queries += ast.literal_eval(search.keywords[0].value)
        assert (PLANNED_FAILURE in code) == program.failed
        if program.searches:
            assert f"[:{program.output_chars}])" in code
    assert queries[0] == question
    assert len(set(queries)) == min(len(queries), 9)


def test_history_compaction_keeps_the_turn_plan_position() -> None:
    question = question_with(lambda programs: len(programs) >= 3)
    tools = [EXEC_TOOL, WAIT_TOOL]
    calls, _ = run_turn(OPENAI_MODEL, tools, question)
    compacted, answer = run_turn(OPENAI_MODEL, tools, question, compact=True)
    assert answer
    assert [c["function"]["arguments"] for c in compacted] == [
        c["function"]["arguments"] for c in calls
    ]


@pytest.mark.parametrize(("model", "tools", "run", "wait"), SHAPES)
def test_each_family_waits_on_a_running_cell_with_its_wait_tool(
    model: str, tools: list[dict[str, Any]], run: str, wait: str
) -> None:
    pool = Knobs(model).code_pool
    question = question_with(lambda programs: len(programs) >= 2, code_pool=pool)
    messages: list[dict[str, Any]] = [{"role": "user", "content": question}]
    [first] = [c.model_dump() for c in next_plan(model, tools, messages).calls]
    assert first["function"]["name"] == run
    messages.append({"role": "assistant", "content": None, "tool_calls": [first]})
    running = (
        "Execution running in cell 4 after 30.0s with 1 tool call so far.\n\n"
        "Cell 4 continues."
    )
    messages.append({"role": "tool", "tool_call_id": first["id"], "content": running})
    [second] = [c.model_dump() for c in next_plan(model, tools, messages).calls]
    assert second["function"]["name"] == wait
    assert json.loads(second["function"]["arguments"]) == {"cell_id": 4}


def test_tool_steps_take_the_observed_model_duration() -> None:
    question = question_with(lambda programs: len(programs) >= 1)
    plan = next_plan(
        "mock-profile-code-v1",
        [EXEC_TOOL, WAIT_TOOL],
        [{"role": "user", "content": question}],
    )
    assert plan.calls
    assert (
        plan.end_s == code_calibration()[0]["pools"]["openai"]["model_seconds_per_call"]
    )


def test_code_profile_without_code_mode_is_rejected() -> None:
    question = question_with(lambda programs: len(programs) >= 1)
    with pytest.raises(ValueError, match="needs code mode"):
        next_plan(
            OPENAI_MODEL,
            [INTERNAL_SEARCH_TOOL],
            [{"role": "user", "content": question}],
        )


def test_program_output_is_cut_and_never_reads_as_document_lines() -> None:
    code = profile_program([["a"], ["b", "c"]], 39_000, failed=True)
    assert len(program_calls(code)) == 2
    assert "asyncio.gather" in code
    assert '"  " + doc["content"].replace("\\n", "\\n  ")' in code
    assert code.endswith(f"raise RuntimeError({PLANNED_FAILURE!r})\n")
    filler = profile_program([], 1_000, failed=False)
    namespace: dict[str, Any] = {}
    printed: list[str] = []
    namespace["print"] = printed.append
    exec(filler, namespace)  # noqa: S102
    assert len(printed[0]) == 1_000
    assert profile_program([], 0, failed=False) == "pass\n"


def code_packet(obj: dict[str, Any], turn: int = 1) -> str:
    return json.dumps({"placement": {"turn_index": turn, "tab_index": 0}, "obj": obj})


def final_delta(status: str, stdout: str = "", **fields: Any) -> dict[str, Any]:
    return {
        "type": "code_mode_delta",
        "stdout": stdout,
        "replace_stdout": fields.pop("replace_stdout", False),
        "error": fields.pop("error", None),
        "status": status,
        "cell_id": 1,
        "observation": 0,
    }


ANSWER = [
    code_packet({"type": "message_start", "final_documents": None}, turn=9),
    code_packet({"type": "message_delta", "content": "Answer"}, turn=9),
    code_packet({"type": "stop", "stop_reason": "finished"}, turn=9),
]


def test_output_chars_follow_appended_and_replaced_stdout() -> None:
    analyzer = ChatStreamAnalyzer()
    for line in [
        code_packet({"type": "code_mode_start", "code": "x", "observation": 0}),
        code_packet({"type": "code_mode_delta", "stdout": "a" * 30}),
        code_packet({"type": "code_mode_delta", "stdout": "b" * 20}),
        code_packet(final_delta("completed", "c" * 40, replace_stdout=True)),
        code_packet({"type": "code_mode_start", "code": "y", "observation": 0}, 2),
        code_packet(final_delta("completed", "d" * 7), 2),
        *ANSWER,
    ]:
        analyzer.feed(line)
    assert analyzer.summary.code_output_chars == 47
    assert analyzer.completed_ok()


def test_a_planned_failure_is_counted_and_keeps_the_turn() -> None:
    error = f"RuntimeError: {PLANNED_FAILURE}"
    analyzer = ChatStreamAnalyzer()
    for line in [
        code_packet({"type": "code_mode_start", "code": "x", "observation": 0}),
        code_packet(final_delta("failed", error=error)),
        *ANSWER,
    ]:
        analyzer.feed(line)
    assert analyzer.completed_ok()
    summary = analyzer.summary
    assert (summary.code_planned_failures, summary.code_failures) == (1, 0)


@pytest.mark.parametrize(
    ("turn", "label"),
    [(1, "1"), (2, "2-5"), (5, "2-5"), (6, "6-10"), (40, "21-40"), (81, "81+")],
)
def test_session_turns_report_in_bounded_ranges(turn: int, label: str) -> None:
    assert turn_range(turn) == label


@pytest.mark.parametrize(
    "model",
    [
        "mock-profile-code-v1",
        "mock-profile-code-v1-claude",
        "mock-profile-code-v1-tail10",
        "mock-profile-code-v1-claude-tail100",
        "mock-profile-code-v1-tail10-claude",
    ],
)
def test_manifest_reports_planned_program_workload(
    model: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["workload_manifest.py", "--model", model])
    manifest_main()
    manifest = json.loads(capsys.readouterr().out)
    plans = manifest["plans"]
    assert manifest["programs"] == sum(len(plan["programs"]) for plan in plans)
    assert manifest["planned_output_chars"] == sum(
        program[0] for plan in plans for program in plan["programs"]
    )
    assert sum(manifest["program_count_counts"].values()) == len(plans)


@pytest.mark.parametrize(
    "model",
    [
        "mock-profile-code-v1-tail101",
        "mock-profile-code-v1-len10",
        "mock-profile-code-v1-codebatched",
        "mock-profile-search-v1-tail10",
    ],
)
def test_manifest_rejects_other_code_overrides(
    model: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "argv", ["workload_manifest.py", "--model", model])
    with pytest.raises(SystemExit) as error:
        manifest_main()
    assert error.value.code == 2


def test_listed_models_include_the_code_profiles() -> None:
    names = {m["id"] for m in TestClient(app).get("/v1/models").json()["data"]}
    assert {
        "mock-profile-code-v1",
        "mock-profile-code-v1-claude",
        "mock-profile-code-v1-tail100",
        "mock-profile-code-v1-claude-tail100",
    } <= names


def test_tool_results_in_content_parts_are_read() -> None:
    """Content parts, such as parts that carry cache markers, reach the same
    wait and citation decisions as plain strings."""
    question = question_with(lambda programs: len(programs) >= 2, code_pool="claude")
    messages: list[dict[str, Any]] = [{"role": "user", "content": question}]
    tools = [REPL_TOOL, POLL_TOOL]
    [first] = [c.model_dump() for c in next_plan(CLAUDE_MODEL, tools, messages).calls]
    messages.append({"role": "assistant", "content": None, "tool_calls": [first]})
    running = "Execution running in cell 4 after 30.0s with 1 tool call so far."
    messages.append(
        {
            "role": "tool",
            "tool_call_id": first["id"],
            "content": [
                {"type": "text", "text": running, "cache_control": {"type": "x"}}
            ],
        }
    )
    [poll] = [c.model_dump() for c in next_plan(CLAUDE_MODEL, tools, messages).calls]
    assert poll["function"]["name"] == "poll"

    cited: list[dict[str, Any]] = [
        {"role": "user", "content": "Find the policy"},
        {"role": "assistant", "content": None, "tool_calls": [first]},
        {
            "role": "tool",
            "tool_call_id": first["id"],
            "content": [{"type": "text", "text": observation(7)}],
        },
    ]
    answer = next_plan("mock-profile-chat-v1-ttft0-itl0", [], cited).answer
    assert answer.endswith(" [7]")
