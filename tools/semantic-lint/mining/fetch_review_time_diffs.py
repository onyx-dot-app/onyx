"""Fetch the PR diff as it stood when each reviewer comment was made.

For every distinct (pr, commit_id) among reviewer threads, GET compare/<base_oid>...<commit_id>
and store files[].{filename, patch} in corpus/review_diffs/<pr>_<sha>.json. Base oids
come from GraphQL. Rerunnable: existing files are skipped.

Usage: fetch_review_time_diffs.py [--workdir DIR]. Needs an authenticated `gh`."""

import json
import subprocess
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from common import GRAPHQL_REPOSITORY, REPO, parse_workdir


def gh(args: list[str]) -> str:
    r = subprocess.run(["gh", *args], capture_output=True, text=True, check=False)
    if r.returncode != 0:
        raise RuntimeError(r.stderr[-300:])
    return r.stdout


def base_oids(prs: list[int]) -> dict[int, str]:
    out: dict[int, str] = {}
    for i in range(0, len(prs), 50):
        batch = prs[i : i + 50]
        q = (
            "query { "
            + GRAPHQL_REPOSITORY
            + " { "
            + " ".join(
                f"p{n}: pullRequest(number: {n}) {{ number baseRefOid }}" for n in batch
            )
            + " } }"
        )
        data = json.loads(gh(["api", "graphql", "-f", f"query={q}"]))["data"][
            "repository"
        ]
        for n in batch:
            pr = data.get(f"p{n}")
            if pr:
                out[n] = pr["baseRefOid"]
    return out


def fetch_one(out: Path, pr: int, base: str, sha: str) -> str:
    dst = out / f"{pr}_{sha}.json"
    if dst.exists():
        return "skip"
    for _ in range(3):
        try:
            raw = gh(
                [
                    "api",
                    f"repos/{REPO}/compare/{base}...{sha}",
                    "--jq",
                    "{status, ahead_by, files: [.files[] | {filename, status, patch}]}",
                ]
            )
            dst.write_text(raw)
            return "ok"
        except RuntimeError as e:
            err = str(e)
    dst.with_suffix(".err").write_text(err)
    return "fail"


def main() -> None:
    corpus = parse_workdir(__doc__) / "corpus"
    out = corpus / "review_diffs"
    out.mkdir(exist_ok=True)
    threads = [json.loads(line) for line in (corpus / "threads.jsonl").open()]
    comments = {
        c["id"]: c
        for c in (json.loads(line) for line in (corpus / "pull_comments.jsonl").open())
    }
    pairs = sorted(
        {
            (t["pr"], comments[t["id"]]["commit_id"])
            for t in threads
            if comments[t["id"]].get("commit_id")
        }
    )
    prs = sorted({p for p, _ in pairs})
    bases = base_oids(prs)
    print(
        f"{len(pairs)} (pr, commit) pairs over {len(prs)} PRs; {len(bases)} base oids",
        file=sys.stderr,
    )
    jobs = [(pr, bases[pr], sha) for pr, sha in pairs if pr in bases]
    with ThreadPoolExecutor(max_workers=12) as pool:
        results = Counter(pool.map(lambda j: fetch_one(out, *j), jobs))
    print(dict(results), file=sys.stderr)


if __name__ == "__main__":
    main()
