"""Review a pull request. Screen its windows, then have the LLM write findings.

`review()` is the CI pipeline behind one call. It owns the per-PR budget, the
choice of hits that reach the LLM, the repo search, and the check on every
answer. The LLM gets one window with all its hits and has no tools. For rules
that need repository evidence, code runs `git grep` first and the LLM may post
only when it cites a symbol those results contain.
"""

import json
import re
import subprocess
import sys
import time
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from semantic_lint.diff import Added, PullRequest, Window
from semantic_lint.github import (
    CHECK_NAME,
    MAX_SUMMARY_CHARS,
    SUMMARY_MARKER,
    Annotation,
    CheckRun,
)
from semantic_lint.registry import LlmSettings, Registry, Rule, RuleId, Severity
from semantic_lint.screen import Hit, Jev, Mode, Usage, rule_mode, screen

REPO_ROOT: Path = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "backend" / "scripts"))

from openai_agent import (  # noqa: E402
    call_responses_sync,
    extract_output_text,
)

__all__ = [
    "Failed",
    "Finding",
    "GrepMatch",
    "Llm",
    "Outcome",
    "Report",
    "Skipped",
    "check_run",
    "parse_answer",
    "render_summary",
    "review",
    "search_repo",
]

PARALLEL_WINDOWS: int = 4
GIT_TIMEOUT_SECONDS: float = 30.0
MAX_MATCH_CHARS: int = 200
MATCHES_PER_FILE: int = 3
# Name parts too generic to find a look-alike helper by.
_COMMON_WORDS: frozenset[str] = frozenset(
    {"get", "set", "for", "from", "with", "the", "and", "make", "build", "create"}
    | {"handle", "process", "data", "value", "list", "dict", "item", "items"}
    | {"helper", "util", "utils", "info", "config", "init", "self", "none"}
)
_DEFINITION = re.compile(
    r"^\s*(?:export\s+)?(?:async\s+)?(?:def|class|function|const|let)\s+([A-Za-z_]\w*)"
    r"|^([A-Z][A-Z0-9_]{2,})\s*(?::[^=]*)?="
)
_HINT_NAME = re.compile(r"\b([a-z_][a-z0-9]*(?:_[a-z0-9*]+)+)\b")
_HINT_PATH = re.compile(r"\b((?:backend|web)/[\w./-]*[\w/])")


@dataclass(frozen=True)
class GrepMatch:
    """One `git grep` line. `commit` is the PR's base or head."""

    commit: str
    path: str
    line: int
    text: str


@dataclass(frozen=True)
class Finding:
    rule_id: RuleId
    path: str
    # A member of the window's anchor_lines.
    line: int
    message: str
    # For repo-search rules, a symbol the grep results contain.
    cited_symbol: str | None


@dataclass(frozen=True)
class Report:
    pr: PullRequest
    findings: tuple[Finding, ...]
    hits_dropped_by_llm: tuple[Hit, ...]
    over_budget: tuple[Hit, ...]
    shadow_hits: tuple[Hit, ...]
    jev_usage: Usage
    llm_usage: Usage
    seconds: float
    cost_usd: float
    windows_screened: int
    windows_over_budget: int
    files_without_patch: tuple[str, ...]
    rules_live: int
    rules_shadow: int
    rules_inactive: int


@dataclass(frozen=True)
class Skipped:
    reason: str


@dataclass(frozen=True)
class Failed:
    error: str


type Outcome = Report | Skipped | Failed


class Llm:
    """The OpenAI call. Tests subclass it and override `write`."""

    def __init__(self, api_key: str) -> None:
        self._api_key: str = api_key

    def write(
        self, prompt: str, schema: dict[str, Any], settings: LlmSettings
    ) -> tuple[str, Usage]:
        started = time.monotonic()
        response = call_responses_sync(
            prompt,
            settings.model,
            self._api_key,
            schema,
            settings.timeout_seconds,
            settings.reasoning_effort,
        )
        usage = response.get("usage") or {}
        return extract_output_text(response), Usage(
            requests=1,
            input_tokens=int(usage.get("input_tokens", 0)),
            output_tokens=int(usage.get("output_tokens", 0)),
            seconds=time.monotonic() - started,
        )


