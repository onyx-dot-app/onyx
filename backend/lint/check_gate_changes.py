"""Check PR changes to lint gates without executing code from the PR."""

import difflib
import io
import json
import os
import re
import subprocess
import tokenize
import tomllib
from http.client import HTTPSConnection
from pathlib import Path
from urllib.parse import quote

COUNT_BASELINES = {
    "backend/lint/db_ops_outside_db_baseline.txt": False,
    "backend/lint/no_http_exception_baseline.txt": False,
    "backend/lint/no_direct_redis_baseline.txt": True,
    "backend/lint/no_response_model_baseline.txt": True,
}
SET_BASELINES = {
    "backend/lint/celery_task_allowlist.txt",
    "backend/scripts/env_inventory_baseline.txt",
}
PROTECTED = {
    ".github/CODEOWNERS",
    ".github/workflows/pr-gate-changes.yml",
    ".github/workflows/pr-quality-checks.yml",
    ".pre-commit-config.yaml",
    "backend/scripts/check_migration_determinism.py",
    "backend/scripts/env_inventory.py",
}
MARKERS = (
    "celery-expires: allow",
    "db-ops-outside-db: allow",
    "http-exception: allow",
    "migration-determinism: allow",
    "no-response-model: allow",
)
NOQA = re.compile(r"#\s*(?:(?:ruff|flake8)\s*:\s*)?noqa\b", re.IGNORECASE)
REDIS_MARKER = "no-direct-redis: allow"


def rows(source: str) -> list[str]:
    return [
        line
        for raw in source.splitlines()
        if (line := raw.strip()) and not line.startswith("#")
    ]


def counts(source: str, count_first: bool) -> dict[str, int]:
    result: dict[str, int] = {}
    for line in rows(source):
        if count_first:
            count, path = line.split(maxsplit=1)
        else:
            path, count = line.rsplit(maxsplit=1)
        value = int(count)
        if path in result or value < 0:
            raise ValueError("Invalid baseline row")
        result[path] = value
    return result


def ruff_additions(before: str, after: str) -> bool:
    old = tomllib.loads(before).get("tool", {}).get("ruff", {})
    new = tomllib.loads(after).get("tool", {}).get("ruff", {})
    for section in (old, new, old.get("lint", {}), new.get("lint", {})):
        for key in ("per-file-ignores", "extend-per-file-ignores"):
            section.setdefault(key, {})
    for left, right in ((old, new), (old.get("lint", {}), new.get("lint", {}))):
        for key in ("per-file-ignores", "extend-per-file-ignores"):
            previous = left.pop(key, {})
            for pattern, rules in right.pop(key, {}).items():
                if pattern not in previous or set(rules) - set(previous[pattern]):
                    return True
    return old != new


def suppression_lines(source: str) -> set[int]:
    lines = {
        index for index, line in enumerate(source.splitlines()) if REDIS_MARKER in line
    }
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type == tokenize.COMMENT and (
            NOQA.search(token.string)
            or any(marker in token.string for marker in MARKERS)
        ):
            lines.add(token.start[0] - 1)
    return lines


def check_change(path: str, before: str, after: str) -> str | None:
    if path in COUNT_BASELINES:
        old = counts(before, COUNT_BASELINES[path])
        new = counts(after, COUNT_BASELINES[path])
        if any(key not in old or value > old[key] for key, value in new.items()):
            return "baseline entry added or increased"
    elif path in SET_BASELINES:
        if path.endswith("celery_task_allowlist.txt"):
            # The identity includes the task or beat prefix and its name.
            old_keys = {line.split(": ", 1)[0] for line in rows(before)}
            new_keys = {line.split(": ", 1)[0] for line in rows(after)}
        else:
            old_keys, new_keys = set(rows(before)), set(rows(after))
        if new_keys - old_keys:
            return "allowlist or baseline entry added"
    elif path in PROTECTED or path.startswith("backend/lint/"):
        return "gate definition changed"
    elif (name := Path(path).name) in {".ruff.toml", "ruff.toml", "pyproject.toml"}:
        if name != "pyproject.toml" or ruff_additions(before, after):
            return "Ruff configuration changed"
    elif path.endswith((".py", ".pyi", ".pyw")):
        if not any(
            marker in after for marker in (*MARKERS, REDIS_MARKER)
        ) and not NOQA.search(after):
            return None
        suppressions = suppression_lines(after)
        diff = difflib.SequenceMatcher(None, before.splitlines(), after.splitlines())
        for tag, _, _, start, stop in diff.get_opcodes():
            if tag != "equal" and not suppressions.isdisjoint(range(start, stop)):
                return "suppression added or edited"
    return None


