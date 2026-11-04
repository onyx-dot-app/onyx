"""Check the boundary between CVE report collection and release gates."""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("base-image-ref.sh")


def resolve_image(
    component: str, browser_status: int, gate: bool
) -> subprocess.CompletedProcess[str]:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        scripts = root / ".github/scripts"
        scripts.mkdir(parents=True)
        shutil.copyfile(SCRIPT, scripts / SCRIPT.name)
        (scripts / "audit-sandbox-browser.sh").write_text(
            f'echo "browser audit ran" >&2\nexit {browser_status}\n'
        )
        docker = root / "docker"
        docker.write_text('#!/bin/sh\n[ "$1" = build ] || exit 99\n')
        docker.chmod(0o755)
        arguments = ["bash", str(scripts / SCRIPT.name), component]
        if not gate:
            arguments.append("--report")
        return subprocess.run(
            arguments,
            cwd=root,
            env={**os.environ, "PATH": f"{root}{os.pathsep}{os.environ['PATH']}"},
            capture_output=True,
            text=True,
            check=False,
        )


class ImageResolverTests(unittest.TestCase):
    def test_release_collects_os_reports_before_failing_the_browser_gate(self) -> None:
        workflow = SCRIPT.parent.parent / "workflows/deployment.yml"
        lines = workflow.read_text().splitlines()
        step = lines.index("      - name: Run base image audit")
        start = lines.index("        run: |", step) + 1
        commands: list[str] = []
        for line in lines[start:]:
            if line and not line.startswith("          "):
                break
            commands.append(line[10:])

        for browser_status in (0, 1, 2):
            with (
                self.subTest(browser_status=browser_status),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                scripts = root / ".github/scripts"
                scripts.mkdir(parents=True)
                resolver = scripts / SCRIPT.name
                shutil.copyfile(SCRIPT, resolver)
                resolver.chmod(0o755)
                (scripts / "audit-sandbox-browser.sh").write_text(
                    f'echo "browser audit ran" >&2\nexit {browser_status}\n'
                )
                for name, body in {
                    "docker": '[ "$1" = build ] || exit 99',
                    "uv": 'echo \'{"version":"2.1.0","runs":[]}\'',
                }.items():
                    executable = root / name
                    executable.write_text(f"#!/bin/sh\n{body}\n")
                    executable.chmod(0o755)
                result = subprocess.run(
                    ["bash", "-e", "-o", "pipefail", "-c", "\n".join(commands)],
                    cwd=root,
                    env={
                        **os.environ,
                        "PATH": f"{root}{os.pathsep}{os.environ['PATH']}",
                        "DHI_NODE_BUILD_ARGS": "NODE_RUNTIME_IMAGE=web:fixture",
                        "DHI_PYTHON_BUILD_ARGS": "PYTHON_RUNTIME_IMAGE=model:fixture",
                    },
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(
                    result.returncode, int(browser_status != 0), result.stderr
                )
                self.assertIn("browser audit ran", result.stderr)
                for component in ("web", "model-server", "backend", "sandbox"):
                    report = root / f"image-audit-{component}.sarif"
                    self.assertEqual(json.loads(report.read_text())["version"], "2.1.0")

    def test_report_collection_does_not_run_the_browser_gate(self) -> None:
        for status in (1, 2, 3):
            with self.subTest(browser_status=status):
                result = resolve_image("sandbox", status, gate=False)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.strip(), "onyx-sandbox-os:audit")
                self.assertNotIn("browser audit ran", result.stderr)

    def test_browser_failures_cannot_be_mistaken_for_unknown_components(self) -> None:
        for status in (1, 2, 3):
            with self.subTest(browser_status=status):
                result = resolve_image("sandbox", status, gate=True)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertEqual(result.stdout, "")
                self.assertIn("browser audit ran", result.stderr)

    def test_clean_browser_gate_returns_the_image(self) -> None:
        result = resolve_image("sandbox", 0, gate=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "onyx-sandbox-os:audit")
        self.assertIn("browser audit ran", result.stderr)

    def test_unknown_component_keeps_its_distinct_exit_status(self) -> None:
        result = resolve_image("unknown", 0, gate=True)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertNotIn("browser audit ran", result.stderr)


if __name__ == "__main__":
    unittest.main()
