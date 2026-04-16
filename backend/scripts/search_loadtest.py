"""
Load test for the Onyx search flow (/api/search/send-search-message).

Usage:
    source .venv/bin/activate
    python backend/scripts/search_loadtest.py --help
"""

from __future__ import annotations

import argparse
import os
import random
import statistics
import threading
import time
from collections import Counter
from pathlib import Path

import httpx
from pydantic import BaseModel

from ee.onyx.server.query_and_chat.models import SendSearchQueryRequest
from onyx.configs.constants import DocumentSource
from onyx.context.search.models import BaseFilters


DEFAULT_TEST_QUERIES = [
    "onboarding checklist",
    "how do we handle refunds",
    "password reset policy",
    "quarterly planning process",
    "incident response runbook",
    "deployment pipeline overview",
    "vacation policy",
    "customer escalation procedure",
]


class Result(BaseModel):
    model_config = {"frozen": True}

    status: int
    latency_s: float
    bytes_received: int
    error: str | None = None


class Queries(BaseModel):
    model_config = {"frozen": True}

    queries: list[str]
    source_types: set[DocumentSource] | None = None

    def get_random_query(self) -> str:
        return random.choice(self.queries)

    def get_random_source_type_set_or_none(self) -> list[DocumentSource] | None:
        if self.source_types is None:
            return None
        source_types_list = sorted(self.source_types)
        return random.sample(
            source_types_list, random.randint(0, len(source_types_list))
        )


class StopCondition:
    def __init__(self, num_requests_to_make: int | None, duration_s: float | None):
        assert (
            num_requests_to_make is not None or duration_s is not None
        ), "Either num_requests_to_make or timestamp_to_stop_making_requests_s must be provided."
        self._num_requests_to_make: int | None = num_requests_to_make
        self._duration_s: float | None = duration_s
        self._timestamp_to_stop_making_requests_s: float | None = (
            time.perf_counter() + self._duration_s if self._duration_s else None
        )

    def should_stop(self, num_requests_made: int, current_timestamp_s: float) -> bool:
        requests_condition_met = False
        timestamp_condition_met = False
        if self._num_requests_to_make is not None:
            requests_condition_met = num_requests_made >= self._num_requests_to_make
        if self._timestamp_to_stop_making_requests_s is not None:
            timestamp_condition_met = (
                current_timestamp_s >= self._timestamp_to_stop_making_requests_s
            )
        return requests_condition_met or timestamp_condition_met

    def __str__(self) -> str:
        if self._num_requests_to_make is not None and self._duration_s is not None:
            return (
                f"Stop condition: make {self._num_requests_to_make} request(s) or make requests for "
                f"{self._duration_s}s, whichever comes first."
            )
        if self._num_requests_to_make is not None:
            return f"Stop condition: make {self._num_requests_to_make} request(s)."
        if self._duration_s is not None:
            return f"Stop condition: make requests for {self._duration_s}s."
        raise ValueError("Bug: Invalid stop condition.")


def make_one_search_request(
    client: httpx.Client,
    search_url: str,
    request_headers: dict[str, str],
    request_body: SendSearchQueryRequest,
    timeout_s: float,
) -> Result:
    request_body_dict = request_body.model_dump()
    start = time.perf_counter()
    try:
        resp = client.post(
            search_url,
            json=request_body_dict,
            headers=request_headers,
            timeout=timeout_s,
        )
        body = resp.content
        return Result(
            status=resp.status_code,
            latency_s=time.perf_counter() - start,
            bytes_received=len(body),
            error=(
                None
                if resp.status_code == 200
                else body[:512].decode("utf-8", "replace")
            ),
        )
    except httpx.TimeoutException:
        return Result(
            status=0,
            latency_s=time.perf_counter() - start,
            bytes_received=0,
            error="timeout",
        )
    except Exception as e:
        return Result(
            status=0,
            latency_s=time.perf_counter() - start,
            bytes_received=0,
            error=f"{type(e).__name__}: {e}",
        )


