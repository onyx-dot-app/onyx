#!/usr/bin/env python3
"""Reconciles the feature map with the commits merged to main since the last run.

Reads the commits since the commit in `RECONCILED` (or the last 7 days), finds the
components whose code changed without a document change, and runs one Claude Code
agent per component in parallel. One integrator agent then applies the cross-file
changes (PATHS.md rows). The integrity check and an em dash check gate the result,
and `RECONCILED` moves to HEAD only when the whole range was reviewed.

Usage: reconcile.py [--write --rationale-file PATH] [--failure-context-file PATH]
Without --write, prints the plan as JSON and calls no agent.
"""

import argparse
import json
import os
import shutil
import string
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from check_feature_map import MAP_DIR, REPO_ROOT, check
from stale_docs import stale_components, unowned_paths

MARKER = MAP_DIR / "RECONCILED"
CLAUDE_CODE_VERSION = "2.1.285"
PROMPTS = REPO_ROOT / ".github/prompts"
DIFF_LIMIT = 30_000
DEFAULT_WINDOW = "7 days ago"
MAX_REINTEGRATIONS = 2
COMPONENT_TIMEOUT = 1200
INTEGRATOR_TIMEOUT = 1800
REPORT_KEYS = {"changed", "summary", "for_integrator", "needs_human"}
INTEGRATE_KEYS = {"summary", "needs_human"}
EM_DASH = "\u2014"
MAP_PREFIX = ".agents/feature-map"
# Unowned paths outside these roots are tooling, CI, deployment, or the design
# system; they never need a PATHS.md row.
PRODUCT_ROOTS = (
    "backend/onyx/",
    "backend/ee/",
    "web/src/",
    "desktop/",
    "mobile/",
    "widget/",
    "extensions/",
    "cli/",
)
NON_PRODUCT = ("web/src/i18n/",)

Plan = dict[str, Any]
Owned = dict[str, dict[str, list[str]]]


@dataclass
class Paths:
    root: Path
    plan: Path
    unowned: Path
    check_errors: Path
    failure_context: Path
    work: Path
    reports: Path
    integrate_report: Path


@dataclass
class Outcome:
    repair: bool
    reports: dict[str, dict[str, Any]] = field(default_factory=dict)
    failed: list[str] = field(default_factory=list)
    integrator: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        errors="replace",
        check=True,
    )
    return result.stdout


def is_ancestor(sha: str) -> bool:
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", sha, "HEAD"],
        cwd=REPO_ROOT,
        capture_output=True,
    )
    return result.returncode == 0


def find_base(since: str | None) -> str:
    if since:
        return since
    if MARKER.exists():
        marked = MARKER.read_text().strip()
        if marked and is_ancestor(marked):
            return marked
    return git("rev-list", "-1", f"--before={DEFAULT_WINDOW}", "HEAD").strip()


def commit_files(sha: str) -> list[str]:
    # No rename detection, so a moved file lists both its old and new path.
    out = git("show", "--name-only", "--no-renames", "--format=", sha)
    return [line for line in out.splitlines() if line]


def list_commits(base: str) -> list[tuple[str, str]]:
    out = git(
        "log",
        "--first-parent",
        "--no-merges",
        "--reverse",
        "--format=%H%x1f%s",
        f"{base}..HEAD",
    )
    commits: list[tuple[str, str]] = []
    for line in out.splitlines():
        sha, _, subject = line.partition("\x1f")
        commits.append((sha, subject))
    return commits


def build_plan(
    base: str, head: str, commits: list[tuple[str, str]]
) -> tuple[Plan, Owned]:
    """The plan, and the owned files per component per commit."""
    entries: list[dict[str, Any]] = []
    owned: Owned = {}
    changed: list[str] = []
    for sha, subject in commits:
        files = commit_files(sha)
        entries.append({"sha": sha, "subject": subject, "files": files})
        changed.extend(files)
        for component, paths in stale_components(files).items():
            owned.setdefault(component, {})[sha] = paths
    plan: Plan = {
        "base": base,
        "head": head,
        "commits": entries,
        "components": {name: list(shas) for name, shas in sorted(owned.items())},
        "unowned": [
            path
            for path in unowned_paths(list(dict.fromkeys(changed)))
            if path.startswith(PRODUCT_ROOTS) and not path.startswith(NON_PRODUCT)
        ],
    }
    return plan, owned


