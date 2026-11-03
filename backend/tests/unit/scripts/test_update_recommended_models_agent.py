from pathlib import Path

from scripts.update_recommended_models import CatalogModel, load_rules, matches_rule
from scripts.update_recommended_models_agent import extract_failure_context

RULES_PATH = (
    Path(__file__).resolve().parents[3]
    / "scripts"
    / "update_recommended_models_rules.json"
)

JOB = "provider-chat-test / provider-chat-test (vertex_ai, gemini-3.8-flash)"


def _log_line(text: str, job: str = JOB) -> str:
    return f"{job}\tUNKNOWN STEP\t2026-10-26T14:50:38.5144619Z {text}"


def _failed_attempt(error: str) -> list[str]:
    return [
        _log_line("FAILED [100%]"),
        _log_line("=" * 35 + " FAILURES " + "=" * 35),
        _log_line("_" * 20 + " test_nightly_provider_chat_workflow " + "_" * 20),
        _log_line("E   Failed: Nightly provider chat failures:"),
        _log_line(f"E   {error}"),
        _log_line("-" * 28 + " Captured stdout setup " + "-" * 29),
        _log_line("setup noise"),
    ]


def test_extract_failure_context_skips_teardown_tail() -> None:
    error = "provider=vertex_ai model=gemini-3.8-flash error=400 VALIDATION_ERROR"
    log = "\n".join(
        [
            "Failed jobs:",
            JOB,
            "",
            *_failed_attempt(error),
            *_failed_attempt(error),
            *[_log_line(f"teardown container log {i}") for i in range(5000)],
        ]
    )

    context = extract_failure_context(log)

    assert context.startswith(f"Failed jobs:\n{JOB}\n")
    assert f"[{JOB}]" in context
    assert context.count(error) == 1
    assert "teardown container log" not in context
    assert "setup noise" not in context


def test_extract_failure_context_keeps_tail_of_job_without_pytest_failure() -> None:
    error = "provider=vertex_ai model=gemini-3.8-flash error=400 VALIDATION_ERROR"
    setup_job = "provider-chat-test / provider-chat-test (anthropic, claude-opus-5-5)"
    log = "\n".join(
        [
            "Failed jobs:",
            JOB,
            setup_job,
            "",
            *_failed_attempt(error),
            *[_log_line(f"pull log {i}", job=setup_job) for i in range(500)],
            _log_line("Error: ANTHROPIC_API_KEY is not set", job=setup_job),
        ]
    )

    context = extract_failure_context(log)

    assert error in context
    assert f"[{setup_job}] (no pytest failure; last lines)" in context
    assert "Error: ANTHROPIC_API_KEY is not set" in context
    assert "pull log 0\n" not in context


def test_extract_failure_context_falls_back_to_tail() -> None:
    log = "\n".join(_log_line(f"build error {i}") for i in range(10))

    assert extract_failure_context(log, limit=40) == log[-40:]


def test_vertex_default_family_accepts_gemini_pro_and_argon() -> None:
    rule = next(
        r
        for r in load_rules(RULES_PATH).sections["vertex_ai"].rules
        if r.is_default_source
    )

    def matches(model_id: str) -> bool:
        return matches_rule(
            rule, CatalogModel.from_json({"id": model_id, "name": model_id})
        )

    assert matches("google/gemini-4-argon")
    assert matches("google/gemini-3.1-pro-preview")
    assert not matches("google/gemini-4-argon-cyber-permissive")
    assert not matches("google/gemini-3.8-flash")
