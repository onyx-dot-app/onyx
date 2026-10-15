"""review(), the LLM answer check, the grep tool loop and the citation check."""

import json
import unittest
from typing import Any

from semantic_lint.diff import FilePatch, PullRequest
from semantic_lint.registry import LlmSettings, load_registry
from semantic_lint.review import (
    MAX_GREP_CALLS,
    MAX_TOOL_ROUNDS,
    Llm,
    Report,
    git_grep,
    parse_answer,
    review,
)
from semantic_lint.screen import Hit, Usage

from tests.rule_fixtures import RULE_ID, RULE_TOML, RulesDirTest
from tests.test_diff import FIXTURES
from tests.test_screen import SLACK_PATH, FakeJev, calibrate, comment_window

PR = PullRequest(
    repo="onyx-dot-app/onyx",
    number=6175,
    base_sha="base0000",
    head_sha="head1111",
    files=(
        FilePatch(SLACK_PATH, (FIXTURES / "comment_2528675138.hunk").read_text()),
        FilePatch("web/public/logo.png", None),
    ),
)
DIFF_MODULE = "tools/semantic-lint/semantic_lint/diff.py"
SETTINGS = LlmSettings("gpt-5-mini", "low", 60.0, ())


class FakeLlm(Llm):
    """Posts every asked rule on the last anchor line of the window."""

    def __init__(self, citation: tuple[str, str] | None = None) -> None:
        super().__init__(api_key="")
        self.citation: tuple[str, str] | None = citation
        self.prompts: list[str] = []
        self.searches: list[bool] = []

    def write(
        self, prompt: str, schema: dict[str, Any], settings: LlmSettings, search: bool
    ) -> tuple[str, Usage]:
        self.prompts.append(prompt)
        self.searches.append(search)
        item = schema["properties"]["findings"]["items"]["properties"]
        symbol, path = self.citation or (None, None)
        findings = [
            {
                "rule": rule_id,
                "post": True,
                "line": item["line"]["enum"][-1],
                "message": f"this deserves at least a debug log ({settings.model})",
                "cited_symbol": symbol,
                "cited_path": path,
            }
            for rule_id in item["rule"]["enum"]
        ]
        return json.dumps({"findings": findings}), Usage(1, 1000, 50, 2.0)


class ReviewTest(RulesDirTest):
    def _live(self, rule_toml: str = RULE_TOML) -> None:
        self.rule_file.write_text(rule_toml)
        registry = load_registry(self.rules_dir)
        calibrate(registry, registry.rules[0], threshold=0.6, lower=0.9)

    def test_live_rule_findings_reach_the_report(self) -> None:
        self._live()
        registry = load_registry(self.rules_dir)
        llm = FakeLlm()

        report = review(PR, registry, FakeJev(0.7), llm)

        windows = len(PR.windows(registry.settings.window.max_lines))
        per_rule = registry.settings.budget.max_findings_per_rule
        self.assertEqual(len(report.findings), min(windows, per_rule))
        self.assertEqual(len(report.over_budget), max(0, windows - per_rule))
        self.assertEqual(report.files_without_patch, ("web/public/logo.png",))
        self.assertEqual((report.rules_live, report.rules_shadow), (1, 0))
        self.assertGreater(report.cost_usd, 0)
        self.assertEqual(set(llm.searches), {False})
        self.assertIn("gpt-5-mini", report.findings[0].message)
        self.assertIn("this deserves at least a debug log", llm.prompts[0])
        self.assertIn("except ValidationError", llm.prompts[0])

    def test_repo_search_findings_need_a_citation_git_grep_confirms(self) -> None:
        self._live(
            RULE_TOML.replace("needs_repo_search = false", "needs_repo_search = true")
        )
        registry = load_registry(self.rules_dir)

        confirmed = review(
            PR, registry, FakeJev(0.7), FakeLlm(("def cut_windows", DIFF_MODULE))
        )
        invented = review(
            PR, registry, FakeJev(0.7), FakeLlm(("def no_such_helper", DIFF_MODULE))
        )
        uncited = review(PR, registry, FakeJev(0.7), FakeLlm())

        self.assertTrue(confirmed.findings)
        citation = confirmed.findings[0].citation
        assert citation is not None
        self.assertEqual(citation.path, DIFF_MODULE)
        for report in (invented, uncited):
            self.assertEqual(report.findings, ())
            self.assertEqual(len(report.hits_without_citation), len(confirmed.findings))

    def test_shadow_rules_never_reach_the_llm(self) -> None:
        registry = load_registry(self.rules_dir)
        calibrate(registry, registry.rules[0], threshold=0.6, lower=0.1)
        registry = load_registry(self.rules_dir)
        llm = FakeLlm()

        report = review(PR, registry, FakeJev(0.7), llm)

        self.assertEqual(llm.prompts, [])
        self.assertEqual(report.findings, ())
        self.assertTrue(report.shadow_hits)

    def test_uncalibrated_rules_are_not_screened(self) -> None:
        jev = FakeJev(0.9)
        report: Report = review(PR, load_registry(self.rules_dir), jev, FakeLlm())
        self.assertEqual(jev.asked, [])
        self.assertEqual(report.rules_inactive, 1)


