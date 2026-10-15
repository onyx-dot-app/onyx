"""Screen reviewer replies to bot comments: keep the ones that dismiss or correct the bot.

Reads swarm/slices/bot-pushback.jsonl (from make_slices.py) and writes the kept replies
to swarm/slices/bot-pushback-a and -b (.jsonl and .md).

Needs `typesafe-sdk` and TYPESAFE_API_KEY. Usage:
    uv run --with typesafe-sdk python3 screen_pushback.py [--workdir DIR]"""

import json
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

from common import parse_workdir
from typesafe_sdk import Choice, Noul, TypeSafeClient

QUESTIONS = {
    "stance": Choice(
        instructions="How does the human reviewer's `reply` respond to the AI bot's `bot_comment` about the `hunk`?",
        criteria={
            "accepts_and_fixes": "Agrees and says it was or will be fixed, e.g. 'done', 'fixed', 'good catch'",
            "dismisses_with_reason": "Disagrees and gives a reason the finding is wrong, not applicable, or not worth doing",
            "dismisses_without_reason": "Dismisses or defers without a stated reason, e.g. 'not needed', 'leaving as is', 'out of scope'",
            "asks_or_discusses": "Asks a question or discusses without accepting or dismissing",
            "unrelated": "Not a response to the bot's finding",
        },
    ),
    "states_rule": Noul(
        instructions="The human reviewer's `reply` states a general reason or convention about this codebase that explains why the bot's finding does not apply."
    ),
}


def state_for(r: dict) -> dict:
    hunk = r["diff_hunk"] or ""
    return {
        "hunk": hunk[-2500:],
        "bot_comment": r["bot_comment"][:1500],
        "reply": r["body"][:1200],
    }


def one(client: TypeSafeClient, r: dict) -> dict:
    for attempt in range(5):
        try:
            res = client.system_one(state=state_for(r), questions=QUESTIONS)
            break
        except Exception:
            if attempt == 4:
                raise
            time.sleep(2**attempt)
    c = res.choices["stance"]
    r["jev"] = {
        "category": "bot_pushback",
        "stance": c.choice,
        "stance_conf": round(c.confidence, 3),
        "states_rule": round(res.nouls["states_rule"].noul, 3),
        "input_tokens": res.usage.input_tokens,
    }
    return r


def main() -> None:
    slices = parse_workdir(__doc__) / "swarm" / "slices"
    rows = [json.loads(line) for line in (slices / "bot-pushback.jsonl").open()]
    t0 = time.perf_counter()
    with (
        TypeSafeClient(model="jev-latest") as client,
        ThreadPoolExecutor(max_workers=8) as pool,
    ):
        rows = list(pool.map(lambda r: one(client, r), rows))
    tokens = sum(r["jev"]["input_tokens"] for r in rows)
    print(Counter(r["jev"]["stance"] for r in rows), file=sys.stderr)
    keep = [
        r
        for r in rows
        if r["jev"]["stance"].startswith("dismisses") or r["jev"]["states_rule"] >= 0.5
    ]
    keep.sort(key=lambda r: r["id"])
    print(
        f"kept {len(keep)} of {len(rows)}; {time.perf_counter() - t0:.0f}s, {tokens} tokens ${tokens / 1e6 * 0.042:.3f}",
        file=sys.stderr,
    )
    half = (len(keep) + 1) // 2
    for name, part in (
        ("bot-pushback-a", keep[:half]),
        ("bot-pushback-b", keep[half:]),
    ):
        with (slices / f"{name}.jsonl").open("w") as f:
            for r in part:
                f.write(json.dumps(r) + "\n")
        with (slices / f"{name}.md").open("w") as f:
            f.write(
                f"# Slice {name}: reviewer replies that dismiss or correct AI reviewer bot findings\n\n{len(part)} replies. Full rows in {name}.jsonl.\n\n"
            )
            for r in part:
                tail = "\n".join((r["diff_hunk"] or "").splitlines()[-12:])
                bot = r["bot_comment"].strip()[:700].replace("\n", "\n> ")
                j = r["jev"]
                f.write(
                    f"### t{r['id']} | {r['reviewer']} replying to {r['bot']} | PR #{r['pr']} | {r['path']}:L{r['line']} | jev: {j['stance']} states_rule={j['states_rule']}\n"
                    f"```\n{tail}\n```\n> BOT: {bot}\n>> {r['reviewer']}: {r['body'].strip()[:600].replace(chr(10), ' ')}\n\n"
                )
        print(f"{name}: {len(part)} rows", file=sys.stderr)


if __name__ == "__main__":
    main()
