"""Eval cases, the Jev answer cache, and threshold choice."""

import json
import math
import tempfile
import unittest
from pathlib import Path

from semantic_lint.evaluate import (
    CachedJev,
    EvalData,
    Label,
    Point,
    Split,
    build_cases,
    choose_threshold,
    split_of,
    wilson_lower,
)
from semantic_lint.registry import (
    CalibrationPolicy,
    CommentId,
    RuleId,
    Severity,
    load_registry,
)

from tests.rule_fixtures import RULE_ID, RulesDirTest
from tests.test_screen import FakeJev, comment_window

POLICY = CalibrationPolicy(
    confidence=0.8,
    min_positives=2,
    report_percent=30,
    min_precision={Severity.FIX: 0.5, Severity.NIT: 0.6},
)
POS, NEG = Label.POSITIVE, Label.NEGATIVE
PATH = "backend/onyx/connectors/slack/utils.py"
# Two hunks of one file at the commit the comments were made on.
REVIEW_PATCH = """\
@@ -10,3 +10,6 @@ def load(raw: str) -> dict:
     try:
+        value = json.loads(raw)
+    except ValueError:
+        pass
     return value
@@ -40,2 +43,3 @@ def parse(raw: str) -> int:
     text = raw.strip()
+    return int(text)
@@ -80,2 +84,4 @@ def save(value: dict) -> None:
     path.write_text(json.dumps(value))
+    logger.info("saved %s", path)
+    return None
"""


def _comment(comment_id: int, hunk: str) -> dict[str, object]:
    return {
        "id": comment_id,
        "pr": 4242,
        "path": PATH,
        "commit_id": "c0ffee",
        "diff_hunk": hunk,
    }


class ThresholdTest(unittest.TestCase):
    def test_wilson_lower_bound(self) -> None:
        self.assertEqual(wilson_lower(0, 0, 0.8), 0.0)
        self.assertAlmostEqual(wilson_lower(5, 5, 0.8), 0.7527, places=3)
        self.assertAlmostEqual(wilson_lower(5, 10, 0.8), 0.3122, places=3)

    def test_picks_the_lowest_threshold_that_meets_the_floor(self) -> None:
        tune = [(0.9, POS), (0.8, POS), (0.7, POS), (0.6, NEG), (0.5, POS), (0.4, NEG)]
        tune += [(0.3, NEG)] * 20
        point = choose_threshold(tune, POLICY, floor=0.5)
        assert point is not None
        self.assertEqual(point.threshold, 0.5)
        self.assertEqual((point.true_positives, point.false_positives), (4, 1))

    def test_falls_back_to_the_best_lower_bound_for_shadow(self) -> None:
        tune = [(0.9, POS), (0.85, NEG), (0.8, POS), (0.7, NEG), (0.6, POS)]
        point = choose_threshold(tune, POLICY, floor=0.9)
        assert point is not None
        # 3 of 5 has a higher lower bound than 2 of 3.
        self.assertEqual(point.threshold, 0.6)

    def test_needs_min_positives(self) -> None:
        self.assertIsNone(choose_threshold([(0.9, POS), (0.2, NEG)], POLICY, 0.5))

    def test_precision_is_nan_with_nothing_flagged(self) -> None:
        self.assertTrue(math.isnan(Point(0.95, 0, 0, 2).precision))
        self.assertEqual(Point(0.95, 0, 0, 2).recall, 0.0)

    def test_split_is_stable_per_pr(self) -> None:
        self.assertEqual(split_of(4242, 30), split_of(4242, 30))
        splits = [split_of(pr, 30) for pr in range(1000)]
        self.assertAlmostEqual(splits.count(Split.REPORT) / 1000, 0.3, delta=0.05)


class CachedJevTest(RulesDirTest):
    def test_asks_jev_only_for_unseen_questions(self) -> None:
        registry = load_registry(self.rules_dir)
        cache_file = self.rules_dir / "cache" / "jev.jsonl"
        window = comment_window()
        inner = FakeJev(0.8)

        first, usage = CachedJev(inner, cache_file).ask("m", window, registry.rules)
        again, cached_usage = CachedJev(inner, cache_file).ask(
            "m", window, registry.rules
        )

        self.assertEqual(first, {RuleId(RULE_ID): 0.8})
        self.assertEqual(again, first)
        self.assertEqual(len(inner.asked), 1)
        self.assertEqual((usage.requests, cached_usage.requests), (1, 0))
        CachedJev(inner, cache_file).ask("other-model", window, registry.rules)
        self.assertEqual(len(inner.asked), 2)


class BuildCasesTest(RulesDirTest):
    def test_labels_windows_from_the_review_time_diff(self) -> None:
        registry = load_registry(self.rules_dir)
        with tempfile.TemporaryDirectory() as temp:
            seed = Path(temp)
            (seed / "review_diffs").mkdir()
            (seed / "review_diffs" / "4242_c0ffee.json").write_text(
                json.dumps(
                    {
                        "files": [
                            {"filename": PATH, "status": "x", "patch": REVIEW_PATCH}
                        ]
                    }
                )
            )
            rows = [
                # A source of the rule, on the `pass` line of the first hunk.
                _comment(3344414001, "@@ -10,2 +10,4 @@\n     try:\n+        pass"),
                # The comment the rule shows Jev as a flag example.
                _comment(2528675138, "@@ -40,1 +43,2 @@\n+    return int(text)"),
                # Comments whose lines no longer exist at this commit.
                _comment(2496441566, "@@ -1,1 +1,2 @@\n+        return []"),
                _comment(3624910226, "@@ -1,1 +1,2 @@\n+        provider_id = -1"),
            ]
            (seed / "pull_comments.jsonl").write_text(
                "".join(json.dumps(row) + "\n" for row in rows)
            )
            data = EvalData(seed / "cache", [seed], github=None)

            cases, unanchored = build_cases(registry, data)

        rule_id = RuleId(RULE_ID)
        self.assertEqual([case.label(rule_id) for case in cases], [POS, None, NEG])
        self.assertIn(CommentId(2496441566), unanchored)
        self.assertNotIn(CommentId(3344414001), unanchored)


if __name__ == "__main__":
    unittest.main()
