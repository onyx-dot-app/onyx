"""Scored regression eval for the source-scope filter extraction prompt.

Runs every eval question in `scope_eval_cases.py` directly through
`decide_search_scope` (real LLM, no agent loop) and fails if the pass rate
drops below the threshold. This is the CI gate for changes to
`onyx/prompts/filter_extration.py` — see the workflow
`.github/workflows/pr-connector-filter-eval.yml`, which runs this file only
when the prompt (or the flow around it) changes.

LLM output varies between runs, so the gate is a scored dataset rather than
per-case hard asserts: each case gets a retry, and the suite passes on an
aggregate threshold. A systematic prompt regression flips its cases on every
attempt and sinks the score; a one-off wobble does not.

Scoring normalizes a scope that covers every connected source to "unscoped" —
filtering to all sources retrieves exactly what no filter does, so the two
answers are behaviorally identical.

Knobs (env vars):
- CONNECTOR_FILTER_EVAL_THRESHOLD: minimum pass rate in [0, 1] (default 0.85).
- CONNECTOR_FILTER_EVAL_ATTEMPTS: attempts per case; a case passes if any
  attempt returns the expected scope (default 2).
"""

from __future__ import annotations

import os
from collections import defaultdict

from pydantic import BaseModel

from onyx.configs.constants import DocumentSource
from onyx.configs.constants import MessageType
from onyx.llm.interfaces import LLM
from onyx.secondary_llm_flows.source_filter import decide_search_scope
from onyx.tools.models import ChatMinimalTextMessage
from onyx.utils.threadpool_concurrency import run_functions_tuples_in_parallel
from tests.external_dependency_unit.connector_filter_eval.scope_eval_cases import (
    SCOPE_EVAL_CASES,
)
from tests.external_dependency_unit.connector_filter_eval.scope_eval_cases import (
    ScopeEvalCase,
)

_PASS_RATE_THRESHOLD = float(os.environ.get("CONNECTOR_FILTER_EVAL_THRESHOLD", "0.85"))
_ATTEMPTS_PER_CASE = int(os.environ.get("CONNECTOR_FILTER_EVAL_ATTEMPTS", "2"))
_MAX_WORKERS = 4


class _CaseOutcome(BaseModel):
    case: ScopeEvalCase
    passed: bool
    # The scope each attempt returned, in order (stops at the first pass).
    attempts: list[set[DocumentSource] | None]


def _scope_str(scope: set[DocumentSource] | None) -> str:
    if scope is None:
        return "ALL"
    return "{" + ",".join(sorted(s.value for s in scope)) + "}"


def _normalize(
    scope: set[DocumentSource] | None, connected: list[DocumentSource]
) -> set[DocumentSource] | None:
    """A scope covering every connected source retrieves the same documents as
    no scope at all — grade the two as equivalent."""
    if scope is not None and scope >= set(connected):
        return None
    return scope


def _run_case(case: ScopeEvalCase, llm: LLM) -> _CaseOutcome:
    history = [
        ChatMinimalTextMessage(message=turn, message_type=MessageType.USER)
        for turn in case.user_turns
    ]
    expected = _normalize(case.expected, case.connected_sources)
    attempts: list[set[DocumentSource] | None] = []
    for _ in range(_ATTEMPTS_PER_CASE):
        scope = decide_search_scope(
            history,
            llm,
            list(case.connected_sources),
            list(case.previous_cycles),
            list(case.current_queries),
        )
        got = set(scope) if scope is not None else None
        attempts.append(got)
        if _normalize(got, case.connected_sources) == expected:
            return _CaseOutcome(case=case, passed=True, attempts=attempts)
    return _CaseOutcome(case=case, passed=False, attempts=attempts)


def _report(outcomes: list[_CaseOutcome]) -> str:
    lines = ["=== filter-extraction regression eval ==="]
    by_category: dict[str, list[_CaseOutcome]] = defaultdict(list)
    for outcome in outcomes:
        by_category[outcome.case.category].append(outcome)
        status = "PASS" if outcome.passed else "FAIL"
        got = " | ".join(_scope_str(a) for a in outcome.attempts)
        lines.append(
            f"[{status}] {outcome.case.category}/{outcome.case.name}: "
            f"expected={_scope_str(outcome.case.expected)} got={got}"
        )
    passed = sum(o.passed for o in outcomes)
    lines.append(
        f"pass rate: {passed}/{len(outcomes)} "
        f"({passed / len(outcomes):.1%}), threshold {_PASS_RATE_THRESHOLD:.0%}"
    )
    lines.append(
        "per category: "
        + ", ".join(
            f"{category} {sum(o.passed for o in group)}/{len(group)}"
            for category, group in sorted(by_category.items())
        )
    )
    return "\n".join(lines)


def test_filter_extraction_no_regression(eval_llm: LLM) -> None:
    outcomes: list[_CaseOutcome] = run_functions_tuples_in_parallel(
        [(_run_case, (case, eval_llm)) for case in SCOPE_EVAL_CASES],
        max_workers=_MAX_WORKERS,
    )

    report = _report(outcomes)
    print("\n" + report)

    failed = [o for o in outcomes if not o.passed]
    pass_rate = (len(outcomes) - len(failed)) / len(outcomes)
    assert pass_rate >= _PASS_RATE_THRESHOLD, (
        f"filter extraction regressed: pass rate {pass_rate:.1%} is below the "
        f"{_PASS_RATE_THRESHOLD:.0%} threshold "
        f"({len(failed)}/{len(outcomes)} cases failed)\n{report}"
    )
