"""GitHub's shapes. Reads a pull request and review comments, writes the run's output.

Reads go through the `gh` CLI, which owns auth, pagination and retries. The tool
posts nothing. `write_outputs` writes the check run body and the summary
comment, and the workflow posts both with `gh api`.
"""

import json
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Literal, TypedDict

from semantic_lint.diff import FilePatch, PullRequest
from semantic_lint.registry import Registry, RuleId, Severity
from semantic_lint.review import Report
from semantic_lint.screen import Hit

__all__ = [
    "CHECK_RUN_FILE",
    "SUMMARY_FILE",
    "SUMMARY_MARKER",
    "base_sha",
    "compare",
    "pull_request",
    "render_summary",
    "review_comment",
    "write_outputs",
]

CHECK_NAME: str = "semantic-lint"
CHECK_RUN_FILE: str = "check-run.json"
SUMMARY_FILE: str = "summary.md"
# The workflow's comment upsert finds the comment by the first line and reads
# the second to decide whether a first comment is worth posting.
SUMMARY_MARKER: str = "<!-- semantic-lint:summary -->"
CLEAN_MARKER: str = "<!-- semantic-lint: clean -->"
FINDINGS_MARKER: str = "<!-- semantic-lint: findings -->"
# GitHub rejects a check run summary longer than this.
MAX_SUMMARY_CHARS: int = 65535


