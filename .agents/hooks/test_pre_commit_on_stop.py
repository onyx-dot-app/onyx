"""Exercise hook events in disposable Git repositories."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HOOK = Path(__file__).with_name("pre_commit_on_stop.py")


class PreCommitOnStopTests(unittest.TestCase):
    def setUp(self) -> None:
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.repo = Path(self.scratch.name)
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        (self.repo / "old.txt").write_text("original\n")
        (self.repo / "new.txt").write_text("original\n")
        subprocess.run(["git", "add", "old.txt", "new.txt"], cwd=self.repo, check=True)
        subprocess.run(
            ["git", "-c", "core.hooksPath=/dev/null", "commit", "-qm", "baseline"],
            cwd=self.repo,
            env={
                **os.environ,
                "GIT_AUTHOR_NAME": "Hook Test",
                "GIT_AUTHOR_EMAIL": "hook@example.invalid",
                "GIT_COMMITTER_NAME": "Hook Test",
                "GIT_COMMITTER_EMAIL": "hook@example.invalid",
            },
            check=True,
        )

    def run_hook(
        self, event: str, *, path: str = "/usr/bin:/bin"
    ) -> subprocess.CompletedProcess[str]:
        payload = {
            "session_id": "test-session",
            "cwd": str(self.repo),
            "hook_event_name": event,
        }
        return subprocess.run(
            [sys.executable, str(HOOK)],
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            env={**os.environ, "PATH": path},
            check=False,
        )

    def test_missing_config_reports_coverage_gap(self) -> None:
        result = self.run_hook("UserPromptSubmit")

        self.assertEqual(result.returncode, 0)
        self.assertIn("pre-commit config", json.loads(result.stdout)["systemMessage"])

    def test_git_lookup_failure_reports_coverage_gap(self) -> None:
        with tempfile.TemporaryDirectory() as scratch:
            payload = {
                "session_id": "test-session",
                "cwd": scratch,
                "hook_event_name": "Stop",
            }
            result = subprocess.run(
                [sys.executable, str(HOOK)],
                input=json.dumps(payload),
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(result.returncode, 0)
        self.assertIn("Git", json.loads(result.stdout)["systemMessage"])

    def test_missing_snapshot_reports_coverage_gap(self) -> None:
        (self.repo / ".pre-commit-config.yaml").write_text("repos: []\n")

        result = self.run_hook("Stop")

        self.assertEqual(result.returncode, 0)
        self.assertIn("prompt snapshot", json.loads(result.stdout)["systemMessage"])

    def test_restored_config_does_not_check_an_older_turn(self) -> None:
        config = self.repo / ".pre-commit-config.yaml"
        config.write_text("repos: []\n")
        bin_dir = self.repo / "bin"
        bin_dir.mkdir()
        call_log = self.repo / "pre-commit-call.txt"
        executable = bin_dir / "pre-commit"
        executable.write_text(f"#!/bin/sh\nprintf '%s\\n' \"$@\" > '{call_log}'\n")
        executable.chmod(0o755)
        path = f"{bin_dir}:/usr/bin:/bin"

        self.assertEqual(self.run_hook("UserPromptSubmit", path=path).returncode, 0)
        (self.repo / "old.txt").write_text("older turn\n")
        config.unlink()
        missing = self.run_hook("UserPromptSubmit", path=path)
        self.assertIn("pre-commit config", json.loads(missing.stdout)["systemMessage"])
        (self.repo / "new.txt").write_text("current turn\n")
        config.write_text("repos: []\n")

        result = self.run_hook("Stop", path=path)

        self.assertEqual(result.returncode, 0)
        self.assertIn("new.txt", call_log.read_text().splitlines())
        self.assertNotIn("old.txt", call_log.read_text().splitlines())

    def test_missing_pre_commit_reports_coverage_gap(self) -> None:
        (self.repo / ".pre-commit-config.yaml").write_text("repos: []\n")
        reminder = self.repo / ".agents" / "feature-map" / "stale_docs.py"
        reminder.parent.mkdir(parents=True)
        reminder.write_text("print('feature-map note')\n")
        self.assertEqual(self.run_hook("UserPromptSubmit").returncode, 0)
        (self.repo / "new.txt").write_text("changed\n")

        result = self.run_hook("Stop")

        self.assertEqual(result.returncode, 0)
        self.assertIn(
            "pre-commit executable", json.loads(result.stdout)["systemMessage"]
        )
        self.assertIn("feature-map note", json.loads(result.stdout)["systemMessage"])

    def test_stop_checks_only_file_changed_after_prompt(self) -> None:
        (self.repo / ".pre-commit-config.yaml").write_text("repos: []\n")
        (self.repo / "old.txt").write_text("older change\n")
        bin_dir = self.repo / "bin"
        bin_dir.mkdir()
        call_log = self.repo / "pre-commit-call.txt"
        executable = bin_dir / "pre-commit"
        executable.write_text(f"#!/bin/sh\nprintf '%s\\n' \"$@\" > '{call_log}'\n")
        executable.chmod(0o755)
        path = f"{bin_dir}:/usr/bin:/bin"

        self.assertEqual(self.run_hook("UserPromptSubmit", path=path).returncode, 0)
        (self.repo / "new.txt").write_text("new change\n")
        result = self.run_hook("Stop", path=path)

        self.assertEqual(result.returncode, 0)
        self.assertEqual(
            call_log.read_text().splitlines(), ["run", "--files", "new.txt"]
        )


if __name__ == "__main__":
    unittest.main()
