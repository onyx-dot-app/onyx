"""Check the image resolver's report and gate boundary, and the sandbox browser pin update."""

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("base-image-ref.sh")


def resolve_image(
    component: str, browser_status: int
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
        return subprocess.run(
            ["bash", str(scripts / SCRIPT.name), component],
            cwd=root,
            env={**os.environ, "PATH": f"{root}{os.pathsep}{os.environ['PATH']}"},
            capture_output=True,
            text=True,
            check=False,
        )


INSTALLER = (
    SCRIPT.parents[2]
    / "backend/onyx/server/features/build/sandbox/image/install-browser.sh"
)
ARCHIVES = {"linux64": b"amd64 archive", "linux-arm64": b"arm64 archive"}


def update_browser(installer: Path, stable: str) -> subprocess.CompletedProcess[str]:
    """Run the pin update against a fake Chrome for Testing."""
    root = installer.parent
    stable_response = json.dumps({"channels": {"Stable": {"version": stable}}})
    cases = "".join(
        f"*/{stable}/{platform}/chrome-{platform}.zip) printf '{body.decode()}'; exit 0;;\n"
        for platform, body in ARCHIVES.items()
    )
    curl = root / "curl"
    curl.write_text(
        '#!/bin/sh\nfor arg in "$@"; do case "$arg" in\n'
        f"*/last-known-good-versions.json) echo '{stable_response}'; exit 0;;\n"
        f"{cases}"
        "esac; done\nexit 22\n"
    )
    curl.chmod(0o755)
    return subprocess.run(
        ["bash", str(SCRIPT.with_name("update-sandbox-browser.sh")), str(installer)],
        env={**os.environ, "PATH": f"{root}{os.pathsep}{os.environ['PATH']}"},
        capture_output=True,
        text=True,
        check=False,
    )


class BrowserUpdateTests(unittest.TestCase):
    def test_a_stale_pin_moves_to_stable_with_both_archive_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            installer = Path(directory) / INSTALLER.name
            shutil.copyfile(INSTALLER, installer)
            before = installer.read_text().splitlines()

            result = update_browser(installer, "999.0.1.2")

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), "999.0.1.2")
            after = installer.read_text().splitlines()
            changed = [
                new for old, new in zip(before, after, strict=True) if old != new
            ]
            self.assertEqual(
                changed,
                [
                    "version=999.0.1.2",
                    f"    checksum={hashlib.sha256(ARCHIVES['linux64']).hexdigest()}",
                    f"    checksum={hashlib.sha256(ARCHIVES['linux-arm64']).hexdigest()}",
                ],
            )

            # A current pin is a no-op: nothing changes and nothing prints.
            result = update_browser(installer, "999.0.1.2")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, "")
            self.assertEqual(installer.read_text().splitlines(), after)

    def test_an_installer_missing_a_pin_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            installer = Path(directory) / INSTALLER.name
            arm64_pin = [
                line
                for line in INSTALLER.read_text().splitlines()
                if "checksum=" in line
            ][1]
            installer.write_text(INSTALLER.read_text().replace(arm64_pin + "\n", ""))

            result = update_browser(installer, "999.0.1.2")

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Could not pin", result.stderr)


class ImageResolverTests(unittest.TestCase):
    def test_browser_failure_is_reported_without_blocking_other_images(self) -> None:
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
                for name, body in {
                    "docker": '[ "$1" = build ] || exit 99',
                    "ods-audit": f'echo \'{{"version":"2.1.0","runs":[]}}\'; case "$*" in *onyx-sandbox*) echo "sandbox audit ran" >&2; exit {browser_status};; esac',
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
                        "GITHUB_OUTPUT": str(root / "outputs"),
                        "DHI_NODE_BUILD_ARGS": "NODE_RUNTIME_IMAGE=web:fixture",
                        "DHI_PYTHON_BUILD_ARGS": "PYTHON_RUNTIME_IMAGE=model:fixture",
                    },
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                expected = "success" if browser_status == 0 else "failure"
                self.assertIn(
                    f"sandbox-status={expected}", (root / "outputs").read_text()
                )
                self.assertIn("sandbox audit ran", result.stderr)
                for component in ("web", "model-server", "backend", "sandbox"):
                    report = root / f"image-audit-{component}.sarif"
                    self.assertEqual(json.loads(report.read_text())["version"], "2.1.0")

    def test_cached_sandbox_publication_requires_a_successful_audit(self) -> None:
        workflow = (SCRIPT.parent.parent / "workflows/deployment.yml").read_text()
        prepare = workflow.split("  prepare-sandbox:\n", 1)[1].split(
            "  build-sandbox-amd64:\n", 1
        )[0]
        first_step = prepare.split("    steps:\n", 1)[1].split("      - ")[1]
        self.assertIn("Require a passing sandbox audit", first_step)
        self.assertIn(
            "SANDBOX_STATUS: ${{ needs.audit-gate.outputs.sandbox-status }}", first_step
        )
        commands = first_step.split("        run: |\n", 1)[1]
        commands = "\n".join(line[10:] for line in commands.splitlines())
        for cached in ("true", "false"):
            for status in ("success", "failure", ""):
                with self.subTest(cached=cached, status=status):
                    result = subprocess.run(
                        ["bash", "-e", "-c", commands],
                        env={
                            **os.environ,
                            "SANDBOX_STATUS": status,
                            "CONTEXT_EXISTS": cached,
                        },
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    self.assertEqual(
                        result.returncode == 0, status == "success", result.stdout
                    )
        merge = workflow.split("  merge-sandbox:\n", 1)[1]
        condition = next(
            line for line in merge.splitlines() if line.startswith("    if:")
        )
        self.assertIn("needs.prepare-sandbox.result == 'success' &&", condition)
        self.assertIn(
            "needs.prepare-sandbox.outputs.context-exists == 'true'", condition
        )

    def test_resolver_only_resolves_the_image(self) -> None:
        result = resolve_image("sandbox", 1)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "onyx-sandbox-os:audit")
        self.assertNotIn("browser audit ran", result.stderr)

    def test_unknown_component_keeps_its_distinct_exit_status(self) -> None:
        result = resolve_image("unknown", 0)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertNotIn("browser audit ran", result.stderr)


if __name__ == "__main__":
    unittest.main()