def worker_loop(
    search_url: str,
    request_headers: dict[str, str],
    base_request_body: SendSearchQueryRequest,
    queries: Queries,
    timeout_s: float,
    results: list[Result],
    results_lock: threading.Lock,
    stop_condition: StopCondition,
) -> None:
    thread_local_base_request_body = base_request_body.model_copy()
    with httpx.Client() as client:
        num_requests_made = 0
        timestamp_s = time.perf_counter()
        while not stop_condition.should_stop(
            num_requests_made=num_requests_made, current_timestamp_s=timestamp_s
        ):
            thread_local_base_request_body.search_query = queries.get_random_query()
            source_type_filter = queries.get_random_source_type_set_or_none()
            thread_local_base_request_body.filters = None
            if source_type_filter:
                thread_local_base_request_body.filters = BaseFilters(
                    source_type=source_type_filter
                )
            result = make_one_search_request(
                client,
                search_url,
                request_headers,
                thread_local_base_request_body,
                timeout_s,
            )
            with results_lock:
                results.append(result)
            num_requests_made += 1
            timestamp_s = time.perf_counter()


def summarize(results: list[Result], wall_time_s: float) -> None:
    if not results:
        print("No results.")
        return
    oks = [r for r in results if r.status == 200]
    fails = [r for r in results if r.status != 200]
    lats = [r.latency_s for r in oks]
    print()
    print(f"Wall time:          {wall_time_s:.3f}s")
    print(f"Total requests:     {len(results)}")
    print(f"Successful (200):   {len(oks)}")
    print(f"Failed:             {len(fails)}")
    if lats:
        print(f"Throughput (ok):    {len(oks) / wall_time_s:.3f} req/s")
        print(f"Round trip latency mean:       {statistics.mean(lats):.3f}s")
        if len(lats) >= 100:
            # quantiles(n=100) returns 99 cut points: indices 0..98 => p1..p99.
            percentiles = statistics.quantiles(lats, n=100)
            print(f"Round trip latency p50:        {percentiles[49]:.3f}s")
            print(f"Round trip latency p90:        {percentiles[89]:.3f}s")
            print(f"Round trip latency p95:        {percentiles[94]:.3f}s")
            print(f"Round trip latency p99:        {percentiles[98]:.3f}s")
        print(f"Round trip latency max:        {max(lats):.3f}s")
    if fails:
        err_counts = Counter((r.status, (r.error or "")[:512]) for r in fails)
        print()
        print("Failure breakdown:")
        for (status, err), n in err_counts.most_common(10):
            print(f"  [{status}] x{n}  {err}")


def load_queries_and_source_types(args: argparse.Namespace) -> Queries:
    source_types = load_source_types(args)
    if args.queries_file:
        path = Path(os.path.expanduser(args.queries_file))
        queries = [ln.strip() for ln in path.read_text().splitlines() if ln.strip()]
        if not queries:
            raise SystemExit(f"No queries found in {path}")
        return Queries(queries=queries, source_types=source_types)
    if args.query:
        return Queries(queries=[args.query], source_types=source_types)
    return Queries(queries=DEFAULT_TEST_QUERIES, source_types=source_types)


def load_token(args: argparse.Namespace) -> str:
    if args.token:
        return args.token.strip()
    if args.token_file:
        return Path(os.path.expanduser(args.token_file)).read_text().strip()
    env = os.environ.get("ONYX_ACCESS_TOKEN")
    if env:
        return env.strip()
    raise SystemExit("Provide --token, --token-file, or ONYX_ACCESS_TOKEN env var.")


def load_source_types(args: argparse.Namespace) -> set[DocumentSource] | None:
    if args.source_types:
        return {DocumentSource(s) for s in args.source_types.split(",")}
    return None


def run_load_test(
    search_url: str,
    request_headers: dict[str, str],
    base_request_body: SendSearchQueryRequest,
    queries: Queries,
    timeout_s: float,
    concurrency: int,
    results: list[Result],
    results_lock: threading.Lock,
    stop_condition: StopCondition,
) -> None:
    threads = [
        threading.Thread(
            target=lambda: worker_loop(
                search_url,
                request_headers,
                base_request_body,
                queries,
                timeout_s,
                results,
                results_lock,
                stop_condition,
            ),
            daemon=True,
        )
        for _ in range(concurrency)
    ]

    for t in threads:
        t.start()

    for t in threads:
        t.join()


