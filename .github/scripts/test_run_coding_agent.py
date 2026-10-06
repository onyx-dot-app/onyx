#!/usr/bin/env python3
from __future__ import annotations

import os
import stat
import subprocess
import tempfile
import unittest
from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import replace
from pathlib import Path
from unittest import mock

import run_coding_agent
from run_coding_agent import AgentConfigError, RunAgentConfig


class _FakeProcess:
    def __init__(self, exit_code: int = 0, timeout_once: bool = False) -> None:
        self.exit_code = exit_code
        self.timeout_once = timeout_once
        self.wait_calls = 0
        self.pid = 321

    def wait(self, timeout: int | None = None) -> int:
        self.wait_calls += 1
        if self.timeout_once and self.wait_calls == 1:
            raise subprocess.TimeoutExpired(cmd=["npx"], timeout=timeout or 0)
        return self.exit_code


class RunCodingAgentTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.prompt_file = self.root / "prompt.md"
        self.prompt_file.write_text("Fix ${TARGET}; keep ${OTHER}.", encoding="utf-8")
        self.env = {
            "ANTHROPIC_API_KEY": "test-key",
            "PATH": os.environ.get("PATH", ""),
            "TARGET": "the issue",
        }

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _base_config(self) -> RunAgentConfig:
        return RunAgentConfig(
            harness="claude-code",
            prompt_file=self.prompt_file,
            working_directory=self.repo,
        )

    def _patch_popen(
        self,
        exit_code: int = 0,
        on_launch: Callable[[Sequence[str], Path, Mapping[str, str]], None]
        | None = None,
        timeout_once: bool = False,
    ) -> AbstractContextManager[mock.Mock]:
        def fake_popen(
            command: Sequence[str],
            *,
            cwd: str | Path,
            env: Mapping[str, str],
            start_new_session: bool,
        ) -> _FakeProcess:
            self.assertTrue(start_new_session)
            if on_launch is not None:
                on_launch(command, Path(cwd), env)
            return _FakeProcess(exit_code=exit_code, timeout_once=timeout_once)

        return mock.patch.object(
            run_coding_agent.subprocess, "Popen", side_effect=fake_popen
        )

    def test_builds_pinned_restricted_claude_code_command(self) -> None:
        add_dir = self.root / "inputs"
        add_dir.mkdir()

        with self._patch_popen() as popen_mock:
            exit_code = run_coding_agent.run_agent(
                replace(
                    self._base_config(), add_dirs=(add_dir,), prompt_vars=("TARGET",)
                ),
                env=self.env,
            )

        self.assertEqual(exit_code, 0)
        command = popen_mock.call_args.args[0]
        self.assertEqual(
            command[:4], ["npx", "--yes", "@anthropic-ai/claude-code@2.1.285", "-p"]
        )
        self.assertIn("Fix the issue; keep ${OTHER}.", command)
        self.assertIn("--restricted", command)
        self.assertIn("--bare", command)
        self.assertIn("--strict-mcp-config", command)
        self.assertEqual(
            command[command.index("--settings") + 1], '{"disableAllHooks":true}'
        )
        self.assertEqual(
            command[command.index("--tools") + 1], "Read,Glob,Grep,Edit,Write"
        )
        self.assertEqual(command[command.index("--permission-mode") + 1], "acceptEdits")
        self.assertEqual(command[command.index("--model") + 1], "claude-opus-5-5")
        self.assertEqual(command[command.index("--max-turns") + 1], "60")
        self.assertEqual(
            command[command.index("--add-dir") + 1], str(add_dir.resolve())
        )

        popen_kwargs = popen_mock.call_args.kwargs
        self.assertEqual(Path(str(popen_kwargs["cwd"])), self.repo.resolve())
        subprocess_env = popen_kwargs["env"]
        self.assertEqual(subprocess_env["ANTHROPIC_API_KEY"], "test-key")
        self.assertNotIn("TARGET", subprocess_env)

    def test_missing_prompt_var_rejects_before_launch(self) -> None:
        with self._patch_popen() as popen_mock:
            with self.assertRaisesRegex(
                AgentConfigError, "Missing required prompt variable"
            ):
                run_coding_agent.run_agent(
                    replace(self._base_config(), prompt_vars=("TARGET", "MISSING")),
                    env=self.env,
                )
        popen_mock.assert_not_called()

    def test_cli_style_whitespace_prompt_vars_are_split(self) -> None:
        self.env["OTHER"] = "literal"
        with self._patch_popen() as popen_mock:
            exit_code = run_coding_agent.run_agent(
                replace(self._base_config(), prompt_vars=("TARGET OTHER",)),
                env=self.env,
            )

        self.assertEqual(exit_code, 0)
        command = popen_mock.call_args.args[0]
        self.assertIn("Fix the issue; keep literal.", command)

    def test_missing_auth_and_wrong_harness_reject_before_launch(self) -> None:
        with self._patch_popen() as popen_mock:
            with self.assertRaisesRegex(AgentConfigError, "ANTHROPIC_API_KEY"):
                run_coding_agent.run_agent(
                    self._base_config(), env={"PATH": self.env["PATH"]}
                )
            with self.assertRaisesRegex(AgentConfigError, "Unsupported harness"):
                run_coding_agent.run_agent(
                    replace(self._base_config(), harness="codex"), env=self.env
                )
        popen_mock.assert_not_called()

    def test_nonzero_exit_propagates_timeout_is_124_and_os_failure_is_126(self) -> None:
        with self._patch_popen(exit_code=7):
            self.assertEqual(
                run_coding_agent.run_agent(self._base_config(), env=self.env), 7
            )

        with (
            self._patch_popen(timeout_once=True),
            mock.patch.object(run_coding_agent.os, "killpg") as killpg_mock,
        ):
            self.assertEqual(
                run_coding_agent.run_agent(self._base_config(), env=self.env), 124
            )
            killpg_mock.assert_any_call(321, run_coding_agent.signal.SIGTERM)
            killpg_mock.assert_any_call(321, run_coding_agent.signal.SIGKILL)

        with mock.patch.object(
            run_coding_agent.subprocess, "Popen", side_effect=OSError("missing npx")
        ):
            self.assertEqual(
                run_coding_agent.run_agent(self._base_config(), env=self.env), 126
            )

    def test_allowed_files_transfer_changes_and_deletions_from_isolated_copy(
        self,
    ) -> None:
        package_dir = self.repo / "pkg"
        package_dir.mkdir()
        edited_file = package_dir / "edited.txt"
        edited_file.write_text("before", encoding="utf-8")
        edited_file.chmod(0o644)
        deleted_file = package_dir / "deleted.txt"
        deleted_file.write_text("delete me", encoding="utf-8")
        ignored_cache = package_dir / "node_modules" / "cache.txt"
        ignored_cache.parent.mkdir()
        ignored_cache.write_text("cache", encoding="utf-8")
        (self.repo / ".git").mkdir()
        (self.repo / "node_modules").mkdir()
        (self.repo / ".venv").mkdir()
        (self.repo / ".ci-actions").mkdir()
        (self.repo / ".agent-actions").mkdir()

        def mutate_copy(
            command: Sequence[str], cwd: Path, _env: Mapping[str, str]
        ) -> None:
            self.assertFalse((cwd / ".git").exists())
            self.assertFalse((cwd / "node_modules").exists())
            self.assertFalse((cwd / ".venv").exists())
            self.assertFalse((cwd / ".ci-actions").exists())
            self.assertFalse((cwd / ".agent-actions").exists())
            prompt = command[command.index("-p") + 1]
            self.assertIn("Only these repo-relative output paths", prompt)
            self.assertIn("pkg", prompt)
            (cwd / "pkg" / "edited.txt").write_text("after", encoding="utf-8")
            (cwd / "pkg" / "edited.txt").chmod(0o600)
            (cwd / "pkg" / "deleted.txt").unlink()
            (cwd / "pkg" / "new.txt").write_text("new", encoding="utf-8")

        with self._patch_popen(on_launch=mutate_copy):
            exit_code = run_coding_agent.run_agent(
                replace(self._base_config(), allowed_files=("pkg deleted-later",)),
                env=self.env,
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(edited_file.read_text(encoding="utf-8"), "after")
        self.assertEqual(stat.S_IMODE(edited_file.stat().st_mode), 0o644)
        self.assertFalse(deleted_file.exists())
        self.assertEqual((package_dir / "new.txt").read_text(encoding="utf-8"), "new")
        self.assertEqual(ignored_cache.read_text(encoding="utf-8"), "cache")

    def test_rejects_allowed_path_traversal_and_overlapping_add_dir(self) -> None:
        (self.repo / "pkg").mkdir()
        with self._patch_popen() as popen_mock:
            with self.assertRaisesRegex(AgentConfigError, "repo root"):
                run_coding_agent.run_agent(
                    replace(self._base_config(), allowed_files=(".",)),
                    env=self.env,
                )
            with self.assertRaisesRegex(AgentConfigError, "ignored copy roots"):
                run_coding_agent.run_agent(
                    replace(self._base_config(), allowed_files=("node_modules/pkg",)),
                    env=self.env,
                )
            with self.assertRaisesRegex(AgentConfigError, "traverse"):
                run_coding_agent.run_agent(
                    replace(self._base_config(), allowed_files=("../outside",)),
                    env=self.env,
                )
            with self.assertRaisesRegex(AgentConfigError, "overlap"):
                run_coding_agent.run_agent(
                    replace(
                        self._base_config(),
                        allowed_files=("pkg",),
                        add_dirs=(self.repo / "pkg",),
                    ),
                    env=self.env,
                )
        popen_mock.assert_not_called()

    def test_rejects_symlink_and_executable_edits_without_partial_transfer(
        self,
    ) -> None:
        package_dir = self.repo / "pkg"
        package_dir.mkdir()
        trusted_file = package_dir / "trusted.txt"
        trusted_file.write_text("trusted", encoding="utf-8")

        def add_symlink(
            _command: Sequence[str], cwd: Path, _env: Mapping[str, str]
        ) -> None:
            (cwd / "pkg" / "trusted.txt").write_text("changed", encoding="utf-8")
            (cwd / "pkg" / "link").symlink_to("trusted.txt")

        with self._patch_popen(on_launch=add_symlink):
            with self.assertRaisesRegex(AgentConfigError, "Symlink"):
                run_coding_agent.run_agent(
                    replace(self._base_config(), allowed_files=("pkg",)),
                    env=self.env,
                )
        self.assertEqual(trusted_file.read_text(encoding="utf-8"), "trusted")

        def make_executable(
            _command: Sequence[str], cwd: Path, _env: Mapping[str, str]
        ) -> None:
            path = cwd / "pkg" / "trusted.txt"
            path.write_text("changed", encoding="utf-8")
            path.chmod(0o755)

        with self._patch_popen(on_launch=make_executable):
            with self.assertRaisesRegex(AgentConfigError, "executable"):
                run_coding_agent.run_agent(
                    replace(self._base_config(), allowed_files=("pkg",)),
                    env=self.env,
                )
        self.assertEqual(trusted_file.read_text(encoding="utf-8"), "trusted")

    def test_rejects_nested_symlink_ancestor_and_dangling_symlink_source(self) -> None:
        package_dir = self.repo / "pkg"
        package_dir.mkdir()
        trusted_file = package_dir / "trusted.txt"
        trusted_file.write_text("trusted", encoding="utf-8")

        def replace_parent_with_symlink(
            _command: Sequence[str], cwd: Path, _env: Mapping[str, str]
        ) -> None:
            (cwd / "pkg" / "trusted.txt").unlink()
            (cwd / "pkg").rmdir()
            (cwd / "elsewhere").mkdir()
            (cwd / "pkg").symlink_to("elsewhere")

        with self._patch_popen(on_launch=replace_parent_with_symlink):
            with self.assertRaisesRegex(AgentConfigError, "Symlink"):
                run_coding_agent.run_agent(
                    replace(self._base_config(), allowed_files=("pkg/trusted.txt",)),
                    env=self.env,
                )
        self.assertEqual(trusted_file.read_text(encoding="utf-8"), "trusted")

        def make_dangling_symlink(
            _command: Sequence[str], cwd: Path, _env: Mapping[str, str]
        ) -> None:
            (cwd / "pkg" / "trusted.txt").unlink()
            (cwd / "pkg" / "trusted.txt").symlink_to("missing-target")

        with self._patch_popen(on_launch=make_dangling_symlink):
            with self.assertRaisesRegex(AgentConfigError, "Symlink"):
                run_coding_agent.run_agent(
                    replace(self._base_config(), allowed_files=("pkg/trusted.txt",)),
                    env=self.env,
                )
        self.assertEqual(trusted_file.read_text(encoding="utf-8"), "trusted")

    def test_no_transfer_after_failed_agent(self) -> None:
        package_dir = self.repo / "pkg"
        package_dir.mkdir()
        trusted_file = package_dir / "trusted.txt"
        trusted_file.write_text("trusted", encoding="utf-8")

        def mutate_copy(
            _command: Sequence[str], cwd: Path, _env: Mapping[str, str]
        ) -> None:
            (cwd / "pkg" / "trusted.txt").write_text("changed", encoding="utf-8")

        with self._patch_popen(exit_code=1, on_launch=mutate_copy):
            exit_code = run_coding_agent.run_agent(
                replace(self._base_config(), allowed_files=("pkg",)),
                env=self.env,
            )

        self.assertEqual(exit_code, 1)
        self.assertEqual(trusted_file.read_text(encoding="utf-8"), "trusted")

    def test_rationale_and_failure_context_contract(self) -> None:
        failure_context_file = self.root / "failure.txt"
        failure_context_file.write_text("failed logs", encoding="utf-8")
        rationale_file = self.root / "rationale.md"

        def write_rationale(
            command: Sequence[str], _cwd: Path, _env: Mapping[str, str]
        ) -> None:
            prompt = command[command.index("-p") + 1]
            self.assertIn("Trusted CI launcher instructions", prompt)
            self.assertIn("failure_context.txt", prompt)
            self.assertIn("rationale.md", prompt)
            add_dirs = [
                Path(command[index + 1])
                for index, item in enumerate(command)
                if item == "--add-dir"
            ]
            io_dirs = [
                path for path in add_dirs if (path / "failure_context.txt").exists()
            ]
            self.assertEqual(len(io_dirs), 1)
            self.assertEqual(
                (io_dirs[0] / "failure_context.txt").read_text(encoding="utf-8"),
                "failed logs",
            )
            (io_dirs[0] / "rationale.md").write_text("Looks good.\n", encoding="utf-8")

        with self._patch_popen(on_launch=write_rationale):
            exit_code = run_coding_agent.run_agent(
                replace(
                    self._base_config(),
                    rationale_file=rationale_file,
                    failure_context_file=failure_context_file,
                ),
                env=self.env,
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(rationale_file.read_text(encoding="utf-8"), "Looks good.\n")

        with self._patch_popen():
            with self.assertRaisesRegex(AgentConfigError, "rationale"):
                run_coding_agent.run_agent(
                    replace(
                        self._base_config(),
                        rationale_file=self.root / "missing-rationale.md",
                    ),
                    env=self.env,
                )


if __name__ == "__main__":
    unittest.main()