def _gh_api(path: str) -> Any:
    result = subprocess.run(
        ["gh", "api", path], capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        raise RuntimeError(f"gh api {path} failed: {result.stderr.strip()}")
    return json.loads(result.stdout)


def compare(repo: str, base: str, head: str) -> Any:
    """`base...head` trimmed to the fields windows need. Eval caches this shape."""
    payload = _gh_api(f"repos/{repo}/compare/{base}...{head}")
    return {
        "status": payload["status"],
        "ahead_by": payload["ahead_by"],
        "files": [
            {
                "filename": item["filename"],
                "status": item["status"],
                "patch": item.get("patch"),
            }
            for item in payload.get("files", [])
        ],
    }


def pull_request(repo: str, number: int, compare_json: Path | None) -> PullRequest:
    """The PR's shas, and its diff from `compare_json` or from the compare API."""
    pull = _gh_api(f"repos/{repo}/pulls/{number}")
    base, head = str(pull["base"]["sha"]), str(pull["head"]["sha"])
    payload = (
        json.loads(compare_json.read_text())
        if compare_json is not None
        else compare(repo, base, head)
    )
    return PullRequest(
        repo=repo,
        number=number,
        base_sha=base,
        head_sha=head,
        files=tuple(
            FilePatch(item["filename"], item.get("patch")) for item in payload["files"]
        ),
    )


def base_sha(repo: str, number: int) -> str:
    return str(_gh_api(f"repos/{repo}/pulls/{number}")["base"]["sha"])


def review_comment(repo: str, comment_id: int) -> Any | None:
    """A pull request review comment, or None when GitHub no longer has it."""
    try:
        return _gh_api(f"repos/{repo}/pulls/comments/{comment_id}")
    except RuntimeError as error:
        if "(HTTP 404)" in str(error):
            return None
        raise


def render_summary(report: Report, registry: Registry) -> str:
    """Markdown for stdout, the check run summary and the PR comment."""
    rules = {rule.id: rule for rule in registry.rules}
    settings = registry.settings
    head = report.pr.head_sha
    blob = f"https://github.com/{report.pr.repo}/blob/{head}"
    lines = [
        SUMMARY_MARKER,
        FINDINGS_MARKER if report.findings else CLEAN_MARKER,
        f"### Semantic lint (advisory) for {head[:7]}",
        "",
        f"{len(report.findings)} findings. Screened {report.windows_screened} windows "
        f"against {report.rules_live} live rules and {report.rules_shadow} shadow rules.",
    ]
    if report.findings:
        lines += [
            "",
            "| Severity | Rule | Where | Finding |",
            "| --- | --- | --- | --- |",
        ]
        for finding in report.findings:
            where = f"[{finding.path}:{finding.line}]({blob}/{finding.path}#L{finding.line})"
            message = _cell(finding.message)
            if finding.citation:
                cited = finding.citation
                message += (
                    f" (`{_cell(cited.symbol)}` in [{cited.path}]({blob}/{cited.path}))"
                )
            severity = rules[finding.rule_id].severity.value
            lines.append(f"| {severity} | `{finding.rule_id}` | {where} | {message} |")
    jev, llm = report.jev_usage, report.llm_usage
    prices = settings.prices
    jev_cost = jev.input_tokens * prices.jev_input / 1e6
    llm_cost = (
        llm.input_tokens * prices.llm_input + llm.output_tokens * prices.llm_output
    ) / 1e6
    sent = (
        len(report.findings)
        + len(report.hits_dropped_by_llm)
        + len(report.hits_without_citation)
    )
    lines += [
        "",
        "<details><summary>Cost, latency and coverage</summary>",
        "",
        "| Stage | Requests | Input tokens | Output tokens | Cost | Time |",
        "| --- | --- | --- | --- | --- | --- |",
        f"| Jev {settings.jev_model} | {jev.requests} | {jev.input_tokens:,} | "
        f"{jev.output_tokens:,} | ${jev_cost:.4f} | {jev.seconds:.1f} s |",
        f"| LLM {settings.llm.model} | {llm.requests} | {llm.input_tokens:,} | "
        f"{llm.output_tokens:,} | ${llm_cost:.4f} | {llm.seconds:.1f} s |",
        f"| Total | | | | ${report.cost_usd:.4f} | {report.seconds:.1f} s |",
        "",
        f"- Live hits sent to the LLM: {sent}. Judged wrong: "
        f"{len(report.hits_dropped_by_llm)}. No verified citation (no_citation): "
        f"{len(report.hits_without_citation)}. Over budget: {len(report.over_budget)}.",
        f"- Shadow hits, not posted: {len(report.shadow_hits)}"
        + _rule_counts(report.shadow_hits),
        f"- Not screened: {report.windows_over_budget} windows over budget, "
        f"{len(report.files_without_patch)} files without a patch.",
        f"- Inactive rules (no valid calibration): {report.rules_inactive}.",
        "",
        "</details>",
    ]
    return "\n".join(lines)[:MAX_SUMMARY_CHARS] + "\n"


def _rule_counts(hits: Sequence[Hit]) -> str:
    counts: dict[RuleId, int] = {}
    for hit in hits:
        counts[hit.rule.id] = counts.get(hit.rule.id, 0) + 1
    if not counts:
        return "."
    return (
        " (" + ", ".join(f"`{rule}` {n}" for rule, n in sorted(counts.items())) + ")."
    )


def _cell(text: str) -> str:
    return " ".join(text.split()).replace("|", "\\|")


class _Annotation(TypedDict):
    path: str
    start_line: int
    end_line: int
    annotation_level: Literal["notice", "warning"]
    title: str
    message: str


class _CheckRunOutput(TypedDict):
    title: str
    summary: str
    annotations: list[_Annotation]


class _CheckRun(TypedDict):
    name: str
    head_sha: str
    status: Literal["completed"]
    # Advisory, so never "failure".
    conclusion: Literal["success", "neutral"]
    output: _CheckRunOutput


def _check_run(report: Report, registry: Registry, summary: str) -> _CheckRun:
    rules = {rule.id: rule for rule in registry.rules}
    annotations: list[_Annotation] = [
        {
            "path": finding.path,
            "start_line": finding.line,
            "end_line": finding.line,
            "annotation_level": (
                "warning"
                if rules[finding.rule_id].severity is Severity.FIX
                else "notice"
            ),
            "title": f"{finding.rule_id}: {rules[finding.rule_id].title}"[:255],
            "message": finding.message,
        }
        for finding in report.findings[: registry.settings.budget.max_annotations]
    ]
    return {
        "name": CHECK_NAME,
        "head_sha": report.pr.head_sha,
        "status": "completed",
        "conclusion": "neutral" if report.findings else "success",
        "output": {
            "title": f"{len(report.findings)} findings" if report.findings else "Clean",
            "summary": summary,
            "annotations": annotations,
        },
    }


def write_outputs(report: Report, registry: Registry, directory: Path) -> None:
    """Write the check run POST body and the summary comment for the workflow."""
    summary = render_summary(report, registry)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / SUMMARY_FILE).write_text(summary)
    (directory / CHECK_RUN_FILE).write_text(
        json.dumps(_check_run(report, registry, summary), indent=2) + "\n"
    )
