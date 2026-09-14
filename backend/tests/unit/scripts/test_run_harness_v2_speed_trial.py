import json
import sys
from pathlib import Path
from typing import Any

import pytest

from scripts import run_harness_v2_speed_trial as speed_trial


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def _question(question_id: str) -> dict[str, str]:
    return {"question_id": question_id, "question": f"Question {question_id}?"}


class _Response:
    def __init__(self, payload: dict[str, Any] | None = None) -> None:
        self.payload = payload or {}

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self.payload


class _Session:
    instances: list["_Session"] = []

    def __init__(self) -> None:
        self.posts: list[tuple[str, dict[str, Any] | None, dict[str, Any] | None]] = []
        _Session.instances.append(self)

    def __enter__(self) -> "_Session":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def post(
        self,
        url: str,
        *,
        data: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        timeout: int,
    ) -> _Response:
        assert timeout
        self.posts.append((url, data, json))
        if url.endswith("/auth/login"):
            return _Response()
        assert json is not None
        arm_label = json.get("label", "unknown")
        return _Response(
            {
                "result": {
                    "answer": f"answer {arm_label}",
                    "outcome": "completed",
                },
                "setup_ms": 12,
            }
        )


def test_select_questions_defaults_to_source_order() -> None:
    rows = [_question("q2"), _question("q1")]

    ids, questions = speed_trial.select_questions(rows, question_ids=None)

    assert ids == ["q2", "q1"]
    assert questions == rows


def test_load_arms_rejects_unsafe_names_and_fixed_request_overrides(
    tmp_path: Path,
) -> None:
    arms_file = tmp_path / "arms.json"
    arms_file.write_text(
        json.dumps(
            {
                "good": {"completion_mode": "minimal"},
                "../bad": {"completion_mode": "standard"},
            }
        )
    )

    with pytest.raises(ValueError, match="Unsafe arm name"):
        speed_trial.load_arms(arms_file)

    arms_file.write_text(
        json.dumps(
            {
                "control": {"model": "different"},
                "candidate": {"completion_mode": "minimal"},
            }
        )
    )
    with pytest.raises(ValueError, match="cannot override fixed request keys: model"):
        speed_trial.load_arms(arms_file)


def test_load_arms_requires_at_least_two_arms(tmp_path: Path) -> None:
    arms_file = tmp_path / "arms.json"
    arms_file.write_text(json.dumps({"only": {"completion_mode": "minimal"}}))

    with pytest.raises(ValueError, match="at least two"):
        speed_trial.load_arms(arms_file)


def test_request_payload_merges_arm_policy_with_fixed_default() -> None:
    payload = speed_trial.request_payload(
        question="What happened?",
        provider="OpenAI Default",
        model="gpt-5-mini",
        arm_options={
            "label": "fast",
            "policy": {"tool_call_budget": 1},
        },
    )

    assert payload["question"] == "What happened?"
    assert payload["provider"] == "OpenAI Default"
    assert payload["model"] == "gpt-5-mini"
    assert payload["reasoning_effort"] == "low"
    assert payload["persona_id"] == 0
    assert payload["include_persona_tools"] is False
    assert payload["policy"] == {
        "max_total_tokens": 500000,
        "tool_call_budget": 1,
    }
    assert payload["label"] == "fast"


def test_rotated_order_balances_any_number_of_arms() -> None:
    arms = {"a": {}, "b": {}, "c": {}}

    assert speed_trial.rotated_order(arms, 0) == ["a", "b", "c"]
    assert speed_trial.rotated_order(arms, 1) == ["b", "c", "a"]
    assert speed_trial.rotated_order(arms, 2) == ["c", "a", "b"]
    assert speed_trial.rotated_order(arms, 3) == ["a", "b", "c"]


def test_cli_writes_one_compatible_results_file_per_arm(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    questions = tmp_path / "questions.jsonl"
    arms_file = tmp_path / "arms.json"
    output = tmp_path / "run"
    _write_jsonl(questions, [_question("q1"), _question("q2")])
    arms_file.write_text(
        json.dumps(
            {
                "control": {"label": "control"},
                "fast": {
                    "label": "fast",
                    "policy": {"tool_call_budget": 1},
                },
            }
        )
    )
    _Session.instances = []
    monkeypatch.setattr(speed_trial.requests, "Session", _Session)
    monkeypatch.setenv("ONYX_BENCH_PASSWORD", "password")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_harness_v2_speed_trial.py",
            "--base-url",
            "https://example.com",
            "--questions",
            str(questions),
            "--arms-file",
            str(arms_file),
            "--output",
            str(output),
            "--image-digest",
            "sha256:abc",
            "--concurrency",
            "1",
        ],
    )

    speed_trial.main()

    manifest = json.loads((output / "manifest.json").read_text())
    assert manifest["question_ids"] == ["q1", "q2"]
    assert manifest["concurrency"] == 1
    assert manifest["arms"] == {
        "control": {"label": "control"},
        "fast": {"label": "fast", "policy": {"tool_call_budget": 1}},
    }

    assert [
        row["question_id"] for row in _read_jsonl(output / "results_control.jsonl")
    ] == [
        "q1",
        "q2",
    ]
    fast_rows = _read_jsonl(output / "results_fast.jsonl")
    assert [row["question_id"] for row in fast_rows] == ["q1", "q2"]
    assert all(row["variant"] == "v2" for row in fast_rows)
    assert all(row["outcome"] == "completed" for row in fast_rows)

    run_posts = [
        payload
        for session in _Session.instances
        for url, _data, payload in session.posts
        if url.endswith("/harness/v2/run") and payload is not None
    ]
    assert run_posts[0]["label"] == "control"
    assert run_posts[1]["label"] == "fast"
    assert run_posts[2]["label"] == "fast"
    assert run_posts[3]["label"] == "control"
    assert run_posts[1]["policy"] == {
        "max_total_tokens": 500000,
        "tool_call_budget": 1,
    }


def test_cli_rejects_concurrency_above_three(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("ONYX_BENCH_PASSWORD", "password")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_harness_v2_speed_trial.py",
            "--base-url",
            "https://example.com",
            "--questions",
            str(tmp_path / "missing.jsonl"),
            "--output",
            str(tmp_path / "run"),
            "--image-digest",
            "sha256:abc",
            "--concurrency",
            "4",
        ],
    )

    with pytest.raises(SystemExit):
        speed_trial.main()
