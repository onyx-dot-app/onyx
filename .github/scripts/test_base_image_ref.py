"""Check the boundary between CVE report collection and release gates."""

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