def review(pr: PullRequest, registry: Registry, jev: Jev, llm: Llm) -> Report:
    """Screen the PR with every live and shadow rule, then write live findings.

    Raises when Jev, OpenAI or git fails. The caller turns that into Failed.
    """
    started = time.monotonic()
    settings = registry.settings
    budget = settings.budget
    modes = {rule.id: rule_mode(rule, settings) for rule in registry.rules}
    screened = registry.only(
        r for r, mode in modes.items() if mode is not Mode.INACTIVE
    )
    in_scope = [
        window
        for window in pr.windows(settings.window.max_lines)
        if screened.in_scope(window.path)
    ]
    windows = in_scope[: budget.max_windows]
    screening = screen(windows, screened, jev)
    hits = screening.hits(screened)
    live = [hit for hit in hits if modes[hit.rule.id] is Mode.LIVE]
    selected, over_budget = _select(live, registry)
    by_window: dict[str, list[Hit]] = {}
    for hit in selected:
        by_window.setdefault(hit.window.id, []).append(hit)
    with ThreadPoolExecutor(PARALLEL_WINDOWS) as pool:
        answers = list(
            pool.map(
                lambda group: _write_window(group, pr, registry, llm),
                by_window.values(),
            )
        )
    findings = tuple(
        sorted(
            (finding for found, _, _ in answers for finding in found),
            key=lambda finding: (finding.path, finding.line),
        )
    )
    llm_usage = sum((usage for _, _, usage in answers), Usage())
    prices = settings.prices
    return Report(
        pr=pr,
        findings=findings,
        hits_dropped_by_llm=tuple(hit for _, dropped, _ in answers for hit in dropped),
        over_budget=tuple(over_budget),
        shadow_hits=tuple(hit for hit in hits if modes[hit.rule.id] is Mode.SHADOW),
        jev_usage=screening.usage,
        llm_usage=llm_usage,
        seconds=time.monotonic() - started,
        cost_usd=(
            screening.usage.input_tokens * prices.jev_input
            + llm_usage.input_tokens * prices.llm_input
            + llm_usage.output_tokens * prices.llm_output
        )
        / 1e6,
        windows_screened=len(windows),
        windows_over_budget=len(in_scope) - len(windows),
        files_without_patch=tuple(f.path for f in pr.files if f.patch is None),
        rules_live=sum(mode is Mode.LIVE for mode in modes.values()),
        rules_shadow=sum(mode is Mode.SHADOW for mode in modes.values()),
        rules_inactive=sum(mode is Mode.INACTIVE for mode in modes.values()),
    )


def _select(hits: Sequence[Hit], registry: Registry) -> tuple[list[Hit], list[Hit]]:
    """Split live hits into (sent to the LLM, over budget).

    Fix before nit, then by margin. At most `max_findings_per_rule` per rule, at
    most `max_annotations` in all, on at most `max_llm_windows` windows.
    """
    budget = registry.settings.budget
    ranked = sorted(
        hits, key=lambda hit: (hit.rule.severity is not Severity.FIX, -hit.margin)
    )
    selected: list[Hit] = []
    over: list[Hit] = []
    per_rule: dict[RuleId, int] = {}
    windows: set[str] = set()
    for hit in ranked:
        new_window = hit.window.id not in windows
        if (
            per_rule.get(hit.rule.id, 0) >= budget.max_findings_per_rule
            or len(selected) >= budget.max_annotations
            or (new_window and len(windows) >= budget.max_llm_windows)
        ):
            over.append(hit)
            continue
        selected.append(hit)
        per_rule[hit.rule.id] = per_rule.get(hit.rule.id, 0) + 1
        windows.add(hit.window.id)
    return selected, over


