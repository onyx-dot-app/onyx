"""Representative turn contracts and reproducible load schedules."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from capacity_report import assess
from fastapi.testclient import TestClient
from mock_llm.app import app
from mock_llm.models import ChatCompletionRequest, ChunkDelta
from mock_llm.profiles import turn_profile
from mock_llm.response_plan import Knobs, prepare_response, schedule, token_count
from onyx_client import workload_metrics
from onyx_client.messages import load_messages
from onyx_client.pacing import pause_seconds, question_order, user_seed
from workload_manifest import main as manifest_main

from .fixtures import INTERNAL_SEARCH_TOOL

client = TestClient(app)
MODEL = "mock-profile-search-v1-ttft0-itl0"


def question_for(rounds: int) -> str:
    return next(
        f"Question {i}"
        for i in range(10000)
        if turn_profile("search", f"Question {i}").search_rounds == rounds
    )


@pytest.mark.parametrize("rounds", [1, 2, 3, 4])
def test_complete_search_turn_stops_at_planned_rounds(rounds: int) -> None:
    question = question_for(rounds)
    messages = [{"role": "user", "content": question}]
    for step in range(rounds + 1):
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": MODEL,
                "messages": messages,
                "tools": [INTERNAL_SEARCH_TOOL],
            },
        )
        assert response.status_code == 200
        choice = response.json()["choices"][0]
        message = choice["message"]
        if step == rounds:
            assert choice["finish_reason"] == "stop"
            assert "[7]" in message["content"]
            assert "[1]" not in message["content"]
            break
        assert choice["finish_reason"] == "tool_calls"
        calls = message["tool_calls"]
        assert len(calls) == 1
        queries = json.loads(calls[0]["function"]["arguments"])["queries"]
        assert 1 <= len(queries) <= 3
        messages.extend(
            [
                message,
                {
                    "role": "tool",
                    "tool_call_id": calls[0]["id"],
                    "content": json.dumps(
                        {"results": [{"document": 7, "content": "Evidence"}]}
                    ),
                },
            ]
        )
    # A new user message begins a fresh search sequence in a multi-turn session.
    messages.append({"role": "user", "content": question})
    restarted = client.post(
        "/v1/chat/completions",
        json={"model": MODEL, "messages": messages, "tools": [INTERNAL_SEARCH_TOOL]},
    ).json()
    assert restarted["choices"][0]["finish_reason"] == "tool_calls"


def test_stream_and_plain_preserve_text_reasoning_usage_and_citations() -> None:
    question = next(
        f"Question {i}"
        for i in range(100)
        if turn_profile("search", f"Question {i}").reasoning_words
    )
    body = {
        "model": MODEL,
        "tool_choice": "none",
        "messages": [
            {"role": "user", "content": question},
            {
                "role": "tool",
                "tool_call_id": "search1",
                "content": '{"results":[{"document":9,"content":"Evidence"}]}',
            },
        ],
    }
    plain = client.post("/v1/chat/completions", json=body).json()
    streamed = client.post(
        "/v1/chat/completions",
        json={**body, "stream": True, "stream_options": {"include_usage": True}},
    )
    chunks = [
        json.loads(line[6:])
        for line in streamed.text.splitlines()
        if line.startswith("data: ") and line != "data: [DONE]"
    ]
    deltas = [c["delta"] for chunk in chunks for c in chunk["choices"]]
    message = plain["choices"][0]["message"]
    assert "".join(d.get("content", "") for d in deltas) == message["content"]
    assert (
        "".join(d.get("reasoning_content", "") for d in deltas)
        == message["reasoning_content"]
    )
    assert "[9]" in message["content"]
    assert chunks[-1]["choices"] == []
    assert chunks[-1]["usage"] == plain["usage"]
    assert plain["usage"]["prompt_tokens"] != 100


def test_argument_fragments_reassemble_valid_json() -> None:
    body = {
        "model": MODEL,
        "messages": [{"role": "user", "content": question_for(3)}],
        "tools": [INTERNAL_SEARCH_TOOL],
    }
    plain = client.post("/v1/chat/completions", json=body).json()
    stream = client.post("/v1/chat/completions", json={**body, "stream": True}).text
    parts = [
        call["function"].get("arguments", "")
        for line in stream.splitlines()
        if line.startswith("data: ") and line != "data: [DONE]"
        for choice in json.loads(line[6:])["choices"]
        for call in choice["delta"].get("tool_calls", [])
    ]
    assert len([part for part in parts if part]) > 1
    assert json.loads("".join(parts)) == json.loads(
        plain["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"]
    )
    assert len(json.loads("".join(parts))["queries"]) == 3


@pytest.mark.parametrize("field", ["max_tokens", "max_completion_tokens"])
def test_budget_includes_reasoning_and_handles_unicode(field: str) -> None:
    request = ChatCompletionRequest.model_validate(
        {
            "model": MODEL,
            "messages": [{"role": "user", "content": "Explain 日本語 👋"}],
            field: 10,
        }
    )
    plan = prepare_response(request, Knobs(MODEL))
    assert token_count(plan.answer) + token_count(plan.reasoning) <= 10
    assert plan.finish == "length"
    assert "\ufffd" not in plan.answer


def test_profile_mix_is_seeded_and_contains_tail_work() -> None:
    plans = [turn_profile("search", f"Question {i}", 7) for i in range(10000)]
    assert 0.18 <= sum(p.search_rounds > 1 for p in plans) / len(plans) <= 0.22
    assert 195 <= sum(p.answer_words for p in plans) / len(plans) <= 225
    assert 0.45 <= sum(p.reasoning_words > 0 for p in plans) / len(plans) <= 0.55
    assert max(p.answer_words for p in plans) == 1300
    assert plans == [turn_profile("search", f"Question {i}", 7) for i in range(10000)]
    assert plans != [turn_profile("search", f"Question {i}", 8) for i in range(10000)]


def test_timing_plan_has_fixed_end_independent_of_fragment_count() -> None:
    for count in (2, 1000):
        events = schedule([ChunkDelta(content="x") for _ in range(count)], 1.4, 3.0)
        assert events[0].offset_s == 1.4
        assert events[-1].offset_s == 3.0
        assert all(
            a.offset_s <= b.offset_s for a, b in zip(events, events[1:], strict=False)
        )
    request = ChatCompletionRequest(
        model="mock-profile-search-v1",
        messages=[
            {
                "role": "user",
                "content": "Analyze the relevance of document sections to a search query and classify x",
            }
        ],
    )
    plan = prepare_response(request, Knobs(request.model))
    assert plan.end_s == 0.88
    assert plan.reasoning == ""


def test_faults_are_explicit_and_normal_profiles_remain_valid() -> None:
    assert (
        client.post("/v1/chat/completions", json={"model": "mock-fault429"}).status_code
        == 429
    )
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": MODEL + "-faultmalformed",
            "messages": [{"role": "user", "content": "q"}],
            "tools": [INTERNAL_SEARCH_TOOL],
        },
    ).json()
    with pytest.raises(ValueError):
        json.loads(
            response["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"]
        )
    assert (
        client.post(
            "/v1/chat/completions", json={"model": "mock-profile-unknown-v1"}
        ).status_code
        == 400
    )


def test_schedule_is_reproducible_and_spreads_users() -> None:
    a, b = user_seed(7, 0, 0), user_seed(7, 1, 0)
    assert a != b
    assert question_order(500, a) == question_order(500, a)
    assert question_order(500, a) != question_order(500, b)
    pauses = [pause_seconds(15, 0.5, a, turn) for turn in range(10000)]
    assert min(pauses) >= 7.5 and max(pauses) <= 22.5
    assert 14.8 <= sum(pauses) / len(pauses) <= 15.2
    assert pause_seconds(0, 0.5, a, 0) == 0
    assert pause_seconds(15, 0, a, 0) == 15
    with pytest.raises(ValueError):
        pause_seconds(15, 2, a, 0)


def test_erag_jsonl_loads_only_questions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "questions.jsonl"
    path.write_text(
        '{"question": "A real question", "gold_answer":"Never send this"}\n'
    )
    monkeypatch.setenv("ONYX_MESSAGES_FILE", str(path))
    assert load_messages() == ["A real question"]
    path.write_text('{"question":null}\n')
    with pytest.raises(ValueError):
        load_messages()


def test_worker_snapshots_replace_instead_of_double_counting() -> None:
    workload_metrics.reset()
    workload_metrics.workers["a"] = {"search": {"active": 5, "finished": 10}}
    workload_metrics.workers["b"] = {"search": {"active": 2, "finished": 20}}
    assert workload_metrics.aggregate()["search"] == {"active": 7, "finished": 30}
    workload_metrics.workers["a"] = {"search": {"active": 0, "finished": 15}}
    assert workload_metrics.aggregate()["search"] == {"active": 2, "finished": 35}
    assert workload_metrics.aggregate({"a"})["search"] == {"active": 0, "finished": 35}
    workload_metrics.reset()


def test_capacity_requires_enough_samples_and_both_targets() -> None:
    row = {
        "Name": "search:total_turn",
        "Request Count": "100",
        "Failure Count": "0",
        "50%": "5000",
        "95%": "10000",
        "Requests/s": "2",
    }
    assert assess(row, 10, 0.01, 100)["passed"]
    assert not assess(row, 9, 0.01, 100)["passed"]
    assert not assess({**row, "Failure Count": "2"}, 10, 0.01, 100)["passed"]
    assert not assess(row, 10, 0.01, 200)["passed"]


@pytest.mark.parametrize("budget", [1, 5, 10])
def test_tool_call_budget_matches_usage_and_finish_reason(budget: int) -> None:
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": MODEL,
            "messages": [
                {"role": "user", "content": "Find the deployment configuration details"}
            ],
            "tools": [INTERNAL_SEARCH_TOOL],
            "max_completion_tokens": budget,
        },
    ).json()
    assert response["usage"]["completion_tokens"] <= budget
    assert response["choices"][0]["finish_reason"] == "length"


def test_citations_do_not_use_previous_turn_or_document_prose() -> None:
    body = {
        "model": MODEL,
        "messages": [
            {"role": "user", "content": "Old question"},
            {
                "role": "tool",
                "content": '{"results":[{"document":9}]}',
                "tool_call_id": "old",
            },
            {"role": "user", "content": "New question"},
            {
                "role": "tool",
                "content": '{"results":[{"content":"document 999"}]}',
                "tool_call_id": "new",
            },
        ],
        "tool_choice": "none",
    }
    message = client.post("/v1/chat/completions", json=body).json()["choices"][0][
        "message"
    ]
    assert "[9]" not in message["content"] and "[999]" not in message["content"]


def test_metrics_expose_workload_without_question_labels() -> None:
    client.post(
        "/v1/chat/completions",
        json={
            "model": MODEL,
            "messages": [{"role": "user", "content": "Private unique question"}],
        },
    )
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "mock_llm_planned_calls_total" in response.text
    assert "mock_llm_completed_calls_total" in response.text
    assert "Private unique question" not in response.text


@pytest.mark.parametrize(
    "model", ["mock-profile-search-v1-len1000", "mock-profile-search-v1-faultstall"]
)
def test_manifest_rejects_unmodeled_overrides(
    model: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "argv", ["workload_manifest.py", "--model", model])
    with pytest.raises(SystemExit) as error:
        manifest_main()
    assert error.value.code == 2
