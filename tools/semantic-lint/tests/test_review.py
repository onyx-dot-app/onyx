"""review(), the LLM answer check, the check run, and publishing against a fake GitHub."""

import json
import unittest
from dataclasses import replace
from typing import Any

from semantic_lint.diff import FilePatch, PullRequest
from semantic_lint.github import GitHub
from semantic_lint.registry import LlmSettings, load_registry
from semantic_lint.review import (
    Failed,
    GrepMatch,
    Llm,
    Report,
    Skipped,
    check_run,
    parse_answer,
    render_summary,
    review,
)
from semantic_lint.screen import Hit, Usage

from tests.rule_fixtures import RULE_ID, RulesDirTest
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


class FakeLlm(Llm):
    """Posts every asked rule on the last anchor line of the window."""

    def __init__(self, post: bool = True) -> None:
        super().__init__(api_key="")
        self.post: bool = post
        self.prompts: list[str] = []
        self.models: list[str] = []

    def write(
        self, prompt: str, schema: dict[str, Any], settings: LlmSettings
    ) -> tuple[str, Usage]:
        self.prompts.append(prompt)
        self.models.append(settings.model)
        item = schema["properties"]["findings"]["items"]["properties"]
        findings = [
            {
                "rule": rule_id,
                "post": self.post,
                "line": item["line"]["enum"][-1],
                "message": "this deserves at least a debug log",
                "cited_symbol": None,
            }
            for rule_id in item["rule"]["enum"]
        ]
        return json.dumps({"findings": findings}), Usage(1, 1000, 50, 2.0)


class FakeGitHub(GitHub):
    def __init__(self, head_sha: str) -> None:
        super().__init__(token="", repo="onyx-dot-app/onyx")
        self.head: str = head_sha
        self.posted: list[tuple[str, object]] = []

    def request(self, method: str, path: str, body: object | None = None) -> Any:
        if method == "GET" and path == f"pulls/{PR.number}":
            return {"head": {"sha": self.head}, "base": {"sha": PR.base_sha}}
        self.posted.append((path, body))
        return {}


class ReviewTest(RulesDirTest):
    def test_live_rule_findings_reach_the_report(self) -> None:
        registry = load_registry(self.rules_dir)
        calibrate(registry, registry.rules[0], threshold=0.6, lower=0.9)
        registry = load_registry(self.rules_dir)
        llm = FakeLlm()

        report = review(PR, registry, FakeJev(0.7), llm)

        windows = len(PR.windows(registry.settings.window.max_lines))
        per_rule = registry.settings.budget.max_findings_per_rule
        self.assertEqual(len(llm.prompts), min(windows, per_rule))
        self.assertEqual(len(report.findings), min(windows, per_rule))
        self.assertEqual(len(report.over_budget), max(0, windows - per_rule))
        self.assertEqual(report.files_without_patch, ("web/public/logo.png",))
        self.assertEqual((report.rules_live, report.rules_shadow), (1, 0))
        self.assertGreater(report.cost_usd, 0)
        self.assertEqual(llm.models[0], registry.settings.llm.model)
        self.assertIn("this deserves at least a debug log", llm.prompts[0])
        self.assertIn("except ValidationError", llm.prompts[0])

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
        registry = load_registry(self.rules_dir)
        jev = FakeJev(0.9)
        report = review(PR, registry, jev, FakeLlm())
        self.assertEqual(jev.asked, [])
        self.assertEqual(report.rules_inactive, 1)


