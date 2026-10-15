"""Join the raw comment dumps into reviewer-authored threads.

Inputs (in <workdir>/corpus): pull_comments.jsonl, issue_comments.jsonl,
pr_meta.jsonl, thread_state.jsonl. Outputs: threads.jsonl (one row per inline thread
whose root is by a target reviewer), pr_comments.jsonl (top-level PR comments by a
target reviewer), stats.json.

Usage: build_threads.py [--workdir DIR]"""

import json
from collections import Counter, defaultdict
from pathlib import Path

from common import BOTS, REVIEWERS, parse_workdir


def load(corpus: Path, name: str) -> list[dict]:
    p = corpus / name
    if not p.exists():
        return []
    return [json.loads(line) for line in p.open() if line.strip()]


def main() -> None:
    corpus = parse_workdir(__doc__) / "corpus"
    comments = load(corpus, "pull_comments.jsonl")
    replies: dict[int, list[dict]] = defaultdict(list)
    for c in comments:
        if c["in_reply_to_id"] is not None:
            replies[c["in_reply_to_id"]].append(c)
    meta = {m["number"]: m for m in load(corpus, "pr_meta.jsonl")}
    state = {s["root_id"]: s for s in load(corpus, "thread_state.jsonl")}

    threads = []
    for c in comments:
        if c["in_reply_to_id"] is not None or c["author"] not in REVIEWERS:
            continue
        m = meta.get(c["pr"], {})
        reps = sorted(replies.get(c["id"], []), key=lambda r: r["created_at"])
        st = state.get(c["id"], {})
        threads.append(
            {
                "id": c["id"],
                "pr": c["pr"],
                "pr_title": m.get("title"),
                "pr_author": m.get("author"),
                "pr_merged": m.get("merged"),
                "pr_size": (m.get("additions") or 0) + (m.get("deletions") or 0),
                "reviewer": c["author"],
                "path": c["path"],
                "line": c["line"] or c["original_line"],
                "diff_hunk": c["diff_hunk"],
                "body": c["body"],
                "created_at": c["created_at"],
                "html_url": c["html_url"],
                "resolved": st.get("resolved"),
                "outdated": st.get("outdated"),
                "replies": [
                    {
                        "author": r["author"],
                        "body": r["body"],
                        "created_at": r["created_at"],
                    }
                    for r in reps
                ],
            }
        )
    threads.sort(key=lambda t: t["created_at"])
    with (corpus / "threads.jsonl").open("w") as f:
        for t in threads:
            f.write(json.dumps(t) + "\n")

    pr_comments = [
        c
        for c in load(corpus, "issue_comments.jsonl")
        if c["is_pr"] and c["author"] in REVIEWERS
    ]
    with (corpus / "pr_comments.jsonl").open("w") as f:
        for c in pr_comments:
            m = meta.get(c["issue"], {})
            c["pr_title"] = m.get("title")
            c["pr_author"] = m.get("author")
            f.write(json.dumps(c) + "\n")

    top_dirs = Counter()
    for t in threads:
        parts = (t["path"] or "").split("/")
        top_dirs["/".join(parts[:2])] += 1
    stats = {
        "pull_comments_total": len(comments),
        "threads_by_reviewer": dict(Counter(t["reviewer"] for t in threads)),
        "threads_by_year": dict(
            sorted(Counter(t["created_at"][:4] for t in threads).items())
        ),
        "threads_resolved": dict(Counter(str(t["resolved"]) for t in threads)),
        "threads_with_author_reply": sum(
            1
            for t in threads
            if any(r["author"] == t["pr_author"] for r in t["replies"])
        ),
        "pr_comments_by_reviewer": dict(Counter(c["author"] for c in pr_comments)),
        "top_dirs": top_dirs.most_common(25),
        "distinct_prs": len({t["pr"] for t in threads}),
        "bot_comments_total": sum(
            1 for c in comments if BOTS.search(c["author"] or "")
        ),
    }
    (corpus / "stats.json").write_text(json.dumps(stats, indent=2))
    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
