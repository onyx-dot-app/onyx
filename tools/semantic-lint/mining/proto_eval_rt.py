"""Prototype: can Jev separate hunks reviewers commented on from hunks they left alone?

Hunks come from the review-time diff (corpus/review_diffs, compare base...commit_id), so
positives show the code the reviewer actually saw. Samples up to 400 positives and 400
negatives, asks one Jev request per hunk, prints AUC and recall/precision per threshold,
and writes <workdir>/proto_eval_rt_results.jsonl.

Needs `typesafe-sdk` and TYPESAFE_API_KEY. Usage:
    uv run --with typesafe-sdk python3 proto_eval_rt.py [--workdir DIR]"""

import json
import random
import re
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

from common import parse_workdir
from typesafe_sdk import Noul, TypeSafeClient

HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def Q_FACTORY() -> dict:
    return {
        "needs_change": Noul(
            instructions="A senior reviewer on this codebase would ask for a change to the added lines in `hunk`."
        ),
        "error_handling": Noul(
            instructions="The added lines in `hunk` handle, raise, or swallow errors in a way a senior reviewer would ask to change."
        ),
        "typing": Noul(
            instructions="The added lines in `hunk` use types in a way a senior reviewer would ask to change, such as Any, an Optional that should not be optional, a cast, or a truthiness check on a value where 0 or empty is valid."
        ),
        "dead_code_duplication": Noul(
            instructions="The added lines in `hunk` duplicate logic that exists elsewhere in the hunk, leave unused code, or add a wrapper that should be inlined."
        ),
        "naming_readability": Noul(
            instructions="The added lines in `hunk` contain a name, comment, or message a senior reviewer would ask to reword."
        ),
    }


def auc(scores_pos: list[float], scores_neg: list[float]) -> float:
    wins = sum(1 for p in scores_pos for n in scores_neg if p > n) + 0.5 * sum(
        1 for p in scores_pos for n in scores_neg if p == n
    )
    return wins / (len(scores_pos) * len(scores_neg))


def split_patch(path: str, patch: str) -> list[dict]:
    hunks, cur = [], None
    for line in patch.splitlines():
        m = HUNK_RE.match(line)
        if m:
            cur = {
                "path": path,
                "new_start": int(m.group(3)),
                "new_len": int(m.group(4) or 1),
                "lines": [line],
            }
            hunks.append(cur)
        elif cur is not None:
            cur["lines"].append(line)
    for h in hunks:
        h["text"] = "\n".join(h["lines"])
    return hunks


