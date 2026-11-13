"""Pure parts of the Firecracker VM developer commands (no cluster)."""

import argparse
import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "craft_fc_vm", Path(__file__).parents[1] / "craft_fc_vm.py"
)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Cannot load craft_fc_vm.py")
vm = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(vm)

PROFILE: dict[str, Any] = {
    "kube": {"context": "dev-ctx", "allowed_contexts": ["dev-ctx", "dev-alias"]},
    "namespaces": {"app": "app-ns", "agent": "agent-ns"},
    "user": {"email": "Profile@Example.com"},
}


def write_tree(root: Path, files: dict[str, bytes]) -> None:
    for name, data in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


class BundleTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def tree(self, name: str, files: dict[str, bytes]) -> Path:
        src = self.root / name
        src.mkdir()
        write_tree(src, files)
        return src

    def test_same_tree_gives_same_bytes(self) -> None:
        files = {"b/run.py": b"print(1)\n", "a.md": b"# skill\n", "b/c/d.txt": b"x"}
        first = self.tree("one", files)
        second = self.tree("two", dict(reversed(list(files.items()))))
        os.utime(second / "a.md", (1_000_000, 1_000_000))
        self.assertEqual(vm.build_bundle(first).sha256, vm.build_bundle(second).sha256)

    def test_content_change_changes_hash(self) -> None:
        a = self.tree("a", {"x.md": b"one"})
        b = self.tree("b", {"x.md": b"two"})
        self.assertNotEqual(vm.build_bundle(a).sha256, vm.build_bundle(b).sha256)

    def test_layout_modes_and_skips(self) -> None:
        src = self.tree(
            "s",
            {
                "skill/SKILL.md": b"doc",
                "skill/run.sh": b"#!/bin/sh\necho hi\n",
                ".DS_Store": b"junk",
                ".git/HEAD": b"ref",
                "skill/__pycache__/x.pyc": b"pyc",
            },
        )
        (src / "skill/run.sh").chmod(0o755)
        (src / "empty").mkdir()
        bundle = vm.build_bundle(src)
        self.assertEqual(bundle.files, 2)
        with zipfile.ZipFile(io.BytesIO(bundle.data)) as zf:
            infos = {i.filename: i for i in zf.infolist()}
        self.assertEqual(
            sorted(infos), ["empty/", "skill/", "skill/SKILL.md", "skill/run.sh"]
        )
        self.assertEqual(infos["skill/run.sh"].external_attr >> 16 & 0o777, 0o755)
        self.assertEqual(infos["skill/SKILL.md"].external_attr >> 16 & 0o777, 0o644)
        self.assertEqual(infos["skill/SKILL.md"].date_time, vm.ZIP_EPOCH)
        self.assertEqual(len(bundle.warnings), 1)
        self.assertIn("noexec", bundle.warnings[0])
        self.assertIn("`sh /mnt/skills/skill/run.sh`", bundle.warnings[0])

    def test_run_hint_uses_shebang(self) -> None:
        self.assertEqual(
            vm.run_hint("a/x.py", b"#!/usr/bin/env python3\n", "/mnt/spaces"),
            "python3 /mnt/spaces/a/x.py",
        )
        self.assertEqual(
            vm.run_hint("x", b"#!/bin/bash\n", "/mnt/skills"), "bash /mnt/skills/x"
        )

    def test_refuses_symlink(self) -> None:
        src = self.tree("s", {"a.md": b"a"})
        (src / "link").symlink_to(src / "a.md")
        with self.assertRaisesRegex(vm.CommandError, "symlinks"):
            vm.build_bundle(src)

    def test_refuses_fifo(self) -> None:
        src = self.tree("s", {"a.md": b"a"})
        os.mkfifo(src / "pipe")
        with self.assertRaisesRegex(vm.CommandError, "only files and directories"):
            vm.build_bundle(src)

    def test_refuses_empty_and_missing(self) -> None:
        (self.root / "empty").mkdir()
        with self.assertRaisesRegex(vm.CommandError, "no files"):
            vm.build_bundle(self.root / "empty")
        with self.assertRaisesRegex(vm.CommandError, "not a directory"):
            vm.build_bundle(self.root / "missing")

    def test_limits(self) -> None:
        src = self.tree("s", {"a": b"12345", "b": b"12345"})
        with patch.object(vm, "MAX_CONTENT_BYTES", 8):
            with self.assertRaisesRegex(vm.CommandError, "content is over"):
                vm.build_bundle(src)
        with patch.object(vm, "MAX_ENTRIES", 1):
            with self.assertRaisesRegex(vm.CommandError, "entries"):
                vm.build_bundle(src)


