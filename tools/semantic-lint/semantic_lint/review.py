"""Review a pull request. Screen its windows, then have the LLM write findings.

`review()` is the CI pipeline behind one call. It owns the per-PR budget, the
choice of hits that reach the LLM, the prompt, and the check on every answer.
The LLM sees one window with all its hits. For rules that need repository
evidence it may call `git_grep` on the checkout, and code keeps such a finding
only when `git grep` finds the symbol it cites in the file it cites.
"""

import json
import subprocess
import sys
import time
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, TypedDict

from semantic_lint.diff import PullRequest, Window
from semantic_lint.registry import LlmSettings, Registry, Rule, RuleId, Severity
from semantic_lint.screen import Hit, Jev, Mode, Usage, rule_mode, screen

REPO_ROOT: Path = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "backend" / "scripts"))

from openai_agent import (  # noqa: E402
    api_request,
    extract_output_text,
    structured_request_body,
)

__all__ = [
    "Citation",
    "Finding",
    "Llm",
    "Report",
    "git_grep",
    "parse_answer",
    "review",
]

PARALLEL_WINDOWS: int = 4
# Bounds on the LLM's repo search for one window. The round after the last
# allowed one forbids tools, so the model must answer.
MAX_TOOL_ROUNDS: int = 4
MAX_GREP_CALLS: int = 8
MAX_GREP_LINES: int = 60
MAX_GREP_LINE_CHARS: int = 200
GREP_TIMEOUT_SECONDS: float = 10.0
# A shorter citation, such as "def", is found in almost any file.
MIN_CITED_SYMBOL_CHARS: int = 4


@dataclass(frozen=True)
class Citation:
    symbol: str
    path: str


@dataclass(frozen=True)
class Finding:
    rule_id: RuleId
    path: str
    # A member of the window's anchor_lines.
    line: int
    message: str
    # Set for repo-search rules only, and only after `git grep` confirmed it.
    citation: Citation | None


@dataclass(frozen=True)
class Report:
    pr: PullRequest
    findings: tuple[Finding, ...]
    hits_dropped_by_llm: tuple[Hit, ...]
    # Repo-search hits the LLM posted without a citation `git grep` confirms.
    hits_without_citation: tuple[Hit, ...]
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


class Llm:
    """The OpenAI call for one window. Tests subclass it and override `write`."""

    def __init__(self, api_key: str) -> None:
        self._api_key: str = api_key

    def write(
        self, prompt: str, schema: dict[str, Any], settings: LlmSettings, search: bool
    ) -> tuple[str, Usage]:
        """The JSON answer. With `search`, the model may call `git_grep` first."""
        started = time.monotonic()
        body = structured_request_body(
            prompt, settings.model, schema, settings.reasoning_effort
        )
        if search:
            body["tools"] = [_GREP_TOOL]
        responses = [self._request(body, settings)]
        greps = 0
        while calls := [
            item
            for item in responses[-1].get("output") or []
            if item.get("type") == "function_call"
        ]:
            outputs: list[dict[str, str]] = []
            for call in calls:
                if greps < MAX_GREP_CALLS:
                    arguments = json.loads(call["arguments"])
                    output = git_grep(arguments["pattern"], arguments["path"])
                    greps += 1
                else:
                    output = "Search budget used. Answer now."
                outputs.append(
                    {
                        "type": "function_call_output",
                        "call_id": call["call_id"],
                        "output": output,
                    }
                )
            last_round = len(responses) >= MAX_TOOL_ROUNDS
            responses.append(
                self._request(
                    body
                    | {
                        "previous_response_id": responses[-1]["id"],
                        "input": outputs,
                        "tool_choice": "none" if last_round else "auto",
                    },
                    settings,
                )
            )
        usages = [response.get("usage") or {} for response in responses]
        return extract_output_text(responses[-1]), Usage(
            requests=len(responses),
            input_tokens=sum(int(usage.get("input_tokens", 0)) for usage in usages),
            output_tokens=sum(int(usage.get("output_tokens", 0)) for usage in usages),
            seconds=time.monotonic() - started,
        )

    def _request(self, body: dict[str, Any], settings: LlmSettings) -> dict[str, Any]:
        return api_request("", self._api_key, settings.timeout_seconds, body)


def git_grep(pattern: str, path: str | None) -> str:
    """`git grep -n -I -E` over the checkout, as text for the LLM. Never raises."""
    command = ["git", "-C", str(REPO_ROOT), "grep", "-n", "-I", "-E", "-e", pattern]
    try:
        result = subprocess.run(
            [*command, "--", path or "."],
            capture_output=True,
            text=True,
            timeout=GREP_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return "git grep timed out. Narrow the pattern or the path."
    if result.returncode == 1:
        return "No matches."
    if result.returncode != 0:
        return f"git grep failed: {result.stderr.strip()[:300]}"
    rows = result.stdout.splitlines()
    shown = [row[:MAX_GREP_LINE_CHARS] for row in rows[:MAX_GREP_LINES]]
    if len(rows) > MAX_GREP_LINES:
        shown.append(f"... {len(rows) - MAX_GREP_LINES} more lines")
    return "\n".join(shown)


def _confirmed(citation: Citation) -> bool:
    if len(citation.symbol) < MIN_CITED_SYMBOL_CHARS:
        return False
    try:
        result = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "grep", "-q", "-F", "-e", citation.symbol]
            + ["--", citation.path],
            capture_output=True,
            timeout=GREP_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return False
    return result.returncode == 0


