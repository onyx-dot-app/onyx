"""Check the hook diagnostic against isolated Git workspaces."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

DIAGNOSTIC = Path(__file__).with_name("hook_health.py")


class HookHealthCliTests(unittest.TestCase):
    def test_help_exits_without_traceback(self) -> None:
        result = subprocess.run(
            [sys.executable, str(DIAGNOSTIC), "--help"],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0)
        self.assertIn("usage:", result.stdout)
        self.assertEqual(result.stderr, "")

    def test_missing_project_reports_failed_json(self) -> None:
        with tempfile.TemporaryDirectory() as scratch:
            missing = Path(scratch) / "missing"
            result = subprocess.run(
                [sys.executable, str(DIAGNOSTIC), str(missing)],
                capture_output=True,
                text=True,
                check=False,
            )

        payload: dict[str, object] = json.loads(result.stdout)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(payload["status"], "failed")
        self.assertIn("project_not_directory", payload["reasons"])
        self.assertEqual(result.stderr, "")


class HookHealthTests(unittest.TestCase):
    def setUp(self) -> None:
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.repo = Path(self.scratch.name)
        self.codex_home = self.repo / "codex-home"
        self.codex_home.mkdir()
        subprocess.run(
            ["git", "init", "-q", str(self.repo)], check=True, capture_output=True
        )
        pre_commit = self.repo / ".venv" / "bin" / "pre-commit"
        pre_commit.parent.mkdir(parents=True)
        pre_commit.write_text("#!/bin/sh\nexit 0\n")
        pre_commit.chmod(0o755)

    def configure(
        self, project: Path, script: Path, command: str | None = None
    ) -> None:
        hooks = project / ".codex"
        hooks.mkdir(parents=True, exist_ok=True)
        command = command or f'python3 "{script}"'
        (hooks / "hooks.json").write_text(
            json.dumps(
                {
                    "hooks": {
                        event: [{"hooks": [{"type": "command", "command": command}]}]
                        for event in ("Stop", "UserPromptSubmit")
                    }
                }
            )
        )

    def diagnose(self, project: Path) -> tuple[int, dict[str, object]]:
        result = subprocess.run(
            [sys.executable, str(DIAGNOSTIC), str(project)],
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "PATH": "/usr/bin:/bin",
                "CODEX_HOME": str(self.codex_home),
            },
            check=False,
        )
        return result.returncode, json.loads(result.stdout)

    def test_healthy_checkout_reports_ok(self) -> None:
        (self.repo / ".pre-commit-config.yaml").write_text("repos: []\n")
        script = self.repo / ".agents" / "hooks" / "pre_commit_on_stop.py"
        script.parent.mkdir(parents=True)
        script.write_text("print('ok')\n")
        self.configure(self.repo, script)

        code, result = self.diagnose(self.repo)

        self.assertEqual(code, 1)
        self.assertEqual(result["status"], "degraded")
        self.assertEqual(result["static_status"], "ok")
        self.assertEqual(result["runtime_status"], "unverified")
        self.assertIn("runtime_activation_unverified", result["reasons"])

    def test_git_root_hook_command_reports_ok(self) -> None:
        (self.repo / ".pre-commit-config.yaml").write_text("repos: []\n")
        script = self.repo / ".agents" / "hooks" / "pre_commit_on_stop.py"
        script.parent.mkdir(parents=True)
        script.write_text("print('ok')\n")
        self.configure(
            self.repo,
            script,
            'python3 "$(git rev-parse --show-toplevel)/.agents/hooks/pre_commit_on_stop.py"',
        )

        code, result = self.diagnose(self.repo)

        self.assertEqual(code, 1)
        self.assertEqual(result["static_status"], "ok")
        self.assertEqual(result["hook_targets"], [str(script)])

    def test_disabled_prompt_hook_reports_degraded(self) -> None:
        (self.repo / ".pre-commit-config.yaml").write_text("repos: []\n")
        script = self.repo / "pre_commit_on_stop.py"
        script.write_text("print('ok')\n")
        self.configure(self.repo, script)
        (self.codex_home / "config.toml").write_text(
            f'[hooks.state."{self.repo}/.codex/hooks.json:user_prompt_submit:0:0"]\n'
            'enabled = false\ntrusted_hash = "sha256:example"\n'
        )

        code, result = self.diagnose(self.repo)

        self.assertEqual(code, 1)
        self.assertEqual(result["runtime_status"], "disabled")
        self.assertIn("user_prompt_submit_disabled", result["reasons"])

    def test_linked_worktree_uses_main_config_and_worktree_script(self) -> None:
        (self.repo / ".pre-commit-config.yaml").write_text("repos: []\n")
        script = self.repo / ".agents" / "hooks" / "pre_commit_on_stop.py"
        script.parent.mkdir(parents=True)
        script.write_text("print('main')\n")
        self.configure(
            self.repo,
            script,
            'python3 "$(git rev-parse --show-toplevel)/.agents/hooks/pre_commit_on_stop.py"',
        )
        subprocess.run(["git", "add", "."], cwd=self.repo, check=True)
        subprocess.run(
            [
                "git",
                "-c",
                "core.hooksPath=/dev/null",
                "-c",
                "user.name=Hook Test",
                "-c",
                "user.email=hook@example.invalid",
                "commit",
                "-qm",
                "baseline",
            ],
            cwd=self.repo,
            check=True,
        )
        worktree_scratch = tempfile.TemporaryDirectory()
        self.addCleanup(worktree_scratch.cleanup)
        worktree = Path(worktree_scratch.name) / "worktree"
        subprocess.run(
            ["git", "worktree", "add", "--detach", str(worktree), "HEAD"],
            cwd=self.repo,
            check=True,
            capture_output=True,
        )
        (worktree / ".codex" / "hooks.json").write_text("invalid json")
        (worktree / ".agents" / "hooks" / "pre_commit_on_stop.py").write_text(
            "print('worktree')\n"
        )
        (self.codex_home / "config.toml").write_text(
            f'[hooks.state."{self.repo}/.codex/hooks.json:user_prompt_submit:0:0"]\n'
            "enabled = false\n"
        )

        code, result = self.diagnose(worktree)

        self.assertEqual(code, 1)
        self.assertEqual(result["static_status"], "ok")
        self.assertEqual(
            result["config_source"], str(self.repo / ".codex" / "hooks.json")
        )
        self.assertEqual(
            result["hook_targets"],
            [str(worktree / ".agents" / "hooks" / "pre_commit_on_stop.py")],
        )
        self.assertEqual(result["runtime_status"], "disabled")
        self.assertIn("user_prompt_submit_disabled", result["reasons"])

    def test_saved_trust_hash_does_not_prove_runtime_execution(self) -> None:
        (self.repo / ".pre-commit-config.yaml").write_text("repos: []\n")
        script = self.repo / "pre_commit_on_stop.py"
        script.write_text("print('ok')\n")
        self.configure(self.repo, script)
        (self.codex_home / "config.toml").write_text(
            f'[hooks.state."{self.repo}/.codex/hooks.json:user_prompt_submit:0:0"]\n'
            'enabled = true\ntrusted_hash = "sha256:example"\n'
            f'[hooks.state."{self.repo}/.codex/hooks.json:stop:0:0"]\n'
            'enabled = true\ntrusted_hash = "sha256:example"\n'
        )

        code, result = self.diagnose(self.repo)

        self.assertEqual(code, 1)
        self.assertEqual(result["runtime_status"], "unverified")
        self.assertIn("runtime_activation_unverified", result["reasons"])

    def test_malformed_user_config_keeps_json_diagnostic(self) -> None:
        (self.repo / ".pre-commit-config.yaml").write_text("repos: []\n")
        script = self.repo / "pre_commit_on_stop.py"
        script.write_text("print('ok')\n")
        self.configure(self.repo, script)
        (self.codex_home / "config.toml").write_text("hooks = []\n")

        code, result = self.diagnose(self.repo)

        self.assertEqual(code, 1)
        self.assertEqual(result["runtime_status"], "unverified")

    def test_other_shell_expansion_stays_unresolved(self) -> None:
        (self.repo / ".pre-commit-config.yaml").write_text("repos: []\n")
        script = self.repo / "pre_commit_on_stop.py"
        script.write_text("print('ok')\n")
        self.configure(self.repo, script, 'python3 "$HOME/pre_commit_on_stop.py"')

        code, result = self.diagnose(self.repo)

        self.assertEqual(code, 2)
        self.assertIn("hook_command_unresolved", result["reasons"])

    def test_ignored_project_reports_degraded(self) -> None:
        (self.repo / ".pre-commit-config.yaml").write_text("repos: []\n")
        (self.repo / ".gitignore").write_text("project/\n")
        project = self.repo / "project"
        script = project / ".agents" / "hooks" / "pre_commit_on_stop.py"
        script.parent.mkdir(parents=True)
        script.write_text("print('ok')\n")
        self.configure(project, script)

        code, result = self.diagnose(project)

        self.assertEqual(code, 1)
        self.assertEqual(result["status"], "degraded")
        self.assertIn("project_ignored_by_git", result["reasons"])

    def test_missing_hook_file_reports_failed(self) -> None:
        (self.repo / ".pre-commit-config.yaml").write_text("repos: []\n")
        self.configure(self.repo, self.repo / "missing_hook.py")

        code, result = self.diagnose(self.repo)

        self.assertEqual(code, 2)
        self.assertEqual(result["status"], "failed")
        self.assertIn("hook_file_missing", result["reasons"])

    def test_nonexecutable_pre_commit_reports_degraded(self) -> None:
        (self.repo / ".pre-commit-config.yaml").write_text("repos: []\n")
        (self.repo / ".venv" / "bin" / "pre-commit").chmod(0o644)
        script = self.repo / "pre_commit_on_stop.py"
        script.write_text("print('ok')\n")
        self.configure(self.repo, script)

        code, result = self.diagnose(self.repo)

        self.assertEqual(code, 1)
        self.assertEqual(result["status"], "degraded")
        self.assertIn("pre_commit_unavailable", result["reasons"])

    def test_malformed_hook_config_reports_failed_json(self) -> None:
        (self.repo / ".pre-commit-config.yaml").write_text("repos: []\n")
        hooks = self.repo / ".codex"
        hooks.mkdir()
        (hooks / "hooks.json").write_text('{"hooks": []}')

        code, result = self.diagnose(self.repo)

        self.assertEqual(code, 2)
        self.assertEqual(result["status"], "failed")
        self.assertIn("hooks_config_unreadable", result["reasons"])


if __name__ == "__main__":
    unittest.main()
