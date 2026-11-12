"""Accept only a version increase and its two checksum replacements."""

import json
import os
import re
import subprocess
import sys

INSTALLER = "backend/onyx/server/features/build/sandbox/image/install-browser.sh"
PIN = re.compile(
    r"^(version=[0-9]+(?:\.[0-9]+){3}|    checksum=[0-9a-f]{64})$", re.MULTILINE
)


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], text=True).strip()


def verify(base: str, head: str) -> None:
    ancestor = git("merge-base", base, head)
    if git("diff", "--name-only", ancestor, head) != INSTALLER:
        raise ValueError("A browser update must change only install-browser.sh")
    before = git("show", f"{ancestor}:{INSTALLER}")
    after = git("show", f"{head}:{INSTALLER}")
    old_pins, new_pins = PIN.findall(before), PIN.findall(after)
    if (
        len(old_pins) != 3
        or len(new_pins) != 3
        or PIN.sub("PIN", before) != PIN.sub("PIN", after)
    ):
        raise ValueError("A browser update must change only the version and two hashes")
    old_version = tuple(map(int, old_pins[0].removeprefix("version=").split(".")))
    new_version = tuple(map(int, new_pins[0].removeprefix("version=").split(".")))
    if new_version <= old_version:
        raise ValueError("A browser update must increase the version")
    if any(old == new for old, new in zip(old_pins[1:], new_pins[1:], strict=True)):
        raise ValueError("A browser update must change both checksums")


def verify_validation_run(base: str, run_id: str) -> None:
    # Required quality checks must preserve the pin-only contract on future heads.
    quality = git("show", f"{base}:.github/workflows/pr-quality-checks.yml")
    if "name: Validate automatic browser pin updates" not in quality:
        raise ValueError("The target branch must enforce browser pin validation")
    pages = json.loads(
        subprocess.check_output(
            [
                "gh",
                "api",
                "--paginate",
                "--slurp",
                f"repos/{os.environ['REPO']}/actions/runs/{run_id}/jobs?per_page=100",
            ],
            text=True,
        )
    )
    jobs = [
        job
        for page in pages
        for job in page["jobs"]
        if job["name"]
        in {"Sandbox browser audit (amd64)", "Sandbox browser audit (arm64)"}
    ]
    if len(jobs) != 2 or any(
        job["conclusion"] != "success"
        or not any(
            step["name"] == "Verify browser rendering and screenshots"
            and step["conclusion"] == "success"
            for step in job["steps"]
        )
        for job in jobs
    ):
        raise ValueError("Both native browser rendering jobs must pass")


if __name__ == "__main__":
    verify(sys.argv[1], sys.argv[2])
    if run_id := os.environ.get("VALIDATION_RUN_ID"):
        verify_validation_run(sys.argv[1], run_id)
