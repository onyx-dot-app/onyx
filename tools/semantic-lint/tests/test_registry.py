"""Rule files parse into typed rules, bad files fail loudly, and eval writes calibration."""

import tomllib
import unittest
from dataclasses import replace
from datetime import date

from semantic_lint.registry import (
    Calibration,
    CommentId,
    Family,
    RegistryError,
    RuleId,
    Severity,
    load_registry,
    precision_floor,
    write_calibration,
)

from tests.rule_fixtures import RULE_ID, RULE_TOML, RulesDirTest

CALIBRATION = Calibration(
    threshold=0.42,
    precision=0.5,
    recall=float("nan"),
    positives=7,
    negatives=812,
    tune_precision_lower=0.31,
    jev_model="jev-1.13.0",
    evaluated_on=date(2026, 10, 15),
    seal="sha256:abc",
)


class LoadRegistryTest(RulesDirTest):
    def test_parses_the_rule(self) -> None:
        registry = load_registry(self.rules_dir)
        [rule] = registry.rules

        self.assertEqual(rule.id, RuleId(RULE_ID))
        self.assertEqual(rule.severity, Severity.FIX)
        self.assertEqual(rule.family, Family.OTHER)
        self.assertEqual(
            rule.flag_examples[0].code.splitlines()[0][:13], "+            "
        )
        self.assertEqual(rule.shown_comments, {2528675138, 2496441566})
        self.assertEqual(rule.question.true_not_for, ())
        self.assertIsNone(rule.calibration)
        self.assertEqual(registry.in_scope("backend/onyx/a.py"), (rule,))
        self.assertEqual(registry.in_scope("backend/tests/unit/test_a.py"), ())
        self.assertEqual(registry.in_scope("backend/uv.lock"), ())

    def test_the_committed_registry_loads(self) -> None:
        load_registry()

    def test_a_rule_can_lower_its_precision_floor(self) -> None:
        [rule] = load_registry(self.rules_dir).rules
        settings = load_registry(self.rules_dir).settings
        self.assertEqual(precision_floor(rule, settings), 0.5)
        self.rule_file.write_text(
            RULE_TOML.replace(
                "needs_repo_search = false",
                "needs_repo_search = false\nmin_precision = 0.4",
            )
        )
        [rule] = load_registry(self.rules_dir).rules
        self.assertEqual(precision_floor(rule, settings), 0.4)

    def test_rejects_invalid_rule_files(self) -> None:
        cases = {
            "unknown key": RULE_TOML.replace("title =", "titel = 1\ntitle ="),
            "missing key": RULE_TOML.replace('family = "other"\n', ""),
            "bad family": RULE_TOML.replace('family = "other"', 'family = "style"'),
            "empty sources": RULE_TOML.replace(
                "sources = [2528675138, 3344414001, 3624910226]", "sources = []"
            ),
            "hint without search": RULE_TOML.replace(
                "needs_repo_search = false",
                'needs_repo_search = false\nrepo_search_hint = "def parse_"',
            ),
            "said without comment": RULE_TOML.replace("comment = 2528675138\n", ""),
            "floor above one": RULE_TOML.replace(
                "needs_repo_search = false",
                "needs_repo_search = false\nmin_precision = 1.5",
            ),
            "calibration not last": RULE_TOML.replace(
                "[[flag]]", "[calibration]\nthreshold = 0.5\n\n[[flag]]"
            ),
        }
        for name, text in cases.items():
            with self.subTest(name):
                self.rule_file.write_text(text)
                with self.assertRaises(RegistryError):
                    load_registry(self.rules_dir)

    def test_rejects_a_file_name_that_is_not_a_rule_id(self) -> None:
        (self.rules_dir / "Bad_Name.toml").write_text(RULE_TOML)
        with self.assertRaises(RegistryError):
            load_registry(self.rules_dir)

    def test_only_rejects_unknown_ids(self) -> None:
        registry = load_registry(self.rules_dir)
        self.assertEqual(len(registry.only([RuleId(RULE_ID)]).rules), 1)
        with self.assertRaises(RegistryError):
            registry.only([RuleId("no-such-rule")])


class WriteCalibrationTest(RulesDirTest):
    def test_adds_replaces_and_removes_the_table(self) -> None:
        [rule] = load_registry(self.rules_dir).rules
        self.assertTrue(write_calibration(rule, CALIBRATION))
        [rule] = load_registry(self.rules_dir).rules
        assert rule.calibration is not None
        self.assertEqual(rule.calibration.threshold, 0.42)
        self.assertEqual(rule.calibration.evaluated_on, date(2026, 10, 15))
        self.assertTrue(self.rule_file.read_text().startswith(RULE_TOML.rstrip()))

        later = replace(CALIBRATION, evaluated_on=date(2026, 11, 1))
        self.assertFalse(write_calibration(rule, later))

        self.assertTrue(write_calibration(rule, replace(CALIBRATION, threshold=0.5)))
        [rule] = load_registry(self.rules_dir).rules
        assert rule.calibration is not None
        self.assertEqual(rule.calibration.threshold, 0.5)
        self.assertEqual(self.rule_file.read_text().count("[calibration]"), 1)

        self.assertTrue(write_calibration(rule, None))
        self.assertEqual(self.rule_file.read_text(), RULE_TOML.rstrip() + "\n")
        tomllib.loads(self.rule_file.read_text())

    def test_sources_are_comment_ids(self) -> None:
        [rule] = load_registry(self.rules_dir).rules
        self.assertIn(CommentId(3344414001), rule.sources)
        self.assertEqual(rule.near_misses, {CommentId(2496441566)})


if __name__ == "__main__":
    unittest.main()