class TargetTest(unittest.TestCase):
    def test_profile_values(self) -> None:
        t = vm.target_from(PROFILE, context=None, user=None, tenant_id=None, env={})
        self.assertEqual(t.context, "dev-ctx")
        self.assertEqual(t.user, "profile@example.com")
        self.assertEqual(t.namespace, "app-ns")
        self.assertEqual(t.agent_namespace, "agent-ns")
        self.assertEqual(
            t.kubectl()[:5], ["kubectl", "--context", "dev-ctx", "-n", "app-ns"]
        )

    def test_flag_beats_env_beats_profile(self) -> None:
        env = {vm.USER_ENV: "env@example.com"}
        t = vm.target_from(PROFILE, context=None, user=None, tenant_id=None, env=env)
        self.assertEqual(t.user, "env@example.com")
        t = vm.target_from(
            PROFILE, context="dev-alias", user="me@example.com", tenant_id="t1", env=env
        )
        self.assertEqual(
            (t.user, t.context, t.tenant_id), ("me@example.com", "dev-alias", "t1")
        )

    def test_refuses_context_outside_profile(self) -> None:
        with self.assertRaisesRegex(vm.CommandError, "not in the profile"):
            vm.target_from(PROFILE, context="prod", user=None, tenant_id=None, env={})

    def test_needs_context_and_user(self) -> None:
        with self.assertRaisesRegex(vm.CommandError, "no kube context"):
            vm.target_from(None, context=None, user="a@b.c", tenant_id=None, env={})
        with self.assertRaisesRegex(vm.CommandError, "no user"):
            vm.target_from(None, context="ctx", user=None, tenant_id=None, env={})

    def test_refuses_placeholder(self) -> None:
        profile = {"kube": {"context": "<cluster arn>"}}
        with self.assertRaisesRegex(vm.CommandError, "placeholder"):
            vm.target_from(profile, context=None, user="a@b.c", tenant_id=None, env={})

    def test_helper_argv_pins_context(self) -> None:
        t = vm.Target(context="ctx", user="a@b.c", kubeconfig="/k")
        argv = vm.helper_argv(t)
        self.assertEqual(
            argv[:7],
            ["kubectl", "--kubeconfig", "/k", "--context", "ctx", "-n", "onyx"],
        )
        self.assertIn("deploy/onyx-api-server", argv)
        self.assertEqual(argv[-2:], ["-c", vm.BOOT])


class HelperProtocolTest(unittest.TestCase):
    def test_boot_reads_script_request_and_payload(self) -> None:
        script = (
            b"import json,sys\n"
            b"b=sys.stdin.buffer\n"
            b"req=json.loads(b.readline())\n"
            b"data=b.read(req['payload_bytes'])\n"
            b"print('@@craft-fc '+json.dumps({'t':'echo','req':req,'n':len(data),"
            b"'tail':data[-3:].decode()}))\n"
        )
        payload = b"\x00\n" * 5000 + b"end"
        stdin = vm.helper_input({"command_name": "x"}, payload, script)
        out = subprocess.run(
            [sys.executable, "-c", vm.BOOT],
            input=stdin,
            capture_output=True,
            check=True,
        ).stdout.decode()
        result = vm.parse_result(out.strip())
        assert result is not None
        self.assertEqual(result["n"], len(payload))
        self.assertEqual(result["tail"], "end")
        self.assertEqual(result["req"]["command_name"], "x")

    def test_helper_file_compiles(self) -> None:
        compile(vm.HELPER.read_bytes(), str(vm.HELPER), "exec")

    def test_parse_and_single(self) -> None:
        self.assertIsNone(vm.parse_result("INFO some log"))
        ok = vm.single([{"t": "out"}, {"t": "vms", "vms": []}])
        self.assertEqual(ok["t"], "vms")
        with self.assertRaisesRegex(vm.CommandError, "NO_VM: none"):
            vm.single([{"t": "error", "code": "NO_VM", "message": "none"}])