class ParseAnswerTest(RulesDirTest):
    def _hit(self, needs_repo_search: bool = False) -> Hit:
        [rule] = load_registry(self.rules_dir).rules
        rule = replace(rule, needs_repo_search=needs_repo_search)
        return Hit(comment_window(), rule, 0.8, 0.5)

    def _answer(self, **item: object) -> str:
        base = {
            "rule": RULE_ID,
            "post": True,
            "line": 587,
            "message": "log this",
            "cited_symbol": None,
        }
        return json.dumps({"findings": [base | item]})

    def test_posts_and_drops(self) -> None:
        hit = self._hit()
        findings, dropped = parse_answer(self._answer(), hit.window, [hit], [])
        self.assertEqual([(f.rule_id, f.line) for f in findings], [(RULE_ID, 587)])
        self.assertEqual(dropped, [])
        findings, dropped = parse_answer(
            self._answer(post=False), hit.window, [hit], []
        )
        self.assertEqual((findings, dropped), ([], [hit]))
        findings, dropped = parse_answer('{"findings": []}', hit.window, [hit], [])
        self.assertEqual((findings, dropped), ([], [hit]))

    def test_rejects_a_line_outside_the_window_or_an_unasked_rule(self) -> None:
        hit = self._hit()
        with self.assertRaises(ValueError):
            parse_answer(self._answer(line=12), hit.window, [hit], [])
        with self.assertRaises(ValueError):
            parse_answer(self._answer(rule="other-rule"), hit.window, [hit], [])

    def test_repo_search_rules_need_a_cited_match(self) -> None:
        hit = self._hit(needs_repo_search=True)
        match = GrepMatch(
            "base0000", "backend/onyx/utils/logger.py", 10, "def log_x():"
        )
        uncited = parse_answer(self._answer(), hit.window, [hit], [match])
        invented = parse_answer(
            self._answer(cited_symbol="log_y"), hit.window, [hit], [match]
        )
        cited = parse_answer(
            self._answer(cited_symbol="log_x"), hit.window, [hit], [match]
        )
        self.assertEqual(uncited, ([], [hit]))
        self.assertEqual(invented, ([], [hit]))
        self.assertEqual(cited[0][0].cited_symbol, "log_x")


class PublishTest(RulesDirTest):
    def _report(self) -> Report:
        registry = load_registry(self.rules_dir)
        calibrate(registry, registry.rules[0], threshold=0.6, lower=0.9)
        return review(PR, load_registry(self.rules_dir), FakeJev(0.7), FakeLlm())

    def test_check_run_is_neutral_with_findings_and_success_without(self) -> None:
        registry = load_registry(self.rules_dir)
        report = self._report()
        with_findings = check_run(report, registry, PR.head_sha)
        clean = check_run(replace(report, findings=()), registry, PR.head_sha)
        skipped = check_run(Skipped("TYPESAFE_API_KEY not set."), registry, "abc")
        failed = check_run(Failed("boom"), registry, "abc")

        self.assertEqual(with_findings["conclusion"], "neutral")
        annotation = with_findings["output"]["annotations"][0]
        self.assertEqual(annotation["annotation_level"], "warning")
        self.assertEqual(annotation["path"], SLACK_PATH)
        self.assertEqual(clean["conclusion"], "success")
        self.assertEqual(skipped["conclusion"], "neutral")
        self.assertEqual(failed["conclusion"], "neutral")
        summary = render_summary(report, registry, PR.head_sha)
        self.assertTrue(
            summary.startswith(
                f"<!-- semantic-lint:summary findings={len(report.findings)} -->"
            )
        )
        self.assertIn("| Total |", summary)

    def test_publishes_on_the_fetched_head(self) -> None:
        registry = load_registry(self.rules_dir)
        github = FakeGitHub(head_sha=PR.head_sha)
        body = check_run(self._report(), registry, PR.head_sha)

        self.assertTrue(github.publish_check_run(PR.number, body))
        self.assertEqual(github.posted, [("check-runs", body)])

    def test_publishes_nothing_when_the_head_moved(self) -> None:
        registry = load_registry(self.rules_dir)
        github = FakeGitHub(head_sha="newer2222")
        body = check_run(self._report(), registry, PR.head_sha)

        self.assertFalse(github.publish_check_run(PR.number, body))
        self.assertEqual(github.posted, [])


if __name__ == "__main__":
    unittest.main()
