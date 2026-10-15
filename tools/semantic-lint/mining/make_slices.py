"""Partition screened reviewer threads into swarm slices by Jev category.

Reads corpus/threads_screened.jsonl and corpus/pull_comments.jsonl. Writes
swarm/slices/<slice>.jsonl (full rows) and <slice>.md (compact, for reading), plus
INDEX.json. Also builds the bot_pushback slice: reviewer replies inside threads
whose root comment came from an AI reviewer bot.

Usage: make_slices.py [--workdir DIR]"""

import json
from collections import Counter
from pathlib import Path

from common import BOTS, REVIEWERS, parse_workdir

SLICES = {
    "naming-readability-a": ["naming_readability"],
    "naming-readability-b": ["naming_readability"],
    "dead-code-duplication-a": ["dead_code_duplication"],
    "dead-code-duplication-b": ["dead_code_duplication"],
    "typing": ["typing"],
    "control-flow": ["control_flow_structure"],
    "architecture": ["architecture_boundaries"],
    "config-env": ["config_and_env"],
    "errors-logging": ["error_handling", "logging_observability"],
    "db-perf": ["db_and_migrations", "concurrency_performance"],
    "connectors-llm": ["connectors_and_indexing", "llm_and_prompts"],
    "security-api-deploy": ["security_auth", "api_contract", "deployment_multitenant"],
    "frontend-tests-process": ["frontend_standards", "tests", "process_and_scope"],
    "questions-other": ["question_or_discussion", "other", "praise_or_ack"],
}
SPLIT = {"naming-readability": 2, "dead-code-duplication": 2}


def compact(t: dict) -> str:
    hunk_lines = (t["diff_hunk"] or "").splitlines()
    tail = "\n".join(hunk_lines[-12:])
    j = t["jev"]
    merged = "merged" if t.get("pr_merged") else "unmerged"
    head = (
        f"### t{t['id']} | {t['reviewer']} | PR #{t['pr']} ({merged}) | "
        f"{t['path']}:L{t['line']} | resolved={t['resolved']} | "
        f"jev: {j['category']} act={j['actionable']} gen={j['generalizable']} sev={j['severity']}"
    )
    body = t["body"].strip()[:800].replace("\n", "\n> ")
    parts = [head, "```", tail, "```", f"> {body}"]
    parts.extend(
        f">> {r['author']}: {r['body'].strip()[:300].replace(chr(10), ' ')}"
        for r in t["replies"][:3]
    )
    return "\n".join(parts) + "\n"


def write_slice(out: Path, name: str, rows: list[dict], title: str) -> None:
    with (out / f"{name}.jsonl").open("w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    with (out / f"{name}.md").open("w") as f:
        f.write(
            f"# Slice {name}: {title}\n\n{len(rows)} threads. Full rows in {name}.jsonl.\n\n"
        )
        for r in rows:
            f.write(compact(r) + "\n")


def main() -> None:
    workdir = parse_workdir(__doc__)
    corpus = workdir / "corpus"
    out = workdir / "swarm" / "slices"
    out.mkdir(parents=True, exist_ok=True)
    rows = [json.loads(line) for line in (corpus / "threads_screened.jsonl").open()]
    by_cat: dict[str, list[dict]] = {}
    for r in rows:
        by_cat.setdefault(r["jev"]["category"], []).append(r)
    index = {}
    for name, cats in SLICES.items():
        base = name[:-2] if name[-2:] in ("-a", "-b") else name
        pool = [r for c in cats for r in by_cat.get(c, [])]
        pool.sort(key=lambda r: r["id"])
        if base in SPLIT:
            half = len(pool) // 2
            pool = pool[:half] if name.endswith("-a") else pool[half:]
        write_slice(out, name, pool, ", ".join(cats))
        index[name] = {
            "categories": cats,
            "rows": len(pool),
            "reviewers": dict(Counter(r["reviewer"] for r in pool)),
        }

    comments = [json.loads(line) for line in (corpus / "pull_comments.jsonl").open()]
    by_id = {c["id"]: c for c in comments}
    pushback = []
    for c in comments:
        if c["author"] not in REVIEWERS or c["in_reply_to_id"] is None:
            continue
        root = by_id.get(c["in_reply_to_id"])
        if root is None or not BOTS.search(root["author"] or ""):
            continue
        pushback.append(
            {
                "id": c["id"],
                "pr": c["pr"],
                "reviewer": c["author"],
                "path": root["path"],
                "line": root["line"] or root["original_line"],
                "diff_hunk": root["diff_hunk"],
                "bot": root["author"],
                "bot_comment": root["body"],
                "body": c["body"],
                "created_at": c["created_at"],
                "html_url": c["html_url"],
                "replies": [],
                "resolved": None,
                "jev": {
                    "category": "bot_pushback",
                    "actionable": None,
                    "generalizable": None,
                    "severity": None,
                },
            }
        )
    pushback.sort(key=lambda r: r["id"])
    with (out / "bot-pushback.jsonl").open("w") as f:
        for r in pushback:
            f.write(json.dumps(r) + "\n")
    with (out / "bot-pushback.md").open("w") as f:
        f.write(
            f"# Slice bot-pushback: reviewer replies to AI reviewer bot comments\n\n{len(pushback)} replies.\n\n"
        )
        for r in pushback:
            tail = "\n".join((r["diff_hunk"] or "").splitlines()[-12:])
            bot = r["bot_comment"].strip()[:700].replace("\n", "\n> ")
            f.write(
                f"### t{r['id']} | {r['reviewer']} replying to {r['bot']} | PR #{r['pr']} | {r['path']}:L{r['line']}\n"
                f"```\n{tail}\n```\n> BOT: {bot}\n>> {r['reviewer']}: {r['body'].strip()[:600].replace(chr(10), ' ')}\n\n"
            )
    index["bot-pushback"] = {
        "categories": ["bot_pushback"],
        "rows": len(pushback),
        "reviewers": dict(Counter(r["reviewer"] for r in pushback)),
    }
    (out / "INDEX.json").write_text(json.dumps(index, indent=2))
    for k, v in index.items():
        print(f"{k:26s} rows={v['rows']:4d} {v['reviewers']}")


if __name__ == "__main__":
    main()
