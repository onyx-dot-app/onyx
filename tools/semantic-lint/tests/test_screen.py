"""screen() batching, thresholds and the seal. One live Jev call when opted in."""

import os
import unittest
from collections.abc import Sequence
from dataclasses import replace
from datetime import date

from semantic_lint.diff import Window, cut_windows
from semantic_lint.registry import (
    Calibration,
    Registry,
    Rule,
    RuleId,
    WindowSettings,
    load_registry,
    write_calibration,
)
from semantic_lint.screen import (
    Jev,
    Mode,
    Usage,
    active_threshold,
    rule_mode,
    screen,
    seal,
)

from tests.rule_fixtures import RULE_ID, RulesDirTest
from tests.test_diff import FIXTURES

SLACK_PATH = "backend/onyx/context/search/federated/slack_search.py"


def comment_window() -> Window:
    hunk = (FIXTURES / "comment_2528675138.hunk").read_text()
    return cut_windows(SLACK_PATH, hunk, 40)[-1]


class FakeJev(Jev):
    def __init__(self, p: float) -> None:
        super().__init__(api_key="")
        self.p: float = p
        self.asked: list[tuple[str, str, list[RuleId]]] = []

    def ask(
        self, model: str, window: Window, rules: Sequence[Rule]
    ) -> tuple[dict[RuleId, float], Usage]:
        self.asked.append((model, window.id, [rule.id for rule in rules]))
        return {rule.id: self.p for rule in rules}, Usage(1, 100, 5, 0.1)


def calibrate(registry: Registry, rule: Rule, threshold: float, lower: float) -> Rule:
    calibration = Calibration(
        threshold=threshold,
        precision=0.6,
        recall=0.5,
        positives=8,
        negatives=500,
        tune_precision_lower=lower,
        jev_model=registry.settings.jev_model,
        evaluated_on=date(2026, 10, 15),
        seal=seal(rule, threshold, registry.settings),
    )
    write_calibration(rule, calibration)
    return replace(rule, calibration=calibration)


class ScreenTest(RulesDirTest):
    def test_asks_in_scope_rules_once_per_window(self) -> None:
        registry = load_registry(self.rules_dir)
        window = comment_window()
        test_window = replace(window, path="backend/tests/unit/test_slack.py")
        jev = FakeJev(0.7)

        screening = screen([window, test_window], registry, jev)

        self.assertEqual(jev.asked, [("jev-1.13.0", window.id, [RuleId(RULE_ID)])])
        self.assertEqual([score.p for score in screening.scores], [0.7])
        self.assertEqual(screening.usage.input_tokens, 100)
        self.assertEqual(screening.hits(registry), [])

    def test_hits_apply_the_sealed_threshold(self) -> None:
        registry = load_registry(self.rules_dir)
        calibrate(registry, registry.rules[0], threshold=0.6, lower=0.55)
        registry = load_registry(self.rules_dir)
        window = comment_window()

        [hit] = screen([window], registry, FakeJev(0.7)).hits(registry)
        self.assertAlmostEqual(hit.margin, 0.1)
        self.assertEqual(hit.window, window)
        self.assertEqual(screen([window], registry, FakeJev(0.59)).hits(registry), [])


class SealTest(RulesDirTest):
    def test_any_change_to_the_ask_breaks_the_seal(self) -> None:
        registry = load_registry(self.rules_dir)
        calibrate(registry, registry.rules[0], threshold=0.6, lower=0.55)
        registry = load_registry(self.rules_dir)
        [rule] = registry.rules
        settings = registry.settings
        self.assertEqual(active_threshold(rule, settings), 0.6)
        self.assertEqual(rule_mode(rule, settings), Mode.LIVE)

        edited = replace(
            rule, question=replace(rule.question, instructions="Something else.")
        )
        self.assertIsNone(active_threshold(edited, settings))
        self.assertEqual(rule_mode(edited, settings), Mode.INACTIVE)
        wider = replace(settings, window=WindowSettings(max_lines=12))
        self.assertIsNone(active_threshold(rule, wider))
        bumped = replace(settings, jev_model="jev-9.9.9")
        self.assertIsNone(active_threshold(rule, bumped))
        assert rule.calibration is not None
        hand_tuned = replace(rule.calibration, threshold=0.3)
        self.assertIsNone(
            active_threshold(replace(rule, calibration=hand_tuned), settings)
        )

    def test_a_rule_below_the_precision_floor_runs_in_shadow(self) -> None:
        registry = load_registry(self.rules_dir)
        rule = calibrate(registry, registry.rules[0], threshold=0.6, lower=0.2)
        self.assertEqual(rule_mode(rule, registry.settings), Mode.SHADOW)


@unittest.skipUnless(os.environ.get("SEMANTIC_LINT_LIVE"), "set SEMANTIC_LINT_LIVE=1")
class LiveJevTest(RulesDirTest):
    def test_jev_flags_a_silent_except(self) -> None:
        registry = load_registry(self.rules_dir)
        jev = Jev(os.environ["TYPESAFE_API_KEY"])

        screening = screen([comment_window()], registry, jev)

        [score] = screening.scores
        self.assertGreater(score.p, 0.5)
        self.assertGreater(screening.usage.input_tokens, 0)


if __name__ == "__main__":
    unittest.main()
