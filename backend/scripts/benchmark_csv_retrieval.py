"""
Benchmark document retrieval quality against Onyx's search endpoint.

Usage:
    python backend/scripts/benchmark_csv_retrieval.py \
        --input benchmark.csv \
        [--base-url http://localhost:3000] \
        [--email admin@example.com] \
        [--password ...] \
        [--top-k 10] \
        [--num-hits 30] \
        [--output results.txt]

Input CSV format (has header row):
    question,expected_file
    "What is the Q1 revenue?",financials.xlsx
    "Who manages the West region?",sales_territories.csv

Matches expected_file against each result's semantic_identifier
(case-insensitive substring match).

Credentials default to $ONYX_BENCH_EMAIL / $ONYX_BENCH_PASSWORD.
"""

import argparse
import csv
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlencode

import requests


@dataclass
class QueryResult:
    query: str
    expected_file: str
    rank: int | None  # 1-indexed, None if not found
    score: float | None  # score of the matched doc, None if not found
    num_results: int
    top_results: list[
        tuple[str, float | None]
    ]  # (semantic_identifier, score) for top 3


def login(base_url: str, email: str, password: str) -> dict[str, str]:
    resp = requests.post(
        f"{base_url}/api/auth/login",
        data=urlencode({"username": email, "password": password}),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    resp.raise_for_status()
    cookie = resp.cookies.get("fastapiusersauth")
    if not cookie:
        raise RuntimeError("Login succeeded but no session cookie returned")
    return {
        "Content-Type": "application/json",
        "Cookie": f"fastapiusersauth={cookie}",
    }


MAX_QUERY_ATTEMPTS = 3
RETRY_BACKOFF_S = 2


def search(
    base_url: str, headers: dict[str, str], query: str, num_hits: int
) -> list[dict]:
    """Run one search query, retrying transient failures.

    Retries up to MAX_QUERY_ATTEMPTS total on any request error or
    non-2xx response. If every attempt fails, returns an empty result
    list so the caller records the query as a miss instead of aborting
    the whole benchmark.
    """
    last_error: Exception | None = None
    for attempt in range(1, MAX_QUERY_ATTEMPTS + 1):
        try:
            resp = requests.post(
                f"{base_url}/api/search/send-search-message",
                json={
                    "search_query": query,
                    "num_hits": num_hits,
                    "stream": False,
                },
                headers=headers,
                timeout=60,
            )
            resp.raise_for_status()
            return resp.json()["search_docs"]
        except (requests.RequestException, ValueError, KeyError) as e:
            last_error = e
            if attempt < MAX_QUERY_ATTEMPTS:
                print(
                    f"    attempt {attempt}/{MAX_QUERY_ATTEMPTS} failed: {e!r}; "
                    f"retrying in {RETRY_BACKOFF_S}s..."
                )
                time.sleep(RETRY_BACKOFF_S)
            else:
                print(
                    f"    attempt {attempt}/{MAX_QUERY_ATTEMPTS} failed: {e!r}; "
                    "giving up on this query"
                )
    print(
        f"    SKIPPED after {MAX_QUERY_ATTEMPTS} attempts — last error: {last_error!r}"
    )
    return []


def find_rank(
    documents: list[dict], expected_file: str, top_k: int
) -> tuple[int | None, float | None]:
    expected_lower = expected_file.lower()
    for i, doc in enumerate(documents[:top_k]):
        if expected_lower in doc.get("semantic_identifier", "").lower():
            return i + 1, doc.get("score")
    return None, None


def run_benchmark(
    base_url: str,
    headers: dict[str, str],
    queries: list[tuple[str, str]],
    top_k: int,
    num_hits: int,
) -> list[QueryResult]:
    results: list[QueryResult] = []
    for i, (query, expected_file) in enumerate(queries, 1):
        print(f"  [{i}/{len(queries)}] {query[:60]}...")
        documents = search(base_url, headers, query, num_hits)
        rank, score = find_rank(documents, expected_file, top_k)
        top_results = [
            (doc.get("semantic_identifier", "???"), doc.get("score"))
            for doc in documents[:3]
        ]
        results.append(
            QueryResult(
                query=query,
                expected_file=expected_file,
                rank=rank,
                score=score,
                num_results=len(documents),
                top_results=top_results,
            )
        )
    return results


def build_report(results: list[QueryResult], top_k: int) -> str:
    lines: list[str] = []
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    n = len(results)

    # Header
    lines.append(f"Retrieval Benchmark — {timestamp}")
    lines.append(f"Queries: {n}, Top-K: {top_k}")
    lines.append("")

    # Aggregate metrics
    k_values = sorted({1, 3, 5, top_k})
    recall: dict[int, float] = {}
    for k in k_values:
        if k > top_k:
            break
        found = sum(1 for r in results if r.rank is not None and r.rank <= k)
        recall[k] = found / n if n else 0
        lines.append(f"Recall@{k}: {found}/{n} ({recall[k]:.1%})")

    reciprocal_ranks = [1.0 / r.rank if r.rank else 0.0 for r in results]
    mrr = sum(reciprocal_ranks) / n if n else 0
    lines.append(f"MRR: {mrr:.4f}")

    misses = sum(1 for r in results if r.rank is None)
    lines.append(f"Misses: {misses}/{n}")
    lines.append("")

    # Per-query detail
    lines.append("Per-query results:")
    lines.append("-" * 70)
    for i, r in enumerate(results, 1):
        if r.rank is not None:
            score_str = f"{r.score:.4f}" if r.score is not None else "N/A"
            status = f"rank {r.rank}, score {score_str}"
        else:
            status = f"NOT FOUND (searched {r.num_results} results)"
        lines.append(f"[{i}] {status}")
        lines.append(f"    Q: {r.query}")
        lines.append(f"    Expected: {r.expected_file}")
        if r.rank is None and r.top_results:
            lines.append("    Top results returned:")
            for j, (name, s) in enumerate(r.top_results, 1):
                s_str = f"{s:.4f}" if s is not None else "N/A"
                lines.append(f"      {j}. {name} (score: {s_str})")
        lines.append("")

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Benchmark retrieval quality against Onyx search"
    )
    parser.add_argument(
        "--input", required=True, help="CSV file with (question, expected_file) rows"
    )
    parser.add_argument(
        "--base-url", default="http://localhost:3000", help="Onyx base URL"
    )
    parser.add_argument(
        "--email",
        default=os.environ.get("ONYX_BENCH_EMAIL"),
        help="Admin email (default: $ONYX_BENCH_EMAIL)",
    )
    parser.add_argument(
        "--password",
        default=os.environ.get("ONYX_BENCH_PASSWORD"),
        help="Admin password (default: $ONYX_BENCH_PASSWORD)",
    )
    parser.add_argument(
        "--top-k", type=int, default=10, help="Number of results to consider"
    )
    parser.add_argument(
        "--num-hits", type=int, default=30, help="Number of hits to request from search"
    )
    parser.add_argument(
        "--output", default="benchmark_results.txt", help="Output file for full report"
    )
    args = parser.parse_args()

    if not args.email or not args.password:
        print(
            "Set ONYX_BENCH_EMAIL and ONYX_BENCH_PASSWORD "
            "(or pass --email/--password).",
            file=sys.stderr,
        )
        sys.exit(1)

    # Load queries
    queries: list[tuple[str, str]] = []
    with open(args.input, newline="") as f:
        reader = csv.reader(f)
        next(reader, None)  # skip header row
        for row in reader:
            if len(row) < 2:
                continue
            question, expected_file = row[0].strip(), row[1].strip()
            if question and expected_file:
                queries.append((question, expected_file))

    if not queries:
        print("No valid queries found in input CSV.", file=sys.stderr)
        sys.exit(1)

    print(f"Loaded {len(queries)} queries from {args.input}")

    # Login
    headers = login(args.base_url, args.email, args.password)

    # Run
    print("Running queries...")
    results = run_benchmark(args.base_url, headers, queries, args.top_k, args.num_hits)

    # Report
    report = build_report(results, args.top_k)

    with open(args.output, "w") as f:
        f.write(report)

    # Print summary
    n = len(results)
    found = sum(1 for r in results if r.rank is not None and r.rank <= args.top_k)
    mrr = sum(1.0 / r.rank if r.rank else 0.0 for r in results) / n
    print(f"\nRecall@{args.top_k}: {found}/{n} ({found / n:.1%}), MRR: {mrr:.4f}")
    print(f"Full report written to {args.output}")


if __name__ == "__main__":
    main()
