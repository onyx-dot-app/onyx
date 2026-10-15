"""Screen every reviewer thread with Jev: category, actionability, generality, severity.

Reads corpus/threads.jsonl, writes corpus/threads_screened.jsonl (same rows plus a
`jev` field). Rerunnable: rows already screened are skipped. Set REORDER=1 to run the
category Choice with reversed option order into `jev.category_rev` for an order-bias
check.

Needs `typesafe-sdk` and TYPESAFE_API_KEY. Usage:
    uv run --with typesafe-sdk python3 screen_threads.py [--workdir DIR]"""

import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

from common import parse_workdir
from typesafe_sdk import Choice, Noul, Score, TypeSafeClient

REORDER = os.environ.get("REORDER") == "1"

CATEGORIES = {
    "error_handling": "How errors and exceptions are raised, caught, propagated, or surfaced; failing loudly vs silently",
    "typing": "Type annotations, Optional/None handling, casts, type narrowing, Pydantic models, mypy/ty complaints",
    "naming_readability": "Names, comments, docstrings, formatting, indentation, clarity of a small piece of code",
    "dead_code_duplication": "Unused code, duplicated logic, asking to combine, dedupe, inline, or delete something",
    "control_flow_structure": "Function length, nesting, early returns, recursion vs iteration, where logic lives inside a function",
    "tests": "Missing tests, test coverage, test quality, flaky tests, test data",
    "db_and_migrations": "SQLAlchemy queries, sessions, transactions, alembic migrations, indexes, N+1, schema design",
    "concurrency_performance": "Blocking calls, loops over large data, memory, caching, timeouts, Celery tasks, async, latency",
    "config_and_env": "Environment variables, constants, settings, feature flags, defaults",
    "api_contract": "Route paths, request/response models, backwards compatibility, public API, HTTP status codes",
    "deployment_multitenant": "Helm, docker, nginx, k8s, multi-tenant isolation, lite deployment, infra",
    "frontend_standards": "React components, hooks, SWR, styling, Opal/refresh components, Next.js, TypeScript on the web side",
    "security_auth": "Permissions, RBAC, auth, secrets, injection, input validation at trust boundaries",
    "logging_observability": "Log levels, log content, tracing, metrics, leftover debug output",
    "architecture_boundaries": "Module placement, layering, abstraction, interfaces, coupling, where code should live",
    "llm_and_prompts": "LLM calls, prompt text, model config, tool calling, agent loops, tracing flows for LLM calls",
    "connectors_and_indexing": "Connector pagination, rate limits, checkpointing, document indexing, search retrieval",
    "process_and_scope": "PR scope, splitting PRs, commit hygiene, TODOs, follow-ups, docs, feature map",
    "question_or_discussion": "The reviewer asks a question or discusses without asking for a change",
    "praise_or_ack": "Praise, acknowledgement, or a joke with no request",
    "other": "None of the above",
}

QUESTIONS = {
    "category": Choice(
        instructions="What is the main topic of the reviewer's comment `comment` about the code in `hunk`?",
        criteria=CATEGORIES,
    ),
    "actionable": Noul(
        instructions="The reviewer's `comment` asks the author to change the code or add something, explicitly or implicitly."
    ),
    "generalizable": Noul(
        instructions=(
            "The reviewer's `comment` expresses a rule or preference that would apply to other pull requests "
            "in this codebase, not only to this specific line."
        ),
        criteria={
            "true": {
                "what": "A reusable engineering rule, convention, or recurring concern",
                "examples": [
                    "we never raise HTTPException directly, use OnyxError",
                    "this should be a constant, not an env var",
                    "make this iterative so large inputs don't blow the stack",
                ],
            },
            "false": {
                "what": "Specific to this line, a typo, a question, or a one-off fact",
                "examples": ["typo", "is this still used?", "nit: rename x to y"],
            },
        },
    ),
    "severity": Score(
        instructions="How strongly does the reviewer want this changed before merge?",
        criteria=[
            "No change requested (question, praise, or discussion)",
            "Optional nit or suggestion",
            "Should fix, reviewer expects a change",
            "Must fix, blocks merge or is a bug",
        ],
    ),
}
QUESTIONS_REV = dict(QUESTIONS)
QUESTIONS_REV["category_rev"] = Choice(
    instructions=QUESTIONS["category"].instructions,
    criteria=dict(reversed(list(CATEGORIES.items()))),
)


def state_for(t: dict) -> dict:
    hunk = t["diff_hunk"] or ""
    if len(hunk) > 3000:
        hunk = "...\n" + hunk[-3000:]
    return {
        "reviewer": t["reviewer"],
        "file": t["path"],
        "hunk": hunk,
        "comment": t["body"][:2000],
        "replies": [
            {"author": r["author"], "text": r["body"][:500]} for r in t["replies"][:3]
        ],
    }


def screen(client: TypeSafeClient, t: dict) -> dict:
    qs = QUESTIONS_REV if REORDER else QUESTIONS
    for attempt in range(5):
        try:
            r = client.system_one(state=state_for(t), questions=qs)
            break
        except Exception:
            if attempt == 4:
                raise
            time.sleep(2**attempt)
    cat = r.choices["category"]
    out = {
        "category": cat.choice,
        "category_conf": round(cat.confidence, 3),
        "category_probs": {
            k: round(v, 3) for k, v in cat.probabilities.items() if v >= 0.05
        },
        "actionable": round(r.nouls["actionable"].noul, 3),
        "generalizable": round(r.nouls["generalizable"].noul, 3),
        "severity": round(r.scores["severity"].score, 2),
        "severity_conf": round(r.scores["severity"].confidence, 3),
        "input_tokens": r.usage.input_tokens,
    }
    if REORDER:
        out["category_rev"] = r.choices["category_rev"].choice
    return out


def main() -> None:
    corpus = parse_workdir(__doc__) / "corpus"
    src = corpus / "threads.jsonl"
    dst = corpus / "threads_screened.jsonl"
    done: dict[int, dict] = {}
    if dst.exists():
        for line in dst.open():
            row = json.loads(line)
            done[row["id"]] = row
    threads = [json.loads(line) for line in src.open()]
    todo = [
        t
        for t in threads
        if t["id"] not in done
        or (REORDER and "category_rev" not in done[t["id"]]["jev"])
    ]
    print(f"{len(threads)} threads, {len(todo)} to screen", file=sys.stderr)
    t0 = time.perf_counter()
    tokens = 0
    with (
        TypeSafeClient(model="jev-latest") as client,
        ThreadPoolExecutor(max_workers=8) as pool,
    ):
        results = list(pool.map(lambda t: (t, screen(client, t)), todo))
    for t, jev in results:
        tokens += jev["input_tokens"]
        t["jev"] = jev
        done[t["id"]] = t
    with dst.open("w") as f:
        for t in sorted(done.values(), key=lambda x: x["created_at"]):
            f.write(json.dumps(t) + "\n")
    dt = time.perf_counter() - t0
    print(
        f"screened {len(todo)} in {dt:.0f}s, {tokens} input tokens, ${tokens / 1e6 * 0.042:.3f}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
