"""Prototype: does window size change how well Jev separates commented from uncommented code?

Same review-time positives/negatives as proto_eval_rt.py, but each hunk is cut to a window
around the anchor (positives) or the hunk start (negatives) at several sizes. Reports AUC
per size for the generic and category nouls. Samples up to 300 positives and 300
negatives and sends one Jev request per hunk and size.

Needs `typesafe-sdk` and TYPESAFE_API_KEY. Usage:
    uv run --with typesafe-sdk python3 proto_window.py [--workdir DIR]"""

import json
import random
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

from common import parse_workdir
from proto_eval_rt import Q_FACTORY, auc, split_patch  # noqa: E402
from typesafe_sdk import TypeSafeClient

SIZES = (12, 24, 40, 10_000)


def window(h: dict, anchor_new_line: int | None, size: int) -> str:
    """Lines of the hunk ending at the anchor (or the first `size` lines), at most `size` long."""
    body = h["lines"][1:]
    if anchor_new_line is None:
        return "\n".join(body[:size])
    new = h["new_start"] - 1
    idx = None
    for i, ln in enumerate(body):
        if not ln.startswith("-"):
            new += 1
        if new == anchor_new_line and not ln.startswith("-"):
            idx = i
            break
    if idx is None:
        return "\n".join(body[:size])
    lo = max(0, idx + 1 - size)
    return "\n".join(body[lo : idx + 1])


def ask(
    client: TypeSafeClient, questions: dict, item: dict, size: int
) -> tuple[dict, int]:
    st = {
        "file": item["hunk"]["path"],
        "hunk": window(item["hunk"], item["anchor"], size),
    }
    for a in range(5):
        try:
            r = client.system_one(state=st, questions=questions)
            break
        except Exception:
            if a == 4:
                raise
            time.sleep(2**a)
    return {k: r.nouls[k].noul for k in questions}, r.usage.input_tokens


def main() -> None:
    corpus = parse_workdir(__doc__) / "corpus"
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
    groups = defaultdict(list)
    for t in threads:
        groups[(t["pr"], raw[t["id"]]["commit_id"])].append((t, raw[t["id"]]))
    pos, neg = [], []
    for (pr, sha), items in groups.items():
        p = corpus / "review_diffs" / f"{pr}_{sha}.json"
        if not p.exists():
            continue
        touched = {t["path"] for t, _ in items}
        for f in json.loads(p.read_text())["files"]:
            if not f.get("patch") or not f["filename"].endswith((".py", ".ts", ".tsx")):
                continue
            for h in split_patch(f["filename"], f["patch"]):
                lo, hi = h["new_start"], h["new_start"] + h["new_len"]
                hits = [
                    (t, c)
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
                if hits and len(h["text"]) < 8000:
                    pos.append(
                        {
                            "hunk": h,
                            "anchor": hits[0][1]["original_line"],
                            "cat": hits[0][0]["jev"]["category"],
                        }
                    )
                elif (
                    not any_comment
                    and h["path"] in touched
                    and 300 < len(h["text"]) < 8000
                ):
                    new = h["new_start"] - 1
                    added = []
                    for ln in h["lines"][1:]:
                        if not ln.startswith("-"):
                            new += 1
                        if ln.startswith("+"):
                            added.append(new)
                    if added:
                        neg.append(
                            {"hunk": h, "anchor": random.choice(added), "cat": None}
                        )
    random.shuffle(pos)
    random.shuffle(neg)
    pos, neg = pos[:300], neg[:300]
    print(f"positives {len(pos)} negatives {len(neg)}", file=sys.stderr)
    Q = Q_FACTORY()

    with (
        TypeSafeClient(model="jev-latest") as client,
        ThreadPoolExecutor(max_workers=8) as pool,
    ):
        for size in SIZES:
            t0 = time.perf_counter()
            res = list(
                pool.map(lambda it, size=size: ask(client, Q, it, size), pos + neg)
            )
            tok = sum(t for _, t in res)
            P = [a for a, _ in res[: len(pos)]]
            N = [a for a, _ in res[len(pos) :]]
            g = auc([a["needs_change"] for a in P], [a["needs_change"] for a in N])
            cats = []
            for cat in (
                "error_handling",
                "typing",
                "dead_code_duplication",
                "naming_readability",
            ):
                Pc = [a for a, it in zip(P, pos, strict=True) if it["cat"] == cat]
                if len(Pc) >= 8:
                    cats.append(
                        f"{cat[:8]}={auc([a[cat] for a in Pc], [a[cat] for a in N]):.3f}(n={len(Pc)})"
                    )
            print(
                f"size={size:>5}: generic AUC={g:.3f}  {'  '.join(cats)}  tokens/item={tok / len(res):.0f}  {time.perf_counter() - t0:.0f}s"
            )


if __name__ == "__main__":
    main()