class CommandTest(unittest.TestCase):
    target = vm.Target(context="ctx", user="me@example.com")

    def run_main(
        self, argv: list[str], results: list[dict[str, Any]]
    ) -> tuple[int, list[dict[str, Any]], str, str]:
        sent: list[dict[str, Any]] = []

        def fake(
            _t: object,
            request: dict[str, Any],
            payload: bytes = b"",
            verbose: bool = False,
        ) -> Iterator[dict[str, Any]]:
            sent.append(dict(request, payload_len=len(payload), verbose=verbose))
            yield from results

        out, err = io.StringIO(), io.StringIO()
        with (
            patch.object(vm, "run_helper", fake),
            patch.object(vm, "load_profile", lambda _p: None),
            contextlib.redirect_stdout(out),
            contextlib.redirect_stderr(err),
        ):
            code = vm.main(["--context", "ctx", "--user", "me@example.com", *argv])
        return code, sent, out.getvalue(), err.getvalue()

    def test_exec_quotes_args_and_returns_exit_code(self) -> None:
        code, sent, out, err = self.run_main(
            ["exec", "--wake", "--", "sh", "-c", "echo a b"],
            [
                {"t": "out", "s": "stdout", "d": "a b\n"},
                {"t": "out", "s": "stderr", "d": "warn\n"},
                {"t": "result", "completion": "EXITED", "exit_code": 3},
            ],
        )
        self.assertEqual(code, 3)
        self.assertEqual(sent[0]["command"], "sh -c 'echo a b'")
        self.assertTrue(sent[0]["wake"])
        self.assertEqual(sent[0]["user"], "me@example.com")
        self.assertEqual(out, "a b\n")
        self.assertEqual(err, "warn\n")

    def test_exec_single_arg_is_a_shell_line(self) -> None:
        _, sent, _, _ = self.run_main(
            ["exec", "--", "ls /mnt/skills | wc -l"],
            [{"t": "result", "completion": "EXITED", "exit_code": 0}],
        )
        self.assertEqual(sent[0]["command"], "ls /mnt/skills | wc -l")

    def test_exec_without_command(self) -> None:
        code, _, _, err = self.run_main(["exec"], [])
        self.assertEqual(code, 2)
        self.assertIn("give a command", err)

    def test_no_vm_error_suggests_wake(self) -> None:
        code, _, _, err = self.run_main(
            ["exec", "--", "true"],
            [
                {
                    "t": "error",
                    "code": "NO_VM",
                    "message": "no running VM; run again with --wake",
                }
            ],
        )
        self.assertEqual(code, 2)
        self.assertIn("--wake", err)

    def test_skills_push_sends_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            write_tree(Path(tmp), {"s/SKILL.md": b"doc"})
            code, sent, out, _ = self.run_main(
                ["skills", "push", tmp, "--mount", "spaces"],
                [
                    {
                        "t": "pushed",
                        "image_id": "ab" * 32,
                        "built": False,
                        "build_ms": 0,
                        "path": "/mnt/spaces",
                        "sandbox_id": "sb",
                        "active": "B",
                        "changed": False,
                        "swap_ms": 4,
                        "listing": "s\n",
                    }
                ],
            )
            bundle = vm.build_bundle(Path(tmp))
        self.assertEqual(code, 0)
        self.assertEqual(sent[0]["command_name"], "skills-push")
        self.assertEqual(sent[0]["mount"], "spaces")
        self.assertEqual(sent[0]["payload_len"], len(bundle.data))
        self.assertIn("cached", out)
        self.assertIn("unchanged", out)
        self.assertIn("ls -la /mnt/spaces", out)

    def test_reset_outcomes(self) -> None:
        code, sent, _, _ = self.run_main(
            ["reset", "--force"],
            [{"t": "reset", "sandbox_id": "sb", "outcome": "stopped"}],
        )
        self.assertEqual((code, sent[0]["force"]), (0, True))
        code, _, _, err = self.run_main(
            ["reset"],
            [{"t": "reset", "sandbox_id": "sb", "outcome": "kept_no_checkpoint"}],
        )
        self.assertEqual(code, 1)
        self.assertIn("--force", err)

    def test_vms_table(self) -> None:
        code, _, out, _ = self.run_main(
            ["vms"],
            [
                {
                    "t": "vms",
                    "vms": [
                        {
                            "user": "me@example.com",
                            "sandbox_id": "sb",
                            "placed": True,
                            "node": "n1",
                            "attempt": 2,
                            "generation": 5,
                            "state": "RUNNING",
                            "age_s": 7300,
                            "idle_s": 30,
                            "busy_marks": True,
                        }
                    ],
                }
            ],
        )
        self.assertEqual(code, 0)
        row = out.splitlines()[1].split()
        self.assertEqual(
            row,
            ["me@example.com", "sb", "n1", "2", "5", "RUNNING", "busy", "2h", "30s"],
        )


