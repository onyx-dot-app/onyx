"""Exercise which runs cancel_superseded_runs.py cancels."""

import importlib.util
import unittest
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "cancel_superseded_runs",
    Path(__file__).with_name("cancel_superseded_runs.py"),
)
assert _SPEC and _SPEC.loader
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
Run = _MODULE.Run
decide = _MODULE.decide


def run(
    run_id: int,
    suite: int,
    status: str = "in_progress",
    event: str = "pull_request",
    branch: str = "chore/top",
    repo: str = "onyx-dot-app/onyx",
) -> Run:
    return Run(
        id=run_id,
        check_suite_id=suite,
        status=status,
        event=event,
        head_branch=branch,
        head_repo=repo,
    )


class DecideTest(unittest.TestCase):
    def test_newest_of_two_same_second_runs_cancels_the_older(self) -> None:
        older, newer = run(100, 500), run(101, 501)
        decision = decide(newer, [older, newer])
        self.assertIsNone(decision.superseded_by)
        self.assertEqual(decision.to_cancel, [100])

    def test_older_run_cancels_itself(self) -> None:
        older, newer = run(100, 500), run(101, 501)
        decision = decide(older, [older, newer])
        self.assertEqual(decision.superseded_by, 101)
        self.assertEqual(decision.to_cancel, [100])

    def test_suite_id_decides_when_run_ids_disagree(self) -> None:
        # Required checks read the newest suite, so the suite id decides.
        low_suite, high_suite = run(101, 500), run(100, 501)
        self.assertEqual(decide(high_suite, [low_suite, high_suite]).to_cancel, [101])
        self.assertEqual(decide(low_suite, [low_suite, high_suite]).superseded_by, 100)

    def test_rerun_of_an_older_run_cancels_itself(self) -> None:
        # A rerun keeps its suite id, so it still does not count once a newer
        # suite exists, even a finished one.
        rerun, newest = run(100, 500), run(101, 501, status="completed")
        decision = decide(rerun, [rerun, newest])
        self.assertEqual(decision.superseded_by, 101)
        self.assertEqual(decision.to_cancel, [100])

    def test_rerun_of_the_newest_run_keeps_running(self) -> None:
        older, newest = run(100, 500, status="completed"), run(101, 501)
        decision = decide(newest, [older, newest])
        self.assertIsNone(decision.superseded_by)
        self.assertEqual(decision.to_cancel, [])

    def test_new_commit_cancels_every_unfinished_older_run(self) -> None:
        runs = [
            run(98, 498, status="completed"),
            run(99, 499, status="queued"),
            run(100, 500, status="waiting"),
            run(101, 501),
        ]
        self.assertEqual(decide(runs[-1], runs).to_cancel, [99, 100])

    def test_ignores_other_branches_events_and_forks(self) -> None:
        own = run(101, 501)
        runs = [
            own,
            run(90, 490, branch="chore/other"),
            run(91, 491, event="merge_group"),
            run(92, 492, event="push"),
            run(93, 493, repo="someone/onyx"),
            run(102, 502, branch="chore/other"),
            run(103, 503, repo="someone/onyx"),
        ]
        decision = decide(own, runs)
        self.assertIsNone(decision.superseded_by)
        self.assertEqual(decision.to_cancel, [])

    def test_only_run(self) -> None:
        own = run(101, 501)
        self.assertEqual(decide(own, [own]).to_cancel, [])


if __name__ == "__main__":
    unittest.main()
