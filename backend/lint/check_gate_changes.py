"""Check PR changes to lint gates without executing code from the PR."""

import ast
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
from typing import Protocol
from urllib.parse import quote

from scripts import check_migration_determinism

from . import (
    check_celery_task_expires,
    check_db_ops_outside_db,
    check_migration_design,
    check_no_direct_redis,
    check_no_http_exception,
    check_no_response_model,
    check_test_flakes,
)

COUNT_BASELINES = {
    "backend/lint/db_ops_outside_db_baseline.txt": False,
    "backend/lint/no_http_exception_baseline.txt": False,
    "backend/lint/no_direct_redis_baseline.txt": True,
    "backend/lint/no_response_model_baseline.txt": True,
    "backend/lint/test_skip_baseline.txt": True,
    "backend/lint/test_sleep_baseline.txt": True,
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
    "cubic.yaml",
    "web/.type-coverage-baseline.yaml",
    "mobile/eslint.config.js",
    "tools/ods/cmd/check_getattr.go",
    "tools/ods/cmd/check_lazy_imports.go",
    "tools/ods/cmd/type_coverage.go",
    "tools/ods/cmd/coverage_gate.go",
    "backend/scripts/check_migration_determinism.py",
    "backend/scripts/env_inventory.py",
}
PROTECTED_DIRECTORIES = (
    ".greptile/",
    "backend/lint/",
    "tools/ods/internal/pycheck/",
    "tools/ods/internal/lazyimports/",
    "tools/ods/internal/typecoverage/",
    "tools/ods/internal/coverage/",
    "web/tools/oxlint/",
    "web/tools/type-check/",
)
IMPORT_BOUNDARIES = "backend/lint/import_boundaries.toml"
NOQA = re.compile(
    r"#\s*(?:(?:ruff|flake8)\s*:\s*)?noqa\b(?:\s*:\s*([A-Z]+\d+(?:[ ,]+[A-Z]+\d+)*))?",
    re.IGNORECASE,
)
RUFF_DIRECTIVE = re.compile(
    r"#\s*ruff\s*:\s*(ignore|disable|enable)\s*\[([^]\n]+)\]",
)

PYTHON_DIRECTIVE = re.compile(
    r"(?P<ods>ods:\s*ignore\[(?P<ods_rules>[^]\n]*)\])"
    r"|(?P<types>#\s*(?P<checker>type|ty)\s*:\s*ignore\b"
    r"(?:\[(?P<type_rules>[^]\n]*)\])?)"
)
JS_DIRECTIVE = re.compile(
    r"@ts-(?:ignore|expect-error|nocheck)\b"
    r"|(?:oxlint|eslint)-disable(?:-next-line|-line)?\b"
    r"|(?:oxlint|eslint)-enable\b"
)
JS_RANGE = re.compile(r"(?:oxlint|eslint)-(disable|enable)(?![-\w])([^\r\n]*)")
JS_SUFFIXES = (".ts", ".tsx", ".js", ".jsx", ".mts", ".cts", ".mjs", ".cjs")


class PythonExceptionCheck(Protocol):
    def __call__(self, source: str, *, accepted: set[int]) -> object: ...


PYTHON_EXCEPTION_CHECKS: dict[str, PythonExceptionCheck] = {
    check_celery_task_expires.ALLOW_MARKER: check_celery_task_expires.find_missing_expires,
    check_db_ops_outside_db.ALLOW_MARKER: check_db_ops_outside_db.find_db_operations,
    check_no_http_exception.ALLOW_MARKER: check_no_http_exception.find_violations,
    check_no_response_model.ALLOW_MARKER: check_no_response_model.find_response_models,
    check_no_direct_redis.ALLOW_MARKER: check_no_direct_redis.find_direct_redis_uses,
    check_migration_determinism.ALLOW_MARKER: check_migration_determinism.find_run_dependent_values,
}
MARKERS = (
    *PYTHON_EXCEPTION_CHECKS,
    check_migration_design.ALLOW_MARKER,
    check_test_flakes.ALLOW_MARKER,
)


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
    old = tomllib.loads(before).get("tool", {}).get("ruff")
    new = tomllib.loads(after).get("tool", {}).get("ruff")
    if old is None and new is not None:
        return True
    old = old or {}
    new = new or {}
    for left, right in ((old, new), (old.get("lint", {}), new.get("lint", {}))):
        for key in ("per-file-ignores", "extend-per-file-ignores"):
            previous = left.pop(key, {})
            for pattern, rules in right.pop(key, {}).items():
                if pattern not in previous or set(rules) - set(previous[pattern]):
                    return True
    for config in (old, new):
        if config.get("lint") == {}:
            del config["lint"]
    return old != new


