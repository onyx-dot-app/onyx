"""Require a chart version increase and updated release descriptions."""

from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path

import semver
import yaml

CHART: Path = Path("deployment/helm/charts/onyx/Chart.yaml")
CHART_DIRS: tuple[str, ...] = (
    "deployment/helm/charts/onyx",
    "deployment/helm/charts/onyx-cnpg-crds",
)


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], text=True).strip()


def chart_changed(base: str) -> bool:
    ancestor: str = git("merge-base", base, "HEAD")
    # Include deleted files and untracked files used by agent stop hooks.
    return bool(
        git("diff", "--name-only", ancestor, "--", *CHART_DIRS)
        or git("ls-files", "--others", "--exclude-standard", "--", *CHART_DIRS)
    )


def read_chart(source: str) -> dict[str, object]:
    data: object = yaml.safe_load(source)
    if not isinstance(data, dict):
        raise ValueError("Chart.yaml must contain a mapping")
    result: dict[str, object] = {}
    for key, value in data.items():
        if not isinstance(key, str):
            raise ValueError("Chart.yaml keys must be strings")
        result[key] = value
    return result


def version(chart: dict[str, object]) -> semver.Version:
    value: object = chart.get("version")
    if not isinstance(value, str):
        raise ValueError("Chart.yaml version must be a SemVer string")
    return semver.Version.parse(value)


def descriptions(chart: dict[str, object]) -> list[str]:
    annotations: object = chart.get("annotations", {})
    if not isinstance(annotations, dict):
        raise ValueError("Chart.yaml annotations must contain a mapping")
    changes: object = annotations.get("artifacthub.io/changes", "")
    if not isinstance(changes, str):
        raise ValueError("artifacthub.io/changes must contain a YAML string")
    entries: object = yaml.safe_load(changes)
    if not isinstance(entries, list) or not entries:
        raise ValueError("artifacthub.io/changes must contain release descriptions")
    result: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("Each release entry must contain a description")
        description: object = entry.get("description")
        if not isinstance(description, str) or not description.strip():
            raise ValueError("Each release entry must contain a nonempty description")
        result.append(" ".join(description.split()))
    return sorted(result)


def main() -> int:
    parser: argparse.ArgumentParser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="origin/main")
    args: argparse.Namespace = parser.parse_args()
    try:
        branch: str = os.environ.get("GITHUB_BASE_REF") or git(
            "branch", "--show-current"
        )
        if branch.startswith("release/"):
            return 0
        if not chart_changed(args.base):
            return 0
        current: dict[str, object] = read_chart(CHART.read_text())
        previous: dict[str, object] = read_chart(git("show", f"{args.base}:{CHART}"))
        failures: list[str] = []
        if version(current) <= version(previous):
            failures.append(
                f"Bump version above {previous['version']} from {args.base}."
            )
        if descriptions(current) == descriptions(previous):
            failures.append(
                "Update the release descriptions in artifacthub.io/changes."
            )
        if failures:
            print(f"{CHART}: Helm chart files changed:")
            print("\n".join(f"  {failure}" for failure in failures))
            return 1
    except (subprocess.CalledProcessError, OSError, ValueError, yaml.YAMLError) as exc:
        print(f"Helm release check failed: {exc}")
        print("Ensure origin/main is available: git fetch origin main")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