def make_paths() -> Paths:
    root = Path(os.environ.get("RUNNER_TEMP") or tempfile.mkdtemp())
    root = root / "feature-map-reconcile"
    shutil.rmtree(root, ignore_errors=True)
    paths = Paths(
        root=root,
        plan=root / "plan.json",
        unowned=root / "unowned.txt",
        check_errors=root / "check_errors.txt",
        failure_context=root / "failure_context.txt",
        work=root / "work",
        reports=root / "reports",
        integrate_report=root / "integrate.json",
    )
    paths.work.mkdir(parents=True)
    paths.reports.mkdir()
    return paths


def write_inputs(paths: Paths, plan: Plan, failure: str) -> None:
    paths.plan.write_text(json.dumps(plan, indent=2))
    paths.unowned.write_text("\n".join(plan["unowned"]))
    paths.check_errors.write_text("")
    paths.failure_context.write_text(failure)


def write_work_file(
    paths: Paths,
    component: str,
    plan: Plan,
    by_commit: dict[str, list[str]],
    subjects: dict[str, str],
) -> None:
    lines = [
        f"# Work for component `{component}`",
        "",
        f"Document: `{MAP_PREFIX}/components/{component}.md`",
        f"Range: {plan['base']}..{plan['head']}",
        "",
    ]
    for sha, files in by_commit.items():
        diff = git("show", "--format=", sha, "--", *files)
        lines += [f"## {sha[:12]} {subjects[sha]}", "", "Owned files changed:"]
        lines += [f"- `{f}`" for f in files]
        lines += ["", "```diff", diff[:DIFF_LIMIT].rstrip("\n"), "```"]
        if len(diff) > DIFF_LIMIT:
            lines.append("[diff truncated: read the files at HEAD]")
        lines.append("")
    (paths.work / f"{component}.md").write_text("\n".join(lines))


def claude_prefix() -> list[str]:
    custom = os.environ.get("CLAUDE_BIN")
    if custom:
        return custom.split()
    return ["npx", "-y", f"@anthropic-ai/claude-code@{CLAUDE_CODE_VERSION}"]


def run_claude(
    prompt: str, model: str, add_dirs: list[Path], log_path: Path, timeout: int
) -> bool:
    argv = [
        *claude_prefix(),
        "-p",
        prompt,
        "--restricted",
        "--bare",
        "--strict-mcp-config",
        "--settings",
        '{"disableAllHooks": true}',
        "--tools",
        "Read,Glob,Grep,Edit,Write",
        "--permission-mode",
        "acceptEdits",
        "--model",
        model,
        "--max-turns",
        "80",
    ]
    for directory in add_dirs:
        argv += ["--add-dir", str(directory)]
    try:
        with log_path.open("wb") as log:
            result = subprocess.run(
                argv,
                cwd=REPO_ROOT,
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=timeout,
            )
    except (OSError, subprocess.SubprocessError) as exc:
        log_path.write_text(f"agent failed to run: {exc!r}\n")
        return False
    return result.returncode == 0


def render(template: str, **values: str) -> str:
    text = (PROMPTS / template).read_text()
    return string.Template(text).substitute(**values)


def read_report(path: Path, keys: set[str]) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not keys <= data.keys():
        return None
    return data


def run_component(
    paths: Paths, component: str, plan: Plan, model: str
) -> dict[str, Any] | None:
    report = paths.reports / f"{component}.json"
    prompt = render(
        "feature-map-reconcile-component.md",
        COMPONENT=component,
        DOC_PATH=f"{MAP_PREFIX}/components/{component}.md",
        WORK_FILE=str(paths.work / f"{component}.md"),
        REPORT_FILE=str(report),
        BASE=plan["base"],
        HEAD=plan["head"],
    )
    ok = run_claude(
        prompt,
        model,
        [paths.work, paths.reports],
        paths.root / f"{component}.log",
        COMPONENT_TIMEOUT,
    )
    return read_report(report, REPORT_KEYS) if ok else None