def type_checker_changed(before: str, after: str) -> bool:
    old = tomllib.loads(before).get("tool", {})
    new = tomllib.loads(after).get("tool", {})
    return old.get("ty") != new.get("ty")


def is_gate_definition(path: str) -> bool:
    name = Path(path).name
    return (
        path in PROTECTED
        or path.startswith(PROTECTED_DIRECTORIES)
        or name in {"ty.toml", ".oxlintrc.json", "oxlint.config.ts"}
        or (name.startswith("tsconfig") and name.endswith(".json"))
    )


def accepted_exceptions(source: str, path: str) -> dict[int, set[str]]:
    exceptions: dict[int, set[str]] = {}
    if is_playwright_source(path):
        if check_test_flakes.ALLOW_MARKER in source:
            accepted_flakes: set[tuple[int, check_test_flakes.Kind]] = set()
            for _ in check_test_flakes.playwright_findings(
                source, tsx=path.endswith(".tsx"), accepted=accepted_flakes
            ):
                pass
            for line, rule in accepted_flakes:
                exceptions.setdefault(line - 1, set()).add(f"gate:test-flakes:{rule}")
        return exceptions
    if path.endswith(JS_SUFFIXES):
        return exceptions

    for marker, check in PYTHON_EXCEPTION_CHECKS.items():
        if marker in source:
            accepted: set[int] = set()
            check(source, accepted=accepted)
            for line in accepted:
                exceptions.setdefault(line - 1, set()).add(f"gate:{marker}")
    if check_migration_design.ALLOW_MARKER in source:
        accepted_design: set[tuple[int, str]] = set()
        check_migration_design.find_violations(
            ast.parse(source), source, accepted=accepted_design
        )
        for line, rule in accepted_design:
            exceptions.setdefault(line - 1, set()).add(f"gate:migration-design:{rule}")
    if check_test_flakes.ALLOW_MARKER in source:
        accepted_python_flakes: set[tuple[int, check_test_flakes.Kind]] = set()
        for _ in check_test_flakes.python_findings(
            source, accepted=accepted_python_flakes
        ):
            pass
        for line, rule in accepted_python_flakes:
            exceptions.setdefault(line - 1, set()).add(f"gate:test-flakes:{rule}")
    return exceptions


def add_js_suppressions(
    source: str, path: str, line_count: int, suppressions: dict[int, set[str]]
) -> None:
    if JS_DIRECTIVE.search(source) or (
        is_playwright_source(path) and check_test_flakes.ALLOW_MARKER in source
    ):
        ranges: dict[int, tuple[str, set[str]]] = {}
        for line, comment in check_test_flakes.typescript_comments(
            source, tsx=path.endswith((".tsx", ".jsx"))
        ):
            marker = is_playwright_source(path) and check_test_flakes.playwright_marker(
                comment
            )
            directive = JS_DIRECTIVE.search(comment)
            if marker or (directive and not directive[0].endswith("-enable")):
                suppressions.setdefault(line - 1, set()).add(f"gate:{comment}")
            if match := JS_RANGE.search(comment):
                action, selectors = match.groups()
                selectors = selectors.split("--", 1)[0].removesuffix("*/")
                rules = {rule.strip() for rule in selectors.split(",") if rule.strip()}
                ranges[line - 1] = action, rules
        active: set[str] = set()
        enabled: set[str] = set()
        for index in range(line_count) if ranges else ():
            if change := ranges.get(index):
                action, rules = change
                if action == "disable":
                    active.update(rules or {"*"})
                    if rules:
                        enabled.difference_update(rules)
                    else:
                        enabled.clear()
                elif rules:
                    active.difference_update(rules)
                    enabled.update(rules)
                else:
                    active.clear()
                    enabled.clear()
            if active:
                suppressions.setdefault(index, set()).update(
                    f"gate:jslint:{rule}" for rule in active
                )
                if "*" in active:
                    suppressions[index].update(
                        f"enable:jslint:{rule}" for rule in enabled
                    )