def _write_window(
    hits: Sequence[Hit], pr: PullRequest, registry: Registry, llm: Llm
) -> tuple[list[Finding], list[Hit], Usage]:
    window = hits[0].window
    settings = registry.settings
    searching = [hit.rule for hit in hits if hit.rule.needs_repo_search]
    matches = (
        search_repo(window, searching, pr, settings.budget.max_search_matches)
        if searching
        else ()
    )
    prompt = _prompt(window, hits, pr, matches, registry)
    text, usage = llm.write(prompt, _schema(window, hits), settings.llm)
    findings, dropped = parse_answer(text, window, hits, matches)
    return findings, dropped, usage


def parse_answer(
    text: str, window: Window, hits: Sequence[Hit], matches: Sequence[GrepMatch]
) -> tuple[list[Finding], list[Hit]]:
    """Findings the LLM posted, and the hits it dropped or left out.

    Raises ValueError on output the schema should have made impossible, such
    as a line outside the window or a rule that was not asked.
    """
    items = json.loads(text)["findings"]
    by_rule = {hit.rule.id: hit for hit in hits}
    answered: dict[RuleId, Finding | None] = {}
    for item in items:
        rule_id = RuleId(item["rule"])
        if rule_id not in by_rule:
            raise ValueError(f"LLM answered rule {rule_id}, which was not asked")
        if item["line"] not in window.anchor_lines:
            raise ValueError(
                f"LLM pointed {rule_id} at line {item['line']}, outside the window"
            )
        if rule_id in answered:
            continue
        rule = by_rule[rule_id].rule
        symbol = (item.get("cited_symbol") or "").strip() or None
        message = item["message"].replace(" \u2014 ", "; ").strip()
        evidence = not rule.needs_repo_search or (
            symbol is not None and any(symbol in match.text for match in matches)
        )
        answered[rule_id] = (
            Finding(rule_id, window.path, item["line"], message, symbol)
            if item["post"] is True and evidence and message
            else None
        )
    findings = [finding for finding in answered.values() if finding]
    dropped = [hit for hit in hits if answered.get(hit.rule.id) is None]
    return findings, dropped


def search_repo(
    window: Window, rules: Sequence[Rule], pr: PullRequest, limit: int
) -> tuple[GrepMatch, ...]:
    """Grep evidence for repo-search rules, capped at `limit` lines.

    Names the window defines are searched at the PR head, which shows their
    callers. Look-alike definitions and the names and paths a rule's hint
    gives are searched at the base, so every match predates the PR.
    """
    names = _defined_names(window)
    words = sorted(
        {
            word
            for name in names
            for word in re.split(r"_|(?<=[a-z])(?=[A-Z])", name)
            if len(word) >= 4 and word.lower() not in _COMMON_WORDS
        }
    )
    hints = " ".join(rule.repo_search_hint or "" for rule in rules)
    hint_names = sorted(set(_HINT_NAME.findall(hints)) - set(names))
    hint_paths = sorted(set(_HINT_PATH.findall(hints)))
    searches: list[tuple[str, str, bool, Sequence[str]]] = [
        (pr.head_sha, re.escape(name), True, ()) for name in names
    ]
    if words:
        definition = r"(def|class|function|const)\s+\w*(" + "|".join(words) + r")\w*"
        searches.append((pr.base_sha, definition, False, hint_paths))
    searches += [
        (pr.base_sha, re.escape(name).replace(r"\*", r"\w*"), True, ())
        for name in hint_names
    ]
    matches: list[GrepMatch] = []
    for commit, pattern, whole_word, paths in searches:
        matches.extend(_git_grep(commit, pattern, whole_word, paths))
        if len(matches) >= limit:
            break
    return tuple(dict.fromkeys(matches))[:limit]


def _defined_names(window: Window) -> list[str]:
    names: list[str] = []
    for line in window.lines:
        if not isinstance(line, Added):
            continue
        if match := _DEFINITION.match(line.text):
            names.append(match.group(1) or match.group(2))
    return list(dict.fromkeys(names))


