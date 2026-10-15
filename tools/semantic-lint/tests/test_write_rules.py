"""write_rules turns a registry draft into rule files the loader accepts."""

import contextlib
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from semantic_lint.registry import (
    RULES_DIR,
    SETTINGS_FILE,
    CommentId,
    RuleId,
    Severity,
    load_registry,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "mining"))

import write_rules  # noqa: E402

RULE_ID = "backend-error-handling-silent-except"
QUOTE = "this deserves at least a debug log"

DRAFT = {
    "rules": [
        {
            "id": RULE_ID,
            "title": "Do not swallow an exception without a log line",
            "statement": "Log the error or say why silence is safe.",
            "llm_guidance": "Ask for a log line with exc_info=True.",
            "scope_globs": ["backend/**/*.py"],
            "severity": "should_fix",
            "source_threads": [102, 101],
            "positive_examples": [
                {
                    "thread_id": 101,
                    "hunk_excerpt": "+            except ValidationError:\n+                pass",
                    "comment_excerpt": QUOTE,
                    "accepted": True,
                }
            ],
            "negative_examples": [
                {
                    "thread_id": 201,
                    "hunk_excerpt": "+    except ValidationError:",
                    "why_not": "expected outcome",
                }
            ],
            "jev_question": {
                "instructions": "An added `except` block swallows the exception.",
                "criteria": {
                    "true": {
                        "what": "The `except` body has no logger call and no raise.",
                        "examples": [
                            "except ValidationError:\n    pass",
                            "except KeyError:\n    return '''x'''",
                        ],
                    },
                    "false": {
                        "what": "The `except` body logs or re-raises.",
                        "not_for": "cleanup after a logged failure",
                        "examples": [
                            "except ValidationError:\n    return []  # not a tool call"
                        ],
                    },
                },
            },
            "criteria_example_sources": {
                "true": [{"thread_id": 101}, {"thread_id": None}],
                "false": [{"thread_id": 202}],
            },
            "needs_repo_search": True,
            "repo_search_hint": "the logging helpers in onyx/utils",
        }
    ],
    "never_flag": [
        "Do not flag a deliberate behavior change",
        {
            "anti_rule_id": "guarded-upstream",
            "dismissed_pattern": "Do not flag a guard\n the caller has",
        },
    ],
}

CORPUS = [
    {
        "id": 101,
        "pr": 1,
        "path": "backend/onyx/a.py",
        "diff_hunk": "@@ -1,3 +1,5 @@\n             try:\n"
        "+                parse()\n+            except ValidationError:\n+                pass",
        "body": "first line of 101\nsecond line",
    },
    {
        "id": 102,
        "pr": 2,
        "path": "backend/onyx/b.py",
        "diff_hunk": "@@ -1 +1,2 @@\n+    x = 1",
        "body": "probably should log these",
    },
    {
        "id": 201,
        "pr": 3,
        "path": "backend/onyx/c.py",
        "diff_hunk": "@@ -1 +1,3 @@\n+    except ValidationError:\n"
        "+        return []  # not a tool call",
        "body": "maybe log here?",
    },
]


class WriteRulesTest(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.rules_dir: Path = root / "rules"
        self.rules_dir.mkdir()
        shutil.copy(RULES_DIR / SETTINGS_FILE, self.rules_dir / SETTINGS_FILE)
        corpus = root / "corpus"
        corpus.mkdir()
        (corpus / "pull_comments.jsonl").write_text(
            "".join(json.dumps(row) + "\n" for row in CORPUS)
        )
        draft = root / "draft.json"
        draft.write_text(json.dumps(DRAFT))
        self.argv: list[str] = [
            str(draft),
            "--corpus",
            str(corpus),
            "--out",
            str(self.rules_dir),
        ]

    def _run(self) -> dict[str, bytes]:
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(write_rules.main(self.argv), 0)
        return {f.name: f.read_bytes() for f in sorted(self.rules_dir.iterdir())}

    def test_writes_a_rule_the_loader_accepts(self) -> None:
        first = self._run()
        registry = load_registry(self.rules_dir)
        [rule] = registry.rules

        self.assertEqual(rule.id, RuleId(RULE_ID))
        self.assertEqual(rule.severity, Severity.FIX)
        self.assertEqual(rule.sources, {CommentId(101), CommentId(102)})
        self.assertEqual(rule.near_misses, {CommentId(201), CommentId(202)})
        attributed, unattributed = rule.flag_examples
        assert attributed.quote is not None
        self.assertEqual(attributed.quote.comment, CommentId(101))
        self.assertEqual(attributed.quote.said, QUOTE)
        self.assertEqual(attributed.code, "except ValidationError:\n    pass")
        self.assertIsNone(unattributed.quote)
        self.assertEqual(unattributed.code, "except KeyError:\n    return '''x'''")
        self.assertEqual(
            rule.question.false_not_for, ("cleanup after a logged failure",)
        )
        [clean] = rule.clean_examples
        self.assertEqual(clean.comment, CommentId(202))
        self.assertEqual(rule.shown_comments, {CommentId(101), CommentId(202)})
        self.assertTrue(rule.needs_repo_search)
        self.assertEqual(rule.repo_search_hint, "the logging helpers in onyx/utils")
        self.assertEqual(
            registry.settings.llm.never_flag,
            (
                "Do not flag a deliberate behavior change",
                "Do not flag a guard the caller has",
            ),
        )

        self.assertEqual(self._run(), first)


if __name__ == "__main__":
    unittest.main()
