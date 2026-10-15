"""Fetch PR metadata and review-thread resolution state for every PR the target
reviewers commented on. Reads corpus/pull_comments.jsonl, writes corpus/pr_meta.jsonl
and corpus/thread_state.jsonl. Rerunnable: skips PRs already present in pr_meta.jsonl.

Usage: fetch_pr_meta.py [--workdir DIR]. Needs an authenticated `gh`."""

import json
import subprocess
import sys

from common import GRAPHQL_REPOSITORY, REVIEWERS, parse_workdir

BATCH = 25

PR_FIELDS = """
  number title merged mergedAt closed state createdAt
  author { login } additions deletions changedFiles baseRefName
  reviewThreads(first: 100%s) {
    pageInfo { hasNextPage endCursor }
    nodes { isResolved isOutdated comments(first: 1) { nodes { databaseId } } }
  }
"""


def gql(query: str) -> dict:
    out = subprocess.run(
        ["gh", "api", "graphql", "-f", f"query={query}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if out.returncode != 0:
        raise RuntimeError(out.stderr[-500:])
    data = json.loads(out.stdout)
    if "errors" in data and not data.get("data"):
        raise RuntimeError(json.dumps(data["errors"])[:500])
    return data["data"]


def fetch_batch(numbers: list[int]) -> list[dict]:
    parts = [f"p{n}: pullRequest(number: {n}) {{ {PR_FIELDS % ''} }}" for n in numbers]
    q = "query { " + GRAPHQL_REPOSITORY + " { " + " ".join(parts) + " } }"
    repo = gql(q)["repository"]
    prs = []
    for n in numbers:
        pr = repo.get(f"p{n}")
        if pr is None:
            continue
        threads = pr["reviewThreads"]["nodes"]
        page = pr["reviewThreads"]["pageInfo"]
        while page["hasNextPage"]:
            more = gql(
                "query { %s { pullRequest(number: %d) { %s } } }"
                % (GRAPHQL_REPOSITORY, n, PR_FIELDS % f', after: "{page["endCursor"]}"')
            )["repository"]["pullRequest"]["reviewThreads"]
            threads.extend(more["nodes"])
            page = more["pageInfo"]
        pr["reviewThreads"] = threads
        prs.append(pr)
    return prs


def main() -> None:
    corpus = parse_workdir(__doc__) / "corpus"
    comments = (json.loads(line) for line in (corpus / "pull_comments.jsonl").open())
    wanted = sorted({c["pr"] for c in comments if c["author"] in REVIEWERS})
    meta_path = corpus / "pr_meta.jsonl"
    state_path = corpus / "thread_state.jsonl"
    done = set()
    if meta_path.exists():
        done = {json.loads(line)["number"] for line in meta_path.open()}
    todo = [n for n in wanted if n not in done]
    print(
        f"{len(wanted)} PRs with reviewer comments, {len(todo)} to fetch",
        file=sys.stderr,
    )
    with meta_path.open("a") as meta_f, state_path.open("a") as state_f:
        for i in range(0, len(todo), BATCH):
            batch = todo[i : i + BATCH]
            for attempt in range(4):
                try:
                    prs = fetch_batch(batch)
                    break
                except RuntimeError as e:
                    print(f"batch {i} attempt {attempt} failed: {e}", file=sys.stderr)
                    if attempt == 3:
                        raise
            for pr in prs:
                threads = pr.pop("reviewThreads")
                for t in threads:
                    first = t["comments"]["nodes"]
                    if not first:
                        continue
                    state_f.write(
                        json.dumps(
                            {
                                "root_id": first[0]["databaseId"],
                                "pr": pr["number"],
                                "resolved": t["isResolved"],
                                "outdated": t["isOutdated"],
                            }
                        )
                        + "\n"
                    )
                pr["author"] = (pr.get("author") or {}).get("login")
                meta_f.write(json.dumps(pr) + "\n")
            meta_f.flush()
            state_f.flush()
            print(f"fetched {min(i + BATCH, len(todo))}/{len(todo)}", file=sys.stderr)


if __name__ == "__main__":
    main()