def run_integrator(paths: Paths, model: str, run: int, outcome: Outcome) -> None:
    paths.integrate_report.unlink(missing_ok=True)
    prompt = render(
        "feature-map-reconcile-integrate.md",
        PLAN_FILE=str(paths.plan),
        REPORTS_DIR=str(paths.reports),
        UNOWNED_FILE=str(paths.unowned),
        CHECK_ERRORS_FILE=str(paths.check_errors),
        FAILURE_CONTEXT_FILE=str(paths.failure_context),
        REPORT_FILE=str(paths.integrate_report),
    )
    ok = run_claude(
        prompt,
        model,
        [paths.root],
        paths.root / f"integrate-{run}.log",
        INTEGRATOR_TIMEOUT,
    )
    report = read_report(paths.integrate_report, INTEGRATE_KEYS) if ok else None
    if report:
        outcome.integrator.append(report)
    else:
        outcome.failed.append(f"integrator (pass {run})")


def status_entries(*pathspec: str) -> list[tuple[str, str]]:
    """(status code, path) from `git status`, with untracked files listed singly."""
    out = git("status", "--porcelain", "-z", "-uall", "--", *pathspec)
    parts = out.split("\0")
    entries: list[tuple[str, str]] = []
    i = 0
    while i < len(parts) and parts[i]:
        code, path = parts[i][:2], parts[i][3:]
        entries.append((code, path))
        i += 2 if code[0] in "RC" else 1
    return entries


def map_changes() -> list[str]:
    return [
        path
        for _, path in status_entries(MAP_PREFIX)
        if "__pycache__" not in path and REPO_ROOT / path != MARKER
    ]


def em_dash_errors() -> list[str]:
    errors: list[str] = []
    for path in map_changes():
        file = REPO_ROOT / path
        if (
            file.suffix == ".md"
            and file.is_file()
            and EM_DASH in file.read_text(errors="replace")
        ):
            errors.append(f"{path}: contains an em dash (U+2014); rewrite the sentence")
    return errors


def integrity_errors() -> list[str]:
    return check() + em_dash_errors()


def integrity_loop(
    paths: Paths, model: str, first_run: int, outcome: Outcome
) -> list[str]:
    errors = integrity_errors()
    for attempt in range(MAX_REINTEGRATIONS):
        if not errors:
            break
        paths.check_errors.write_text("\n".join(errors))
        run_integrator(paths, model, first_run + attempt, outcome)
        errors = integrity_errors()
    return errors


def revert_outside_map() -> list[str]:
    reverted: list[str] = []
    for code, path in status_entries():
        if path.startswith(f"{MAP_PREFIX}/"):
            continue
        if code == "??":
            (REPO_ROOT / path).unlink(missing_ok=True)
        else:
            git("checkout", "--", path)
        reverted.append(path)
    return reverted


def fan_out(
    paths: Paths, plan: Plan, owned: Owned, args: argparse.Namespace, outcome: Outcome
) -> None:
    subjects = {c["sha"]: c["subject"] for c in plan["commits"]}
    for component, by_commit in owned.items():
        write_work_file(paths, component, plan, by_commit, subjects)
    with ThreadPoolExecutor(max_workers=args.max_parallel) as pool:
        futures = {
            name: pool.submit(run_component, paths, name, plan, args.component_model)
            for name in owned
        }
    for name, future in futures.items():
        report = future.result()
        if report is None:
            outcome.failed.append(name)
        else:
            outcome.reports[name] = report


