"""Window cutting on real patches and review comment hunks from onyx-dot-app/onyx."""

import unittest
from pathlib import Path

from semantic_lint.diff import Added, Context, Removed, cut_windows, parse_hunks

FIXTURES: Path = Path(__file__).with_name("fixtures")
TRACING_PATH = "backend/onyx/llm/tracing_wrap.py"


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text()


class ParseHunksTest(unittest.TestCase):
    def test_numbers_lines_from_the_hunk_header(self) -> None:
        hunks = parse_hunks(_fixture("tracing_wrap.patch"))

        self.assertEqual(hunks[0].header, "")
        self.assertEqual(hunks[1].header, "def wrap_stream(")
        self.assertEqual(hunks[0].lines[0], Context(23, 23, ""))
        self.assertEqual(
            hunks[0].lines[3],
            Added(
                26,
                "    from onyx.llm.model_response import ChatCompletionDeltaToolCall",
            ),
        )
        removed = [line for line in hunks[1].lines if isinstance(line, Removed)]
        self.assertEqual(removed[0].old_line, 165)

    def test_rejects_text_that_is_not_a_diff(self) -> None:
        with self.assertRaises(ValueError):
            parse_hunks("this is not a patch")


class CutWindowsTest(unittest.TestCase):
    def test_invariants_hold_on_a_real_patch(self) -> None:
        patch = _fixture("tracing_wrap.patch")
        hunk_ends = [hunk.lines[-1] for hunk in parse_hunks(patch)]
        for max_lines in (8, 12, 40):
            windows = cut_windows(TRACING_PATH, patch, max_lines)
            self.assertTrue(windows)
            for window in windows:
                self.assertLessEqual(len(window.lines), max_lines)
                self.assertTrue(window.anchor_lines)
                if window.lines[-1] not in hunk_ends:
                    self.assertFalse(
                        window.lines[-1].text.rstrip().endswith((":", "{", "("))
                    )

    def test_windows_do_not_overlap_and_keep_every_added_line(self) -> None:
        patch = _fixture("tracing_wrap.patch")
        windows = cut_windows(TRACING_PATH, patch, 12)
        added_in_windows = [line for window in windows for line in window.anchor_lines]
        added_in_patch = [
            line.new_line
            for hunk in parse_hunks(patch)
            for line in hunk.lines
            if isinstance(line, Added)
        ]
        self.assertEqual(added_in_windows, added_in_patch)

    def test_ids_are_stable_and_ignore_line_numbers(self) -> None:
        patch = _fixture("tracing_wrap.patch")
        first = [window.id for window in cut_windows(TRACING_PATH, patch, 12)]
        second = [window.id for window in cut_windows(TRACING_PATH, patch, 12)]
        moved = patch.replace("@@ -23,8 +23,10 @@", "@@ -40,8 +40,10 @@", 1)
        shifted = [window.id for window in cut_windows(TRACING_PATH, moved, 12)]

        self.assertEqual(first, second)
        self.assertEqual(first, shifted)
        self.assertEqual(len(set(first)), len(first))
        self.assertNotEqual(
            first, [window.id for window in cut_windows("other.py", patch, 12)]
        )

    def test_drops_pure_deletion_runs(self) -> None:
        patch = "@@ -1,3 +1,1 @@\n-gone = 1\n-also_gone = 2\n kept = 3\n"
        self.assertEqual(cut_windows("a.py", patch, 40), [])

    def test_last_window_of_a_comment_hunk_covers_the_commented_line(self) -> None:
        # Review comment 2528675138 ("this deserves at least a debug log") sits
        # on the last line of its diff_hunk, `pass` at new line 587.
        windows = cut_windows(
            "backend/onyx/context/search/federated/slack_search.py",
            _fixture("comment_2528675138.hunk"),
            40,
        )
        last = windows[-1]

        self.assertTrue(last.covers_new_line(587))
        self.assertEqual(last.last_new_line, 587)
        self.assertIn("+            except ValidationError:", last.render())
        self.assertEqual(sum(window.covers_new_line(587) for window in windows), 1)
        self.assertIn("   587 +                pass", last.render_numbered())


if __name__ == "__main__":
    unittest.main()