def review(pr: PullRequest, registry: Registry, jev: Jev, llm: Llm) -> Report:
    """Screen the PR with every live and shadow rule, then write live findings.

    Raises when Jev, OpenAI or git fails.
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
    llm_usage = sum((answer.usage for answer in answers), Usage())
    prices = settings.prices
    return Report(
        pr=pr,
        findings=tuple(
            sorted(
                (finding for answer in answers for finding in answer.findings),
                key=lambda finding: (finding.path, finding.line),
            )
        ),
        hits_dropped_by_llm=tuple(hit for a in answers for hit in a.judged_wrong),
        hits_without_citation=tuple(hit for a in answers for hit in a.no_citation),
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


@dataclass(frozen=True)
class _WindowAnswer:
    findings: list[Finding]
    judged_wrong: list[Hit]
    no_citation: list[Hit]
    usage: Usage


def _write_window(
    hits: Sequence[Hit], pr: PullRequest, registry: Registry, llm: Llm
) -> _WindowAnswer:
    window = hits[0].window
    settings = registry.settings
    search = any(hit.rule.needs_repo_search for hit in hits)
    text, usage = llm.write(
        _prompt(window, hits, pr, registry), _schema(window, hits), settings.llm, search
    )
    posted, judged_wrong = parse_answer(text, window, hits)
    rules = {hit.rule.id: hit for hit in hits}
    findings = [
        finding
        for finding in posted
        if not rules[finding.rule_id].rule.needs_repo_search
        or (finding.citation and _confirmed(finding.citation))
    ]
    kept = {finding.rule_id for finding in findings}
    no_citation = [rules[f.rule_id] for f in posted if f.rule_id not in kept]
    return _WindowAnswer(findings, judged_wrong, no_citation, usage)


def parse_answer(
    text: str, window: Window, hits: Sequence[Hit]
) -> tuple[list[Finding], list[Hit]]:
    """Findings the LLM posted, and the hits it judged wrong or left out.

    Raises ValueError on output the schema should have made impossible, such
    as a line outside the window or a rule that was not asked.
    """
    by_rule = {hit.rule.id: hit for hit in hits}
    answered: dict[RuleId, Finding | None] = {}
    for item in json.loads(text)["findings"]:
        rule_id = RuleId(item["rule"])
        if rule_id not in by_rule:
            raise ValueError(f"LLM answered rule {rule_id}, which was not asked")
        if item["line"] not in window.anchor_lines:
            raise ValueError(
                f"LLM pointed {rule_id} at line {item['line']}, outside the window"
            )
        if rule_id in answered:
            continue
        message = item["message"].replace(" — ", "; ").strip()
        symbol = (item.get("cited_symbol") or "").strip()
        path = (item.get("cited_path") or "").strip()
        citation = (
            Citation(symbol, path)
            if by_rule[rule_id].rule.needs_repo_search and symbol and path
            else None
        )
        answered[rule_id] = (
            Finding(rule_id, window.path, item["line"], message, citation)
            if item["post"] is True and message
            else None
        )
    findings = [finding for finding in answered.values() if finding]
    judged_wrong = [hit for hit in hits if answered.get(hit.rule.id) is None]
    return findings, judged_wrong


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

A rule marked "needs repo search" may post only with evidence you found with
the git_grep tool, which searches the repository with this PR applied. Set
"cited_symbol" to the exact text you rely on, such as the existing function
name, and "cited_path" to the file where git_grep found it. Code checks both
and drops the finding when they do not match. For every other rule set both
to null.
"""


def _prompt(
    window: Window, hits: Sequence[Hit], pr: PullRequest, registry: Registry
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
    nullable_string = {"type": ["string", "null"]}
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
                    "required": [
                        "rule",
                        "post",
                        "line",
                        "message",
                        "cited_symbol",
                        "cited_path",
                    ],
                    "properties": {
                        "rule": {"type": "string", "enum": [h.rule.id for h in hits]},
                        "post": {"type": "boolean"},
                        "line": {"type": "integer", "enum": list(window.anchor_lines)},
                        "message": {"type": "string"},
                        "cited_symbol": nullable_string,
                        "cited_path": nullable_string,
                    },
                },
            }
        },
    }


class _GrepParameters(TypedDict):
    type: Literal["object"]
    additionalProperties: Literal[False]
    required: list[str]
    properties: dict[str, object]


class _GrepTool(TypedDict):
    type: Literal["function"]
    name: Literal["git_grep"]
    description: str
    strict: Literal[True]
    parameters: _GrepParameters


_GREP_TOOL: _GrepTool = {
    "type": "function",
    "name": "git_grep",
    "description": (
        "Search the Onyx repository, with this pull request applied, using "
        f"git grep -n -I -E. Returns at most {MAX_GREP_LINES} lines as "
        "path:line:text. Use it to find an existing helper, its callers, or the "
        "module where code like this already lives."
    ),
    "strict": True,
    "parameters": {
        "type": "object",
        "additionalProperties": False,
        "required": ["pattern", "path"],
        "properties": {
            "pattern": {"type": "string", "description": "POSIX extended regex"},
            "path": {
                "type": ["string", "null"],
                "description": "A pathspec such as backend/onyx/utils/, or null for all",
            },
        },
    },
}