def rationale(plan: Plan, outcome: Outcome, truncated: int) -> str:
    count = len(plan["commits"])
    lines = [f"Range `{plan['base'][:10]}..{plan['head'][:10]}`, {count} commits."]
    if truncated:
        lines.append(
            f"The range had {count + truncated} commits. Only the newest {count} were reviewed."
        )
    if outcome.repair:
        lines.append(
            "This was a repair run. It fixed the failure from an earlier CI run."
        )
    updated = [(n, r) for n, r in sorted(outcome.reports.items()) if r["changed"]]
    if updated:
        lines += ["", "Updated:"]
        lines += [f"- **{name}**: {r['summary']}" for name, r in updated]
    same = sorted(n for n, r in outcome.reports.items() if not r["changed"])
    if same:
        lines += ["", f"Reviewed with no change: {', '.join(same)}"]
    if outcome.failed:
        failed = ", ".join(sorted(outcome.failed))
        lines += ["", f"Failed (not reconciled, retried next run): {failed}"]
    lines += [
        f"\nIntegrator: {r['summary']}" for r in outcome.integrator if r["summary"]
    ]
    human = [
        f"- **{name}**: {item}"
        for name, r in sorted(outcome.reports.items())
        for item in r["needs_human"]
    ]
    human += [f"- {item}" for r in outcome.integrator for item in r["needs_human"]]
    if human:
        lines += ["", "Needs a human:", *human]
    if outcome.errors:
        lines += ["", "The integrity check still fails:"]
        lines += [f"- {error}" for error in outcome.errors]
    lines += ["", "This run does not change any `Verified against` line."]
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--rationale-file", type=Path)
    parser.add_argument("--failure-context-file", type=Path)
    parser.add_argument("--since")
    parser.add_argument("--max-parallel", type=int, default=6)
    parser.add_argument("--component-model", default="claude-sonnet-5-5")
    parser.add_argument("--integrator-model", default="claude-opus-5-5")
    parser.add_argument("--max-commits", type=int, default=400)
    args = parser.parse_args()
    if args.write and not args.rationale_file:
        parser.error("--write needs --rationale-file")
    return args


def say_nothing(args: argparse.Namespace) -> int:
    print("nothing to reconcile")
    if args.rationale_file:
        args.rationale_file.write_text(
            "Nothing to reconcile: no new commits on main.\n"
        )
    return 0


def warm_cache() -> None:
    if not os.environ.get("CLAUDE_BIN"):
        subprocess.run([*claude_prefix(), "--version"], capture_output=True)


def execute(args: argparse.Namespace, plan: Plan, owned: Owned) -> Outcome:
    failure = ""
    if args.failure_context_file and args.failure_context_file.exists():
        failure = args.failure_context_file.read_text()
    outcome = Outcome(repair=bool(failure.strip()))
    paths = make_paths()
    write_inputs(paths, plan, failure)
    warm_cache()
    if not outcome.repair:
        fan_out(paths, plan, owned, args, outcome)
    wanted = any(r["for_integrator"] for r in outcome.reports.values())
    run = 0
    if outcome.repair or wanted or plan["unowned"]:
        run = 1
        run_integrator(paths, args.integrator_model, run, outcome)
    outcome.errors = integrity_loop(paths, args.integrator_model, run + 1, outcome)
    return outcome


def main() -> int:
    args = parse_args()
    head = git("rev-parse", "HEAD").strip()
    base = find_base(args.since)
    if not base or base == head:
        return say_nothing(args)
    commits = list_commits(base)
    truncated = max(0, len(commits) - args.max_commits)
    if truncated:
        commits = commits[truncated:]
        base = git("rev-parse", f"{commits[0][0]}^").strip()
    plan, owned = build_plan(base, head, commits)
    if not args.write:
        print(json.dumps(plan, indent=2))
        return 0

    outcome = execute(args, plan, owned)
    reverted = revert_outside_map()
    if reverted:
        print("Reverted changes outside the feature map:", *reverted, sep="\n  ")
    args.rationale_file.write_text(rationale(plan, outcome, truncated))
    if outcome.errors:
        print("\n".join(outcome.errors))
        return 1
    if outcome.failed and not outcome.reports and not outcome.integrator:
        # Every agent failed (a bad key, an outage): fail so the run alerts.
        print("Every agent failed:", ", ".join(outcome.failed))
        return 1
    if not outcome.repair and not outcome.failed and map_changes():
        MARKER.write_text(head + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
