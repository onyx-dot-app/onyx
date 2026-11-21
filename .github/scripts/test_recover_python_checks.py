"""Replay the PR and attempt-one metadata recorded while #17989 was open."""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIXTURE = HERE / "fixtures/python-checks-17989.json"
TARGET = "44157156583"
REPO = "repos/onyx-dot-app/onyx"

# Only the expected GETs and the original run's rerun endpoint exist in this fake.
GH = """#!/usr/bin/env bash
set -eu
repo=repos/onyx-dot-app/onyx
case "$*" in
  "api $repo/pulls/17989 --jq "*)
    if [[ -e read-pr && -f changed-pr ]]; then cat changed-pr; else cat pr; fi | jq -c "$4"
    touch read-pr ;;
  "api $repo/actions/workflows/pr-python-checks.yml/runs?branch=roshan%2Fci-split-slow-integration-shards&per_page=100")
    if [[ -e read-runs && -f changed-runs ]]; then cat changed-runs; else cat runs; fi
    touch read-runs ;;
  "api $repo/actions/runs/44157156351/attempts/1/jobs?per_page=100") cat passed ;;
  "api $repo/actions/runs/44157156583/attempts/1/jobs?per_page=100") cat cancelled ;;
  "api --method POST $repo/actions/runs/44157156583/rerun") echo "$4" >> posts ;;
  *) echo "Unexpected gh request: $*" >&2; exit 1 ;;
esac
"""


class RecoveryTest(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        gh = self.root / "gh"
        gh.write_text(GH)
        gh.chmod(0o755)
        self.data = json.loads(FIXTURE.read_text())

    def run_command(self, *args: str) -> tuple[str, list[str]]:
        runs = self.data["runs"]
        files = {
            "pr": self.data["pr"],
            "runs": {"total_count": len(runs), "workflow_runs": runs},
            "passed": self.data["jobs"][0],
            "cancelled": self.data["jobs"][1],
        }
        for name, value in files.items():
            (self.root / name).write_text(json.dumps(value))
        result = subprocess.check_output(
            [HERE / "recover-python-checks.sh", "17989", TARGET, *args],
            cwd=self.root,
            env={**os.environ, "PATH": f"{self.root}:{os.environ['PATH']}"},
            text=True,
        )
        posts = self.root / "posts"
        return result, posts.read_text().splitlines() if posts.exists() else []

    def test_recorded_pair(self) -> None:
        message, posts = self.run_command()
        self.assertIn("Eligible", message)
        self.assertEqual(posts, [])
        _, posts = self.run_command("--apply")
        self.assertEqual(posts, [f"{REPO}/actions/runs/{TARGET}/rerun"])

    def assert_skips(self) -> None:
        message, posts = self.run_command("--apply")
        self.assertIn("Skip", message)
        self.assertEqual(posts, [])

    def test_ineligible_pair(self) -> None:
        for field, value in [
            ("run_attempt", 2),
            ("created_at", "later"),
            ("status", "queued"),
            ("conclusion", "failure"),
            ("id", 123),
            ("run_number", 64657),
            ("event", "push"),
            ("path", "another-workflow.yml"),
            ("head_sha", "old"),
            ("pull_requests", []),
        ]:
            with self.subTest(field=field):
                self.data = json.loads(FIXTURE.read_text())
                self.data["runs"][1][field] = value
                self.assert_skips()

    def test_wrong_pr_or_ref(self) -> None:
        for key, field, value in [
            ("head", "sha", "stale"),
            ("base", "sha", "stale"),
            ("base", "ref", "other"),
            ("head", "repo", {"id": 1}),
        ]:
            with self.subTest(key=key, field=field):
                self.data = json.loads(FIXTURE.read_text())
                self.data["runs"][0]["pull_requests"][0][key][field] = value
                self.assert_skips()
        self.data = json.loads(FIXTURE.read_text())
        self.data["runs"][1]["pull_requests"][0]["number"] = 1
        self.assert_skips()

    def test_active_other_head(self) -> None:
        self.data["runs"].append({"status": "in_progress", "head_sha": "other"})
        self.assert_skips()

    def test_cancelled_run_created_job(self) -> None:
        self.data["jobs"][1] = self.data["jobs"][0]
        self.assert_skips()

    def test_required_job_did_not_pass(self) -> None:
        self.data["jobs"][0]["jobs"][1]["conclusion"] = "skipped"
        self.assert_skips()

    def test_pr_closed_before_write(self) -> None:
        changed = {**self.data["pr"], "state": "closed"}
        (self.root / "changed-pr").write_text(json.dumps(changed))
        self.assert_skips()

    def test_run_retried_before_write(self) -> None:
        runs = [self.data["runs"][0], {**self.data["runs"][1], "run_attempt": 2}]
        (self.root / "changed-runs").write_text(
            json.dumps({"total_count": len(runs), "workflow_runs": runs})
        )
        self.assert_skips()