def git(*args: str) -> bytes:
    return subprocess.check_output(["git", *args])


def read_blob(revision: str, path: str, present: bool) -> str:
    if not present:
        return ""
    return git("cat-file", "blob", f"{revision}:{path}").decode("utf-8")


def violations(base: str, head: str) -> list[tuple[str, str]]:
    start = git("merge-base", base, head).decode().strip()
    changed = git("diff", "--no-renames", "--name-status", "-z", start, head)
    fields = changed.rstrip(b"\0").split(b"\0") if changed else []
    failures: list[tuple[str, str]] = []
    for status, raw_path in zip(fields[::2], fields[1::2], strict=True):
        path = os.fsdecode(raw_path)
        protected = path in PROTECTED or path.startswith("backend/lint/")
        if protected and path not in COUNT_BASELINES and path not in SET_BASELINES:
            failures.append((path, "gate definition changed"))
            continue
        if not (
            protected
            or path in SET_BASELINES
            or path.endswith((".py", ".pyi", ".pyw", "pyproject.toml", "ruff.toml"))
        ):
            continue
        try:
            reason = check_change(
                path,
                read_blob(start, path, status != b"A"),
                read_blob(head, path, status != b"D"),
            )
        except (ValueError, SyntaxError, tokenize.TokenError):
            reason = "could not parse the changed gate or source"
        if reason:
            failures.append((path, reason))
    return failures


def api(path: str, token: str, *, allow_missing: bool = False) -> bytes:
    connection = HTTPSConnection("api.github.com", timeout=30)
    try:
        connection.request(
            "GET",
            f"/{path}",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "User-Agent": "onyx-gate-changes",
            },
        )
        response = connection.getresponse()
        if allow_missing and response.status == 404:
            return b"{}"
        if response.status != 200:
            raise RuntimeError(f"GitHub API returned HTTP {response.status}")
        return response.read()
    finally:
        connection.close()


def owner_approved(number: int, head: str) -> bool:
    membership_token = os.environ.get("GATE_TEAM_TOKEN")
    if not membership_token:
        print("Set GATE_TEAM_TOKEN to enable code owner approvals.")
        return False
    route = f"repos/{os.environ['GITHUB_REPOSITORY']}/pulls/{number}"
    token = os.environ["GH_TOKEN"]
    pull = json.loads(api(route, token))
    if pull["head"]["sha"] != head or pull["state"] != "open":
        return False
    latest: dict[str, tuple[str, str]] = {}
    page = 1
    while reviews := json.loads(
        api(f"{route}/reviews?per_page=100&page={page}", token)
    ):
        for review in reviews:
            if review["user"] and review["state"] in {
                "APPROVED",
                "CHANGES_REQUESTED",
                "DISMISSED",
            }:
                latest[review["user"]["login"]] = (review["state"], review["commit_id"])
        page += 1
    for login, review in latest.items():
        if login == pull["user"]["login"] or review != ("APPROVED", head):
            continue
        membership = json.loads(
            api(
                f"orgs/onyx-dot-app/teams/onyx-core-team/memberships/{quote(login, safe='')}",
                membership_token,
                allow_missing=True,
            )
        )
        if membership.get("state") == "active":
            return True
    return False


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base")
    parser.add_argument("head")
    parser.add_argument("--pr", type=int)
    args = parser.parse_args()
    failures = violations(args.base, args.head)
    for path, reason in failures:
        print(f"{path!r} {reason}")
    if not failures or (args.pr and owner_approved(args.pr, args.head)):
        return 0
    print("Ask an Onyx core-team member to approve this PR head, then rerun this job.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