class ParseAnswerTest(RulesDirTest):
    def _hit(self) -> Hit:
        [rule] = load_registry(self.rules_dir).rules
        return Hit(comment_window(), rule, 0.8, 0.5)

    def _answer(self, **item: object) -> str:
        base = {
            "rule": RULE_ID,
            "post": True,
            "line": 587,
            "message": "log this — or say why it is safe",
            "cited_symbol": None,
            "cited_path": None,
        }
        return json.dumps({"findings": [base | item]})

    def test_posts_and_drops(self) -> None:
        hit = self._hit()
        [finding], dropped = parse_answer(self._answer(), hit.window, [hit])
        self.assertEqual((finding.rule_id, finding.line), (RULE_ID, 587))
        self.assertEqual(finding.message, "log this; or say why it is safe")
        self.assertEqual(dropped, [])
        self.assertEqual(
            parse_answer(self._answer(post=False), hit.window, [hit]), ([], [hit])
        )
        self.assertEqual(
            parse_answer('{"findings": []}', hit.window, [hit]), ([], [hit])
        )

    def test_rejects_a_line_outside_the_window_or_an_unasked_rule(self) -> None:
        hit = self._hit()
        with self.assertRaises(ValueError):
            parse_answer(self._answer(line=12), hit.window, [hit])
        with self.assertRaises(ValueError):
            parse_answer(self._answer(rule="other-rule"), hit.window, [hit])


class ScriptedLlm(Llm):
    """Answers every round with grep calls until tools are forbidden."""

    def __init__(self, calls_per_round: int) -> None:
        super().__init__(api_key="")
        self.calls_per_round: int = calls_per_round
        self.bodies: list[dict[str, Any]] = []
        self.timeouts: list[float] = []

    def _request(self, body: dict[str, Any], settings: LlmSettings) -> dict[str, Any]:
        self.bodies.append(body)
        self.timeouts.append(settings.timeout_seconds)
        usage = {"input_tokens": 10, "output_tokens": 1}
        if body.get("tool_choice") == "none":
            text = '{"findings": []}'
            message = {"type": "output_text", "text": text}
            return {
                "id": "r",
                "status": "completed",
                "usage": usage,
                "output": [{"type": "message", "content": [message]}],
            }
        calls = [
            {
                "type": "function_call",
                "call_id": f"c{len(self.bodies)}-{index}",
                "arguments": json.dumps(
                    {"pattern": "def cut_windows", "path": DIFF_MODULE}
                ),
            }
            for index in range(self.calls_per_round)
        ]
        return {"id": f"r{len(self.bodies)}", "usage": usage, "output": calls}


class ToolLoopTest(unittest.TestCase):
    def test_the_loop_is_bounded_and_the_last_round_forbids_tools(self) -> None:
        llm = ScriptedLlm(calls_per_round=3)

        text, usage = llm.write("prompt", {}, SETTINGS, search=True)

        self.assertEqual(text, '{"findings": []}')
        self.assertEqual(len(llm.bodies), MAX_TOOL_ROUNDS + 1)
        self.assertEqual(usage.requests, MAX_TOOL_ROUNDS + 1)
        self.assertEqual(llm.bodies[0]["tools"][0]["name"], "git_grep")
        self.assertEqual(llm.bodies[-1]["tool_choice"], "none")
        self.assertEqual(set(llm.timeouts), {SETTINGS.timeout_seconds})
        outputs = [item["output"] for body in llm.bodies[1:] for item in body["input"]]
        searched = [output for output in outputs if DIFF_MODULE in output]
        self.assertEqual(len(searched), MAX_GREP_CALLS)
        self.assertIn("Search budget used. Answer now.", outputs)

    def test_git_grep_reads_the_checkout(self) -> None:
        self.assertIn(f"{DIFF_MODULE}:", git_grep("def cut_windows", DIFF_MODULE))
        self.assertEqual(git_grep("no_such_" + "symbol_9f3", None), "No matches.")
        self.assertTrue(git_grep("(", DIFF_MODULE).startswith("git grep failed"))


if __name__ == "__main__":
    unittest.main()