def run(args: argparse.Namespace) -> None:
    token = load_token(args)
    queries = load_queries_and_source_types(args)
    base_url = args.url.rstrip("/")
    # Accept either the bare host (https://st-dev.onyx.app) or one ending in
    # /api.
    api_root = base_url if base_url.endswith("/api") else base_url + "/api"
    search_url = f"{api_root}/search/send-search-message"

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    timeout_s = args.timeout

    # Preflight: Verify connectivity and auth so we fail fast on URL / token
    # issues.
    with httpx.Client() as client:
        for label, url in [
            ("health", f"{api_root}/health"),
            ("me", f"{api_root}/me"),
        ]:
            print(f"Preflight {label} -> {url}")
            start = time.perf_counter()
            try:
                resp = client.get(url=url, headers=headers, timeout=timeout_s)
            except Exception as e:
                raise SystemExit(f"{type(e).__name__}: {e}")
            latency = time.perf_counter() - start
            print(
                f"  status={resp.status_code}  latency={latency:.3f}s  bytes={len(resp.content)}."
            )
            if resp.status_code != 200:
                print(f"  error: {resp.content[:1024].decode('utf-8', 'replace')}")
                raise SystemExit(f"Preflight '{label}' failed; aborting load test.")

    print()
    print(f"Load test: concurrency={args.concurrency}.")
    base_request = SendSearchQueryRequest(
        search_query="",  # Overwritten per request.
    )
    if args.num_hits:
        base_request.num_hits = args.num_hits
    stop_condition = StopCondition(
        num_requests_to_make=(
            args.requests_per_worker if args.requests_per_worker else None
        ),
        duration_s=args.duration_per_worker if args.duration_per_worker else None,
    )
    print(str(stop_condition))
    results: list[Result] = []
    results_lock = threading.Lock()
    t0 = time.perf_counter()
    run_load_test(
        search_url=search_url,
        request_headers=headers,
        base_request_body=base_request,
        queries=queries,
        timeout_s=timeout_s,
        concurrency=args.concurrency,
        results=results,
        results_lock=results_lock,
        stop_condition=stop_condition,
    )
    wall_time_s = time.perf_counter() - t0

    summarize(results=results, wall_time_s=wall_time_s)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="A load test tool for the Onyx search endpoint."
    )
    parser.add_argument(
        "--url", required=True, help="Onyx base URL, e.g. https://cloud.onyx.app"
    )
    parser.add_argument(
        "--token",
        help="Bearer token (onyx_pat_...). Or use --token-file / $ONYX_ACCESS_TOKEN.",
    )
    parser.add_argument(
        "-f",
        "--token-file",
        help="Path to a file containing a bearer token. Or use --token / $ONYX_ACCESS_TOKEN.",
    )
    parser.add_argument(
        "-c",
        "--concurrency",
        type=int,
        default=1,
        help="Number of concurrent workers making requests.",
    )
    parser.add_argument(
        "-r",
        "--requests-per-worker",
        type=int,
        help=(
            "Total number of requests to make per worker. If specified along with --duration-per-worker, the worker "
            "will stop on whichever condition is met first."
        ),
    )
    parser.add_argument(
        "-d",
        "--duration-per-worker",
        type=float,
        help=(
            "Duration in seconds each worker will run for. If specified along with --requests-per-worker, the worker "
            "will stop on whichever condition is met first."
        ),
    )
    parser.add_argument(
        "--timeout", type=float, default=30.0, help="Per-request timeout in seconds."
    )
    parser.add_argument(
        "--queries-file", help="File with one query per line. Or use --query."
    )
    parser.add_argument(
        "-q", "--query", help="Single literal query used for every request."
    )
    parser.add_argument(
        "--num-hits",
        type=int,
        default=10,
        help="Number of hits to retrieve per request.",
    )
    parser.add_argument(
        "--source-types",
        help=(
            "Comma-separated list of source types to filter by. The specific source types to filter by will be "
            "randomly selected per request from this list. If not specified, there will be no source type filter for "
            "all requests."
        ),
    )
    args = parser.parse_args()

    if not args.requests_per_worker and not args.duration_per_worker:
        parser.error(
            "No stop condition specified. Must specify either --requests-per-worker or --duration-per-worker."
        )
    if args.concurrency <= 0:
        parser.error("Concurrency must be greater than 0.")
    if args.timeout <= 0:
        parser.error("Timeout must be greater than 0.")
    if args.num_hits <= 0:
        parser.error("Number of hits must be greater than 0.")

    try:
        run(args)
    except KeyboardInterrupt:
        print("Interrupted.")


if __name__ == "__main__":
    main()