def suppression_data(source: str, path: str) -> tuple[list[str], dict[int, set[str]]]:
    lines = source.splitlines()
    suppressions = accepted_exceptions(source, path)
    if path.endswith(JS_SUFFIXES):
        add_js_suppressions(source, path, len(lines), suppressions)
        return lines, suppressions
    range_directives: dict[int, tuple[bool, set[str]]] = {}
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type != tokenize.COMMENT:
            continue
        index = token.start[0] - 1
        for directive in PYTHON_DIRECTIVE.finditer(token.string):
            selectors = directive["ods_rules"] or directive["type_rules"]
            checker = directive["checker"] or "ods"
            rules = (
                {rule.strip() for rule in selectors.split(",")}
                if selectors
                else {"all"}
            )
            suppressions.setdefault(index, set()).update(
                f"gate:{checker}:{rule}" for rule in rules
            )
        if directive := RUFF_DIRECTIVE.search(token.string):
            kind, selectors = directive.groups()
            rules = {rule.strip() for rule in selectors.split(",")}
            if kind == "ignore":
                suppressions.setdefault(index, set()).update(rules)
            else:
                range_directives[index] = (kind == "disable", rules)
                if kind == "disable":
                    suppressions.setdefault(index, set()).update(rules)
            start = token.start[1] + directive.start(2)
            stop = token.start[1] + directive.end(2)
            lines[index] = lines[index][:start] + lines[index][stop:]
        elif match := NOQA.search(token.string):
            rules = set(re.findall(r"[A-Z]+[0-9]+", (match[1] or "").upper()))
            suppressions.setdefault(index, set()).update(rules or {"all"})
            # Align a selector edit with the original directive on the same code.
            start = token.start[1] + match.start()
            stop = token.start[1] + match.end()
            directive = match[0].split(match[1], 1)[0] if match[1] else match[0]
            lines[index] = (
                lines[index][:start] + directive.rstrip(": ") + lines[index][stop:]
            )
    if range_directives:
        active: set[str] = set()
        for index in range(len(lines)):
            if change := range_directives.get(index):
                disables, rules = change
                if disables:
                    active.update(rules)
                else:
                    active.difference_update(rules)
            if active:
                suppressions.setdefault(index, set()).update(active)
    return lines, suppressions


def adds_suppression(before: str, after: str, path: str) -> bool:
    if not any(marker in after for marker in MARKERS) and not (
        NOQA.search(after)
        or RUFF_DIRECTIVE.search(after)
        or PYTHON_DIRECTIVE.search(after)
        or JS_DIRECTIVE.search(after)
    ):
        return False
    old_lines, old = suppression_data(before, path)
    new_lines, new = suppression_data(after, path)
    diff = difflib.SequenceMatcher(None, old_lines, new_lines, autojunk=False)
    for tag, old_start, _, start, stop in diff.get_opcodes():
        for index in range(start, stop):
            rules = new.get(index, set())
            if not rules:
                continue
            previous = (
                old.get(old_start + index - start, set()) if tag == "equal" else set()
            )
            if "gate:jslint:*" in rules and any(
                rule.startswith("enable:") for rule in previous - rules
            ):
                return True
            added = {
                rule for rule in rules - previous if not rule.startswith("enable:")
            }
            if added and (
                "all" not in previous or any(rule.startswith("gate:") for rule in added)
            ):
                return True
    return False


def changes_import_boundaries(before: str, after: str) -> bool:
    old, new = tomllib.loads(before), tomllib.loads(after)
    old_contracts, new_contracts = old.get("contract", []), new.get("contract", [])
    if len(old_contracts) != len(new_contracts):
        return True
    for old_contract, new_contract in zip(old_contracts, new_contracts, strict=True):
        old_exceptions = old_contract.pop("exception", [])
        for exception in new_contract.pop("exception", []):
            if exception not in old_exceptions:
                return True
            old_exceptions.remove(exception)
    return old != new


def is_playwright_source(path: str) -> bool:
    return path.startswith("web/tests/") and path.endswith((".ts", ".tsx"))


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
    elif path == IMPORT_BOUNDARIES:
        if changes_import_boundaries(before, after):
            return "import boundary policy changed"
    elif path == "web/package.json":
        old = json.loads(before or "{}").get("scripts", {})
        new = json.loads(after or "{}").get("scripts", {})
        if any(old.get(name) != new.get(name) for name in ("types:check", "oxlint")):
            return "web lint or type check command changed"
    elif is_gate_definition(path):
        return "gate definition changed"
    elif (name := Path(path).name) in {".ruff.toml", "ruff.toml", "pyproject.toml"}:
        if name == "pyproject.toml" and type_checker_changed(before, after):
            return "ty configuration changed"
        if name != "pyproject.toml" or ruff_additions(before, after):
            return "Ruff configuration changed"
    elif path.endswith((".py", ".pyi", ".pyw", *JS_SUFFIXES)) and adds_suppression(
        before, after, path
    ):
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
        protected = is_gate_definition(path)
        if (
            protected
            and path not in COUNT_BASELINES
            and path not in SET_BASELINES
            and path != IMPORT_BOUNDARIES
        ):
            failures.append((path, "gate definition changed"))
            continue
        if not (
            protected
            or path in SET_BASELINES
            or path == "web/package.json"
            or is_playwright_source(path)
            or path.endswith(
                (".py", ".pyi", ".pyw", "pyproject.toml", "ruff.toml", *JS_SUFFIXES)
            )
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
