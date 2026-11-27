"""Check that pull request workflows never let concurrency cancel their newest run.

A workflow that runs on pull_request and cancels in-progress runs must adopt
reusable-cancel-superseded-runs.yml, which explains why. Exit 1 lists each
workflow that does not.
"""

import sys
from pathlib import Path
from typing import Any

import yaml

WORKFLOWS = Path(".github/workflows")
REUSABLE = "./.github/workflows/reusable-cancel-superseded-runs.yml"
SAME_REPO_PR = (
    "github.event_name == 'pull_request' && "
    "github.event.pull_request.head.repo.full_name == github.repository"
)
GROUP_KEY = f"${{{{ ({SAME_REPO_PR} && github.run_id) || "

# Workflows that keep built-in cancellation, and why.
EXEMPT = {
    # Deploys a preview per commit. The group serializes deploys, and no
    # required check comes from it.
    "preview.yml",
    # Its artifact feeds docs-preview-publish.yml. No required check comes
    # from it.
    "docs-preview.yml",
}


def _triggers(workflow: dict[Any, Any]) -> set[str]:
    # PyYAML reads the `on` key as True.
    on = workflow.get(True, workflow.get("on")) or {}
    if isinstance(on, str):
        return {on}
    return set(on)


def _cancels(concurrency: Any) -> bool:
    return isinstance(concurrency, dict) and concurrency.get(
        "cancel-in-progress"
    ) not in (None, False)


def problems(name: str, workflow: dict[Any, Any]) -> list[str]:
    if "pull_request" not in _triggers(workflow) or name in EXEMPT:
        return []
    jobs = workflow.get("jobs") or {}
    found = [
        f"{name}: job {job_id} sets concurrency with cancel-in-progress"
        for job_id, job in jobs.items()
        if _cancels(job.get("concurrency"))
    ]
    concurrency = workflow.get("concurrency")
    if not _cancels(concurrency):
        return found
    if GROUP_KEY not in str(concurrency.get("group", "")):
        found.append(f"{name}: the concurrency group must include {GROUP_KEY}")
    callers = [job for job in jobs.values() if job.get("uses") == REUSABLE]
    if not any(
        job.get("if") == SAME_REPO_PR
        and (job.get("permissions") or {}).get("actions") == "write"
        for job in callers
    ):
        found.append(
            f"{name}: add a job that calls {REUSABLE} with "
            f"`if: {SAME_REPO_PR}` and `actions: write`"
        )
    return found


def main() -> int:
    found: list[str] = []
    for path in sorted(WORKFLOWS.glob("*.y*ml")):
        workflow = yaml.safe_load(path.read_text())
        if isinstance(workflow, dict):
            found.extend(problems(path.name, workflow))
    for problem in found:
        print(problem)
    if found:
        print(f"See {REUSABLE.removeprefix('./')}.")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
