from __future__ import annotations

import importlib.util
import json
import os
import socket
import subprocess
import sys
import tempfile
import unittest
import warnings
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType
from typing import Iterator
from unittest.mock import patch

SCRIPT_PATH = Path(__file__).with_name("dev_stack.py")


def load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("onyx_dev_stack_test", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


dev_stack = load_module()


class DevStackTest(unittest.TestCase):
    def make_repo(self, root: Path) -> None:
        (root / ".vscode").mkdir(parents=True)
        (root / ".venv" / "bin").mkdir(parents=True)
        (root / ".venv" / "bin" / "python").symlink_to(Path(sys.executable))
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)

    def test_jsonc_parser_preserves_comment_tokens_inside_strings(self) -> None:
        parsed = json.loads(
            dev_stack.strip_jsonc(
                """
                {
                  // comment
                  "url": "http://localhost:3000/path//part",
                  "items": [1, 2,], /* comment */
                }
                """
            )
        )
        self.assertEqual(parsed["url"], "http://localhost:3000/path//part")
        self.assertEqual(parsed["items"], [1, 2])

    def test_env_parser_handles_quotes_hashes_and_comments(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / ".env"
            path.write_text(
                "PLAIN=value\n"
                'QUOTED="value with spaces"\n'
                "HASH=abc#123\n"
                "COMMENTED=value # comment\n"
            )
            self.assertEqual(
                dev_stack.load_env_file(path),
                {
                    "PLAIN": "value",
                    "QUOTED": "value with spaces",
                    "HASH": "abc#123",
                    "COMMENTED": "value",
                },
            )

    def test_project_name_distinguishes_equal_basenames(self) -> None:
        first = Path.cwd() / "one" / "worktree"
        second = Path.cwd() / "two" / "worktree"
        self.assertNotEqual(
            dev_stack.project_name(first), dev_stack.project_name(second)
        )
        self.assertTrue(dev_stack.project_name(first).startswith("worktree-"))

    def test_selected_ports_connect_web_api_and_model(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.make_repo(root)
            stack_dir = dev_stack.state_dir(root)
            stack_dir.mkdir(parents=True)
            (stack_dir / "ports.json").write_text(
                json.dumps({"web": 3002, "api": 8082, "model": 9002, "mcp": 8092})
            )
            config = {
                "name": "API Server",
                "type": "debugpy",
                "request": "launch",
                "module": "onyx.main:app",
                "args": ["--port", "8080"],
            }
            spec = dev_stack.process_spec(config, root)
            self.assertEqual(spec.command[-2:], ["--port", "8082"])
            self.assertEqual(spec.env["INTERNAL_URL"], "http://localhost:8082")
            self.assertEqual(spec.env["MODEL_SERVER_PORT"], "9002")
            self.assertEqual(spec.env["WEB_DOMAIN"], "http://localhost:3002")

    def test_prepare_env_localizes_symlink_without_changing_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "worktree"
            self.make_repo(root)
            shared = base / "shared.env"
            shared.write_text("AUTH_TYPE=basic\nGEN_AI_API_KEY=secret\n")
            (root / ".vscode" / ".env").symlink_to(shared)
            (root / ".vscode" / "env_template.txt").write_text("AUTH_TYPE=basic\n")
            (root / ".vscode" / "env.web_template.txt").write_text("AUTH_TYPE=basic\n")

            dev_stack.prepare_env(root)

            local_env = root / ".vscode" / ".env"
            self.assertFalse(local_env.is_symlink())
            self.assertEqual(local_env.read_text(), shared.read_text())
            self.assertEqual(
                shared.read_text(), "AUTH_TYPE=basic\nGEN_AI_API_KEY=secret\n"
            )

    def test_host_lock_rejects_a_second_process(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.make_repo(root)
            (root / ".vscode" / "launch.json").write_text("{}\n")
            with dev_stack.operation_lock(root, "outer-test"):
                result = subprocess.run(
                    [sys.executable, str(SCRIPT_PATH), "prepare-env"],
                    cwd=root,
                    capture_output=True,
                    text=True,
                    check=False,
                )
            self.assertEqual(result.returncode, 1)
            self.assertIn("owns the dev stack lock", result.stderr)

    def test_port_reservation_blocks_a_second_listener(self) -> None:
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        with dev_stack.reserve_port(port):
            with socket.socket() as competing:
                with self.assertRaises(OSError):
                    competing.bind(("127.0.0.1", port))

    def test_infrastructure_reserves_app_ports(self) -> None:
        reserved: list[int] = []
        commands: list[list[str]] = []

        @contextmanager
        def fake_reservation(port: int) -> Iterator[None]:
            reserved.append(port)
            yield

        def record_command(command: list[str], **_: object) -> None:
            commands.append(command)

        with (
            patch.object(
                dev_stack,
                "project_service_uses_host_port",
                return_value=False,
            ),
            patch.object(dev_stack, "reserve_port", fake_reservation),
            patch.object(dev_stack, "port_is_open", return_value=False),
            patch.object(dev_stack, "run_checked", record_command),
        ):
            dev_stack.start_infrastructure(Path.cwd())

        self.assertEqual(reserved, [8000])
        self.assertEqual(len(commands), 1)
        self.assertEqual(commands[0][-3:], ["compose", "dev", "--infra"])

    def test_infrastructure_collision_recreates_only_infra(self) -> None:
        commands: list[list[str]] = []

        @contextmanager
        def fake_reservation(_: int) -> Iterator[None]:
            yield

        def record_command(command: list[str], **_: object) -> None:
            commands.append(command)

        with (
            patch.object(
                dev_stack,
                "project_service_uses_host_port",
                return_value=True,
            ),
            patch.object(dev_stack, "reserve_port", fake_reservation),
            patch.object(dev_stack, "run_checked", record_command),
        ):
            dev_stack.start_infrastructure(Path.cwd())

        self.assertEqual(len(commands), 2)
        self.assertEqual(commands[0][-4:], ["compose", "dev", "--infra", "--down"])
        self.assertEqual(commands[1][-3:], ["compose", "dev", "--infra"])

    @unittest.skipUnless(os.name == "posix", "process-group test requires POSIX")
    def test_stop_records_terminates_only_recorded_process_group(self) -> None:
        process = subprocess.Popen(
            ["/bin/sh", "-c", "sleep 30"],
            start_new_session=True,
        )
        record = {
            "pid": process.pid,
            "pgid": os.getpgid(process.pid),
            "start_marker": dev_stack.process_start_marker(process.pid),
        }
        dev_stack.stop_records([record], timeout=2)
        process.wait(timeout=2)
        self.assertIsNotNone(process.returncode)

    def test_background_start_and_stop_use_git_scoped_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.make_repo(root)
            (root / ".vscode" / ".env").write_text("AUTH_TYPE=basic\n")
            (root / ".vscode" / ".env.web").write_text("AUTH_TYPE=basic\n")
            (root / ".vscode" / "launch.json").write_text(
                json.dumps(
                    {
                        "compounds": [
                            {
                                "name": dev_stack.DEFAULT_COMPOUND,
                                "configurations": ["Sleep Service"],
                            }
                        ],
                        "configurations": [
                            {
                                "name": "Sleep Service",
                                "type": "node",
                                "request": "launch",
                                "runtimeExecutable": "/bin/sh",
                                "runtimeArgs": ["-c", "sleep 30"],
                                "cwd": "${workspaceFolder}",
                                "envFile": "${workspaceFolder}/.vscode/.env",
                            }
                        ],
                    }
                )
            )

            with (
                patch.object(dev_stack, "run_checked"),
                warnings.catch_warnings(),
            ):
                warnings.simplefilter("ignore", ResourceWarning)
                self.assertEqual(
                    dev_stack.start_processes(root, dev_stack.DEFAULT_COMPOUND), 0
                )

            state_path = dev_stack.state_dir(root) / "state.json"
            state = json.loads(state_path.read_text())
            pid = state["processes"][0]["pid"]
            self.assertTrue(dev_stack.pid_exists(pid))

            dev_stack.stop_processes(root, timeout=2)
            self.assertFalse(state_path.exists())
            self.assertTrue((dev_stack.state_dir(root) / "last-state.json").is_file())


if __name__ == "__main__":
    unittest.main()
