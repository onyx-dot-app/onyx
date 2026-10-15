"""The files the workflow posts: the check run body and the summary comment."""

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from semantic_lint.github import (
    CHECK_RUN_FILE,
    SUMMARY_FILE,
    SUMMARY_MARKER,
    write_outputs,
)
from semantic_lint.registry import load_registry
from semantic_lint.review import review

from tests.rule_fixtures import RulesDirTest
from tests.test_review import PR, FakeLlm
from tests.test_screen import SLACK_PATH, FakeJev, calibrate


class WriteOutputsTest(RulesDirTest):
    def _write(self, clean: bool) -> tuple[dict[str, object], str]:
        registry = load_registry(self.rules_dir)
        calibrate(registry, registry.rules[0], threshold=0.6, lower=0.9)
        registry = load_registry(self.rules_dir)
        report = review(PR, registry, FakeJev(0.7), FakeLlm())
        if clean:
            report = replace(report, findings=())
        with tempfile.TemporaryDirectory() as temp:
            write_outputs(report, registry, Path(temp))
            check_run = json.loads((Path(temp) / CHECK_RUN_FILE).read_text())
            summary = (Path(temp) / SUMMARY_FILE).read_text()
        return check_run, summary

    def test_findings_give_a_neutral_check_run_with_annotations(self) -> None:
        check_run, summary = self._write(clean=False)

        self.assertEqual(check_run["name"], "semantic-lint")
        self.assertEqual(check_run["head_sha"], PR.head_sha)
        self.assertEqual(check_run["conclusion"], "neutral")
        output = check_run["output"]
        assert isinstance(output, dict)
        annotation = output["annotations"][0]
        self.assertEqual(annotation["path"], SLACK_PATH)
        self.assertEqual(annotation["annotation_level"], "warning")
        self.assertEqual(output["summary"], summary)
        first, second = summary.splitlines()[:2]
        self.assertEqual(first, SUMMARY_MARKER)
        self.assertEqual(second, "<!-- semantic-lint: findings -->")
        self.assertIn("| Total |", summary)
        self.assertIn(f"blob/{PR.head_sha}/{SLACK_PATH}#L", summary)

    def test_a_clean_run_succeeds(self) -> None:
        check_run, summary = self._write(clean=True)

        self.assertEqual(check_run["conclusion"], "success")
        self.assertEqual(summary.splitlines()[1], "<!-- semantic-lint: clean -->")


if __name__ == "__main__":
    unittest.main()