def _git_grep(
    commit: str, pattern: str, whole_word: bool, paths: Sequence[str]
) -> list[GrepMatch]:
    _ensure_commit(commit)
    command = ["git", "-C", str(REPO_ROOT), "grep", "-n", "-I", "-E"]
    command += [f"--max-count={MATCHES_PER_FILE}", *(["-w"] if whole_word else [])]
    command += ["-e", pattern, commit, "--", *(paths or ["."])]
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=GIT_TIMEOUT_SECONDS,
        check=False,
    )
    if result.returncode not in (0, 1):
        raise RuntimeError(f"git grep failed: {result.stderr.strip()}")
    matches: list[GrepMatch] = []
    for row in result.stdout.splitlines():
        path, line, text = row.removeprefix(f"{commit}:").split(":", 2)
        matches.append(
            GrepMatch(commit, path, int(line), text.strip()[:MAX_MATCH_CHARS])
        )
    return matches


def _ensure_commit(commit: str) -> None:
    present = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "cat-file", "-e", f"{commit}^{{commit}}"],
        capture_output=True,
        check=False,
    )
    if present.returncode != 0:
        subprocess.run(
            [
                "git",
                "-C",
                str(REPO_ROOT),
                "fetch",
                "--no-tags",
                "--quiet",
                "origin",
                commit,
            ],
            check=True,
            timeout=GIT_TIMEOUT_SECONDS * 4,
        )


_INSTRUCTIONS = """\
You review one window of a pull request diff in the Onyx repository. A fast
screen flagged the rules below for this window. The screen is often wrong.

For each rule, decide whether the added lines in the window break it. Use the
file patch only as context. Set "post" to false when the rule does not apply,
when the code only resembles the pattern, or when the problem sits in lines the
PR did not add.

When a rule applies, write the comment an Onyx reviewer would leave. Be direct
and short, one to three sentences, and name the fix. Match the voice of the
reviewer quotes. Do not restate the rule title. Do not use em dashes. Set
"line" to the added line the comment is about.

A rule marked "needs repo search" may post only when the search results show
the evidence, such as the existing helper or the callers. Put the exact symbol
you rely on, copied from the results, in "cited_symbol". For every other rule
set "cited_symbol" to null.
"""


def _prompt(
    window: Window,
    hits: Sequence[Hit],
    pr: PullRequest,
    matches: Sequence[GrepMatch],
    registry: Registry,
) -> str:
    settings = registry.settings
    sections = [_INSTRUCTIONS]
    if settings.llm.never_flag:
        sections.append(
            "Never raise these. Reviewers dismissed them when other bots did:\n"
            + "\n".join(f"- {pattern}" for pattern in settings.llm.never_flag)
        )
    sections.append("## Rules\n\n" + "\n\n".join(_rule_text(hit.rule) for hit in hits))
    sections.append(
        f"## Window in `{window.path}` (new-side line numbers on the left)\n\n"
        f"```diff\n{window.render_numbered()}\n```"
    )
    sections.append(
        "## File patch context\n\n```diff\n"
        + _patch_context(
            pr.patch_for(window.path), window, settings.budget.patch_context_chars
        )
        + "\n```"
    )
    if any(hit.rule.needs_repo_search for hit in hits):
        rows = "\n".join(
            f"{'base' if m.commit == pr.base_sha else 'head'} {m.path}:{m.line}: {m.text}"
            for m in matches
        )
        sections.append(f"## Repo search results\n\n{rows or 'No matches.'}")
    return "\n\n".join(sections)


def _rule_text(rule: Rule) -> str:
    lines = [f"### {rule.id}: {rule.title}", f"Severity {rule.severity.value}."]
    if rule.needs_repo_search:
        lines.append("Needs repo search.")
        if rule.repo_search_hint:
            lines.append(f"Where to look: {rule.repo_search_hint}")
    lines.append(rule.guidance)
    for example in rule.flag_examples:
        quote = f' A reviewer said: "{example.quote.said}"' if example.quote else ""
        lines.append(f"Flagged example.{quote}\n```\n{example.code}\n```")
    lines.extend(
        f"Accepted look-alike, do not flag:\n```\n{example.code}\n```"
        for example in rule.clean_examples
    )
    return "\n".join(lines)


