"""Keep only the newest run of this workflow for a pull request branch.

Required status checks read only the newest check suite of each workflow on a
commit. Built-in concurrency cancels runs in the order they reach the group,
and two runs created in the same second (a stack push sends one event for the
head push and one for the base push) can reach it in either order. Then the
newest run is the one cancelled, and its cancelled checks block the merge.

So same-repo pull request runs use a concurrency group per run, and this
script, which runs in each of them, decides by check suite id instead:

- A run with a newer suite on the branch supersedes this run: cancel this run.
- Otherwise cancel the older runs on the branch that have not finished.

Each run decides from the same ordering, so the newest run always survives.
Errors only print a warning: an uncancelled older run wastes runner time, but
its checks do not count.
"""

import http.client
import json
import os
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

API = "https://api.github.com"


@dataclass(frozen=True)
class Run:
    id: int
    check_suite_id: int
    status: str
    event: str
    head_branch: str
    head_repo: str

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "Run":
        return cls(
            id=data["id"],
            check_suite_id=data["check_suite_id"],
            status=data["status"],
            event=data["event"],
            head_branch=data["head_branch"],
            head_repo=(data.get("head_repository") or {}).get("full_name", ""),
        )


@dataclass(frozen=True)
class Decision:
    superseded_by: int | None
    to_cancel: list[int]


def decide(own: Run, runs: list[Run]) -> Decision:
    siblings = [
        run
        for run in runs
        if run.id != own.id
        and run.event == "pull_request"
        and run.head_branch == own.head_branch
        and run.head_repo == own.head_repo
    ]
    newer = [run for run in siblings if run.check_suite_id > own.check_suite_id]
    if newer:
        newest = max(newer, key=lambda run: run.check_suite_id)
        return Decision(superseded_by=newest.id, to_cancel=[own.id])
    older = sorted(
        run.id
        for run in siblings
        if run.check_suite_id < own.check_suite_id and run.status != "completed"
    )
    return Decision(superseded_by=None, to_cancel=older)


def _request(method: str, path: str, token: str) -> Any:
    request = urllib.request.Request(  # noqa: S310 — fixed https endpoint
        f"{API}{path}",
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
        body = response.read()
    return json.loads(body) if body else None


def main() -> None:
    token = os.environ["GH_TOKEN"]
    repo = os.environ["REPO"]
    run_id = os.environ["RUN_ID"]
    try:
        own_data = _request("GET", f"/repos/{repo}/actions/runs/{run_id}", token)
        own = Run.from_api(own_data)
        # Unfinished runs are the most recent ones, so the first page is enough.
        listing = _request(
            "GET",
            f"/repos/{repo}/actions/workflows/{own_data['workflow_id']}/runs"
            f"?event=pull_request&branch={urllib.parse.quote(own.head_branch, safe='')}"
            "&per_page=100",
            token,
        )
    except (OSError, http.client.HTTPException, KeyError, ValueError) as error:
        print(f"::warning::Could not list runs, so none were cancelled: {error}")
        return

    decision = decide(own, [Run.from_api(run) for run in listing["workflow_runs"]])
    if decision.superseded_by is not None:
        print(
            f"Run {decision.superseded_by} is newer and is the run that counts. "
            "Cancelling this run."
        )
    elif not decision.to_cancel:
        print(f"No older unfinished runs for {own.head_branch}.")
    for cancel_id in decision.to_cancel:
        print(f"Cancelling run {cancel_id}")
        try:
            _request("POST", f"/repos/{repo}/actions/runs/{cancel_id}/cancel", token)
        except (OSError, http.client.HTTPException) as error:
            # 409 means the run finished after the listing.
            print(f"::warning::Could not cancel run {cancel_id}: {error}")


if __name__ == "__main__":
    main()