def main() -> None:
    workdir = parse_workdir(__doc__)
    corpus = workdir / "corpus"
    threads = [json.loads(line) for line in (corpus / "threads_screened.jsonl").open()]
    raw = {
        c["id"]: c
        for c in (json.loads(line) for line in (corpus / "pull_comments.jsonl").open())
    }
    commented = defaultdict(set)
    for c in raw.values():
        if c["path"] and c["original_line"]:
            commented[(c["pr"], c["commit_id"], c["path"])].add(c["original_line"])
    random.seed(5)
    pos, neg = [], []
    groups = defaultdict(list)
    for t in threads:
        c = raw[t["id"]]
        groups[(t["pr"], c["commit_id"])].append((t, c))
    for (pr, sha), items in groups.items():
        p = corpus / "review_diffs" / f"{pr}_{sha}.json"
        if not p.exists():
            continue
        files = json.loads(p.read_text())["files"]
        touched = {t["path"] for t, _ in items}
        for f in files:
            if not f.get("patch") or not f["filename"].endswith((".py", ".ts", ".tsx")):
                continue
            for h in split_patch(f["filename"], f["patch"]):
                lo, hi = h["new_start"], h["new_start"] + h["new_len"]
                hits = [
                    t
                    for t, c in items
                    if t["path"] == h["path"]
                    and c["original_line"]
                    and lo <= c["original_line"] < hi
                    and t["jev"]["actionable"] >= 0.8
                    and t["jev"]["category"]
                    not in ("question_or_discussion", "praise_or_ack", "other")
                ]
                any_comment = any(
                    lo <= ln < hi for ln in commented.get((pr, sha, h["path"]), ())
                )
                if hits and len(h["text"]) < 4000:
                    pos.append(
                        {
                            "pr": pr,
                            "hunk": h,
                            "cat": hits[0]["jev"]["category"],
                            "thread": hits[0]["id"],
                        }
                    )
                elif (
                    not any_comment
                    and h["path"] in touched
                    and 200 < len(h["text"]) < 4000
                ):
                    neg.append({"pr": pr, "hunk": h, "cat": None, "thread": None})
    random.shuffle(pos)
    random.shuffle(neg)
    pos, neg = pos[:400], neg[:400]
    print(f"positives {len(pos)} negatives {len(neg)}", file=sys.stderr)
    Q = Q_FACTORY()

    def ask(client: TypeSafeClient, item: dict) -> dict:
        st = {"file": item["hunk"]["path"], "hunk": item["hunk"]["text"]}
        for a in range(5):
            try:
                r = client.system_one(state=st, questions=Q)
                break
            except Exception:
                if a == 4:
                    raise
                time.sleep(2**a)
        item["ans"] = {k: r.nouls[k].noul for k in Q}
        item["tok"] = r.usage.input_tokens
        return item

    t0 = time.perf_counter()
    with (
        TypeSafeClient(model="jev-latest") as client,
        ThreadPoolExecutor(max_workers=8) as pool,
    ):
        items = list(pool.map(lambda it: ask(client, it), pos + neg))
    tok = sum(i["tok"] for i in items)
    print(
        f"{len(items)} hunks in {time.perf_counter() - t0:.0f}s, {tok} tokens ${tok / 1e6 * 0.042:.3f}",
        file=sys.stderr,
    )
    P = [i for i in items if i["cat"]]
    N = [i for i in items if not i["cat"]]
    print(
        f"\nGeneric 'needs_change': AUC={auc([i['ans']['needs_change'] for i in P], [i['ans']['needs_change'] for i in N]):.3f}"
    )
    for th in (0.3, 0.5, 0.7):
        tp = sum(1 for i in P if i["ans"]["needs_change"] >= th)
        fp = sum(1 for i in N if i["ans"]["needs_change"] >= th)
        print(
            f"  th={th}: recall={tp / len(P):.2f} precision={tp / (tp + fp) if tp + fp else 0:.2f} fp_rate={fp / len(N):.2f}"
        )
    for cat in (
        "error_handling",
        "typing",
        "dead_code_duplication",
        "naming_readability",
    ):
        Pc = [i for i in P if i["cat"] == cat]
        if len(Pc) < 8:
            continue
        a = auc([i["ans"][cat] for i in Pc], [i["ans"][cat] for i in N])
        best = max(
            (
                (
                    th,
                    sum(1 for i in Pc if i["ans"][cat] >= th) / len(Pc),
                    sum(1 for i in N if i["ans"][cat] >= th) / len(N),
                )
                for th in (0.3, 0.4, 0.5, 0.6, 0.7)
            ),
            key=lambda x: x[1] - x[2],
        )
        print(
            f"{cat:24s} n={len(Pc):3d} AUC vs uncommented={a:.3f}  best th={best[0]} recall={best[1]:.2f} fp_rate={best[2]:.2f}"
        )
    (workdir / "proto_eval_rt_results.jsonl").write_text(
        "\n".join(
            json.dumps(
                {
                    "pr": i["pr"],
                    "path": i["hunk"]["path"],
                    "cat": i["cat"],
                    "thread": i["thread"],
                    "ans": i["ans"],
                }
            )
            for i in items
        )
    )


if __name__ == "__main__":
    main()