def _patch_context(patch: str, window: Window, max_chars: int) -> str:
    if len(patch) <= max_chars:
        return patch
    body = window.render().split("\n", 1)[-1]
    center = max(patch.find(body[:200]), 0) + len(body) // 2
    start = max(0, min(center - max_chars // 2, len(patch) - max_chars))
    return patch[start : start + max_chars]


def _schema(window: Window, hits: Sequence[Hit]) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["findings"],
        "properties": {
            "findings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["rule", "post", "line", "message", "cited_symbol"],
                    "properties": {
                        "rule": {
                            "type": "string",
                            "enum": [hit.rule.id for hit in hits],
                        },
                        "post": {"type": "boolean"},
                        "line": {"type": "integer", "enum": list(window.anchor_lines)},
                        "message": {"type": "string"},
                        "cited_symbol": {"type": ["string", "null"]},
                    },
                },
            }
        },
    }


def render_summary(outcome: Outcome, registry: Registry, head_sha: str) -> str:
    """Markdown for stdout, the check run summary and the PR comment.

    The first line is the marker the workflow's comment upsert looks for.
    """
    match outcome:
        case Skipped(reason=reason):
            return f"{SUMMARY_MARKER} findings=0 -->\n### Semantic lint skipped\n\n{reason}\n"
        case Failed(error=error):
            return (
                f"{SUMMARY_MARKER} findings=0 -->\n### Semantic lint failed\n\n"
                f"The linter stopped with an error. The job log has the details.\n\n"
                f"```\n{error[:2000]}\n```\n"
            )
        case Report():
            return _render_report(outcome, registry, head_sha)


def _render_report(report: Report, registry: Registry, head_sha: str) -> str:
    rules = {rule.id: rule for rule in registry.rules}
    settings = registry.settings
    blob = f"https://github.com/{report.pr.repo}/blob/{head_sha}"
    lines = [
        f"{SUMMARY_MARKER} findings={len(report.findings)} -->",
        f"### Semantic lint (advisory) for {head_sha[:7]}",
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
            rule = rules[finding.rule_id]
            where = f"[{finding.path}:{finding.line}]({blob}/{finding.path}#L{finding.line})"
            lines.append(
                f"| {rule.severity.value} | `{rule.id}` | {where} | {_cell(finding.message)} |"
            )
    jev, llm = report.jev_usage, report.llm_usage
    prices = settings.prices
    jev_cost = jev.input_tokens * prices.jev_input / 1e6
    llm_cost = (
        llm.input_tokens * prices.llm_input + llm.output_tokens * prices.llm_output
    ) / 1e6
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
        f"- Live hits sent to the LLM: {len(report.findings) + len(report.hits_dropped_by_llm)}. "
        f"Dropped by the LLM: {len(report.hits_dropped_by_llm)}. "
        f"Over budget: {len(report.over_budget)}.",
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


def check_run(outcome: Outcome, registry: Registry, head_sha: str) -> CheckRun:
    """The check run body. `success` only for a clean review, `neutral` otherwise."""
    summary = render_summary(outcome, registry, head_sha)
    match outcome:
        case Report(findings=findings):
            rules = {rule.id: rule for rule in registry.rules}
            annotations: list[Annotation] = [
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
                for finding in findings[: registry.settings.budget.max_annotations]
            ]
            title = f"{len(findings)} findings" if findings else "No findings"
            conclusion: Literal["success", "neutral"] = (
                "neutral" if findings else "success"
            )
        case Skipped(reason=reason):
            annotations, title, conclusion = [], f"Skipped: {reason}", "neutral"
        case Failed():
            annotations, title = [], "Linter error. The job log has the details."
            conclusion = "neutral"
    return {
        "name": CHECK_NAME,
        "head_sha": head_sha,
        "status": "completed",
        "conclusion": conclusion,
        "output": {"title": title, "summary": summary, "annotations": annotations},
    }