class LogLineTest(unittest.TestCase):
    sid = "11111111-2222-3333-4444-555555555555"

    def test_guest_lines(self) -> None:
        line = json.dumps(
            {
                "kind": "guest_log",
                "stream": "console",
                "sandbox_id": self.sid,
                "line": "boot ok",
            }
        )
        self.assertEqual(
            vm.log_line(line, self.sid, guest=True, agent=True), "[console] boot ok"
        )
        self.assertIsNone(vm.log_line(line, self.sid, guest=False, agent=True))

    def test_other_sandbox_is_hidden(self) -> None:
        other = json.dumps({"kind": "guest_log", "sandbox_id": "x", "line": "hi"})
        self.assertIsNone(vm.log_line(other, self.sid, guest=True, agent=True))

    def test_agent_lines(self) -> None:
        line = json.dumps(
            {"time": "t", "level": "INFO", "msg": "vm started", "sandbox": self.sid}
        )
        shown = vm.log_line(line, self.sid, guest=True, agent=True)
        self.assertEqual(shown, f"t INFO vm started sandbox={self.sid}")
        self.assertIsNone(vm.log_line(line, self.sid, guest=True, agent=False))
        self.assertEqual(
            vm.log_line(f"plain {self.sid}", self.sid, guest=False, agent=True),
            f"plain {self.sid}",
        )

    def test_tail_counts_only_this_vm(self) -> None:
        mine = [json.dumps({"msg": f"m{i}", "sandbox_id": self.sid}) for i in range(3)]
        other = [json.dumps({"msg": "o", "sandbox_id": "x"})] * 5
        lines = [mine[0], *other, mine[1], *other, mine[2], *other]
        shown = list(vm.matching_lines(lines, self.sid, guest=True, agent=True, tail=2))
        self.assertEqual([s.split()[0] for s in shown], ["m1", "m2"])
        self.assertEqual(
            len(
                list(
                    vm.matching_lines(
                        lines, self.sid, guest=True, agent=True, tail=None
                    )
                )
            ),
            3,
        )


class ParserTest(unittest.TestCase):
    def test_mount_choices(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            vm.parser().parse_args(["skills", "push", "d", "--mount", "other"])
        args: argparse.Namespace = vm.parser().parse_args(
            ["logs", "--guest", "--tail", "5"]
        )
        self.assertTrue(args.guest)
        self.assertEqual(args.tail, 5)


if __name__ == "__main__":
    unittest.main()
